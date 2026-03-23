#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Official account search and management services."""

from __future__ import annotations

from bs4 import BeautifulSoup

from article_service import query_local_articles, upsert_articles
from database import Database
from log_utils import get_logger
from mp_client import WechatMPClient
from sync_service import sync_account
from utils import failure, normalize_mp_article_url, now_ts, success


LOGGER = get_logger(__name__)


def _resolve_account(db: Database, fakeid: str = "", nickname: str = "") -> dict | None:
    if fakeid:
        return db.row("SELECT * FROM account WHERE fakeid = ?", (fakeid,))
    if nickname:
        return db.row("SELECT * FROM account WHERE nickname = ?", (nickname,))
    return None


def _pick_exact_match(accounts: list[dict], keyword: str) -> dict | None:
    normalized_keyword = keyword.strip().casefold()
    exact_matches = [
        item
        for item in accounts
        if str(item.get("nickname", "")).strip().casefold() == normalized_keyword
        or str(item.get("alias", "")).strip().casefold() == normalized_keyword
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(accounts) == 1:
        return accounts[0]
    return None


def _extract_account_name_from_article_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in [".wx_follow_nickname", "#js_name", "mp-common-profile"]:
        node = soup.select_one(selector)
        if not node:
            continue
        if selector == "mp-common-profile":
            candidate = str(node.get("data-nickname") or "").strip()
        else:
            candidate = node.get_text(strip=True)
        if candidate:
            return candidate
    meta = soup.find("meta", attrs={"property": "profile:nickname"})
    return str(meta.get("content") or "").strip() if meta else ""


def search_account(db: Database, keyword: str, limit: int = 10) -> dict:
    LOGGER.debug("search_account keyword=%s limit=%s", keyword, limit)
    client = WechatMPClient(db)
    accounts = client.search_accounts(keyword, count=limit)
    return success(
        {
            "keyword": keyword,
            "total": len(accounts),
            "accounts": accounts,
        },
        f"搜索到 {len(accounts)} 个公众号候选",
    )


def add_account(
    db: Database,
    fakeid: str,
    nickname: str,
    alias: str = "",
    avatar: str = "",
    service_type: int = 0,
    signature: str = "",
    enable_sync: bool = True,
    sync_hour: int = 8,
    sync_minute: int = 0,
    initial_sync: bool = False,
) -> dict:
    if not fakeid or not nickname:
        return failure("添加公众号时必须提供 fakeid 和 nickname")
    LOGGER.info("add_account fakeid=%s nickname=%s initial_sync=%s", fakeid, nickname, initial_sync)
    now = now_ts()
    with db.transaction():
        db.connection.execute(
            """
            INSERT INTO account
            (fakeid, nickname, alias, avatar, service_type, signature, enabled, total_count, articles_synced, last_sync_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT total_count FROM account WHERE fakeid = ?), 0), COALESCE((SELECT articles_synced FROM account WHERE fakeid = ?), 0), (SELECT last_sync_at FROM account WHERE fakeid = ?), COALESCE((SELECT created_at FROM account WHERE fakeid = ?), ?), ?)
            ON CONFLICT(fakeid) DO UPDATE SET
              nickname = excluded.nickname,
              alias = excluded.alias,
              avatar = excluded.avatar,
              service_type = excluded.service_type,
              signature = excluded.signature,
              enabled = excluded.enabled,
              updated_at = excluded.updated_at
            """,
            (
                fakeid,
                nickname,
                alias or "",
                avatar or "",
                int(service_type or 0),
                signature or "",
                1 if enable_sync else 0,
                fakeid,
                fakeid,
                fakeid,
                fakeid,
                now,
                now,
            ),
        )
        db.connection.execute(
            """
            INSERT INTO sync_config
            (fakeid, enabled, sync_hour, sync_minute, last_sync_at, last_sync_status, last_sync_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT last_sync_at FROM sync_config WHERE fakeid = ?), NULL), COALESCE((SELECT last_sync_status FROM sync_config WHERE fakeid = ?), ''), COALESCE((SELECT last_sync_message FROM sync_config WHERE fakeid = ?), ''), COALESCE((SELECT created_at FROM sync_config WHERE fakeid = ?), ?), ?)
            ON CONFLICT(fakeid) DO UPDATE SET
              enabled = excluded.enabled,
              sync_hour = excluded.sync_hour,
              sync_minute = excluded.sync_minute,
              updated_at = excluded.updated_at
            """,
            (
                fakeid,
                1 if enable_sync else 0,
                sync_hour,
                sync_minute,
                fakeid,
                fakeid,
                fakeid,
                fakeid,
                now,
                now,
            ),
        )
    sync_result = None
    if initial_sync:
        sync_result = sync_account(db, fakeid)
    return success(
        {
            "fakeid": fakeid,
            "nickname": nickname,
            "alias": alias,
            "avatar": avatar,
            "enabled": enable_sync,
            "sync_hour": sync_hour,
            "sync_minute": sync_minute,
            "initial_sync": sync_result,
        },
        f"已添加公众号: {nickname}",
    )


def add_account_by_keyword(db: Database, keyword: str, limit: int = 10, initial_sync: bool = False) -> dict:
    LOGGER.info("add_account_by_keyword keyword=%s limit=%s initial_sync=%s", keyword, limit, initial_sync)
    result = search_account(db, keyword, limit=limit)
    if not result.get("success"):
        return result
    accounts = result["data"]["accounts"]
    if not accounts:
        return failure(f"未找到关键字“{keyword}”对应的公众号")

    account = _pick_exact_match(accounts, keyword)
    if not account:
        return failure(
            "存在多个候选公众号，请先执行 search-account 再明确 fakeid 添加",
            {
                "keyword": keyword,
                "accounts": accounts,
            },
        )

    return add_account(
        db,
        fakeid=str(account.get("fakeid") or ""),
        nickname=str(account.get("nickname") or ""),
        alias=str(account.get("alias") or ""),
        avatar=str(account.get("round_head_img") or ""),
        service_type=int(account.get("service_type") or 0),
        signature=str(account.get("signature") or ""),
        initial_sync=initial_sync,
    )


def resolve_account_by_url(db: Database, url: str, limit: int = 20) -> dict:
    normalized_url = normalize_mp_article_url(url)
    LOGGER.info("resolve_account_by_url url=%s limit=%s", normalized_url, limit)
    client = WechatMPClient(db)
    html = client.fetch_public_article(normalized_url)
    account_name = _extract_account_name_from_article_html(html)
    if not account_name:
        return failure("未能从文章链接中解析出公众号名称", {"url": normalized_url})

    candidates = client.search_accounts(account_name, count=limit)
    exact_matches = [
        item
        for item in candidates
        if str(item.get("nickname", "")).strip() == account_name
        or str(item.get("alias", "")).strip() == account_name
    ]
    matched_accounts = exact_matches or candidates
    return success(
        {
            "url": normalized_url,
            "resolved_name": account_name,
            "total": len(matched_accounts),
            "accounts": matched_accounts,
        },
        f"已从文章链接解析公众号名称: {account_name}",
    )


def add_account_by_url(db: Database, url: str, limit: int = 20, initial_sync: bool = False) -> dict:
    LOGGER.info("add_account_by_url url=%s limit=%s initial_sync=%s", url, limit, initial_sync)
    resolved = resolve_account_by_url(db, url=url, limit=limit)
    if not resolved.get("success"):
        return resolved

    account_name = resolved["data"]["resolved_name"]
    accounts = resolved["data"]["accounts"]
    account = _pick_exact_match(accounts, account_name)
    if not account:
        return failure(
            "根据文章链接解析出了公众号名称，但候选公众号不唯一，请先执行 resolve-account-url 确认",
            resolved["data"],
        )

    return add_account(
        db,
        fakeid=str(account.get("fakeid") or ""),
        nickname=str(account.get("nickname") or ""),
        alias=str(account.get("alias") or ""),
        avatar=str(account.get("round_head_img") or ""),
        service_type=int(account.get("service_type") or 0),
        signature=str(account.get("signature") or ""),
        initial_sync=initial_sync,
    )


def list_accounts(db: Database) -> dict:
    rows = db.rows(
        """
        SELECT
          a.fakeid, a.nickname, a.alias, a.avatar, a.service_type, a.signature,
          a.enabled, a.total_count, a.articles_synced, a.last_sync_at,
          s.sync_hour, s.sync_minute, s.last_sync_status, s.last_sync_message
        FROM account a
        LEFT JOIN sync_config s ON s.fakeid = a.fakeid
        ORDER BY a.updated_at DESC
        """
    )
    return success(
        {
            "total": len(rows),
            "accounts": rows,
        },
        f"当前共 {len(rows)} 个公众号",
    )


def delete_account(db: Database, fakeid: str = "", nickname: str = "") -> dict:
    account = _resolve_account(db, fakeid=fakeid, nickname=nickname)
    if not account:
        return failure("未找到指定公众号")
    LOGGER.info("delete_account fakeid=%s nickname=%s", account["fakeid"], account.get("nickname", ""))
    fakeid = account["fakeid"]
    with db.transaction():
        db.connection.execute("DELETE FROM account WHERE fakeid = ?", (fakeid,))
        db.connection.execute("DELETE FROM sync_config WHERE fakeid = ?", (fakeid,))
        db.connection.execute("DELETE FROM article_detail WHERE fakeid = ?", (fakeid,))
        db.connection.execute("DELETE FROM article WHERE fakeid = ?", (fakeid,))
    return success(
        {
            "fakeid": fakeid,
            "nickname": account.get("nickname", ""),
        },
        f"已删除公众号: {account.get('nickname') or fakeid}",
    )


def set_sync_target(
    db: Database,
    fakeid: str = "",
    nickname: str = "",
    enabled: bool | None = None,
    sync_hour: int | None = None,
    sync_minute: int | None = None,
) -> dict:
    account = _resolve_account(db, fakeid=fakeid, nickname=nickname)
    if not account:
        return failure("未找到指定公众号")
    LOGGER.info(
        "set_sync_target fakeid=%s enabled=%s sync_hour=%s sync_minute=%s",
        account["fakeid"],
        enabled,
        sync_hour,
        sync_minute,
    )
    fakeid = account["fakeid"]
    current = db.row("SELECT * FROM sync_config WHERE fakeid = ?", (fakeid,)) or {}
    now = now_ts()
    db.execute(
        """
        INSERT INTO sync_config
        (fakeid, enabled, sync_hour, sync_minute, last_sync_at, last_sync_status, last_sync_message, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fakeid) DO UPDATE SET
          enabled = excluded.enabled,
          sync_hour = excluded.sync_hour,
          sync_minute = excluded.sync_minute,
          updated_at = excluded.updated_at
        """,
        (
            fakeid,
            1 if (enabled if enabled is not None else bool(current.get("enabled", 1))) else 0,
            sync_hour if sync_hour is not None else int(current.get("sync_hour", 8)),
            sync_minute if sync_minute is not None else int(current.get("sync_minute", 0)),
            current.get("last_sync_at"),
            current.get("last_sync_status", ""),
            current.get("last_sync_message", ""),
            current.get("created_at", now),
            now,
        ),
    )
    return success(
        db.row("SELECT * FROM sync_config WHERE fakeid = ?", (fakeid,)) or {},
        f"已更新同步配置: {account.get('nickname') or fakeid}",
    )


def list_sync_targets(db: Database) -> dict:
    rows = db.rows(
        """
        SELECT
          s.fakeid, a.nickname, s.enabled, s.sync_hour, s.sync_minute,
          s.last_sync_at, s.last_sync_status, s.last_sync_message
        FROM sync_config s
        LEFT JOIN account a ON a.fakeid = s.fakeid
        ORDER BY a.updated_at DESC, s.fakeid
        """
    )
    return success(
        {
            "total": len(rows),
            "targets": rows,
        },
        f"当前共 {len(rows)} 个同步目标",
    )


def list_account_articles(
    db: Database,
    fakeid: str = "",
    nickname: str = "",
    begin: int = 0,
    count: int = 10,
    keyword: str = "",
    remote: bool = True,
    save_remote: bool = True,
) -> dict:
    account = _resolve_account(db, fakeid=fakeid, nickname=nickname)
    if not account:
        return failure("未找到指定公众号")
    fakeid = account["fakeid"]
    LOGGER.debug(
        "list_account_articles fakeid=%s begin=%s count=%s keyword=%s remote=%s save_remote=%s",
        fakeid,
        begin,
        count,
        keyword,
        remote,
        save_remote,
    )

    if remote:
        client = WechatMPClient(db)
        payload = client.fetch_article_page(fakeid=fakeid, begin=begin, count=count, keyword=keyword)
        articles = payload["articles"]
        if save_remote:
            upsert_articles(db, fakeid, articles)
        returned_articles = articles[:count] if count and count > 0 else articles
        return success(
            {
                "fakeid": fakeid,
                "nickname": account.get("nickname", ""),
                "remote": True,
                "total_count": payload.get("total_count", 0),
                "fetched_count": len(articles),
                "returned_count": len(returned_articles),
                "articles": [dict(item, fakeid=fakeid) for item in returned_articles],
            },
            f"远端命中 {len(articles)} 篇文章，返回 {len(returned_articles)} 篇",
        )

    articles = query_local_articles(db, fakeid=fakeid, begin=begin, count=count, keyword=keyword)
    return success(
        {
            "fakeid": fakeid,
            "nickname": account.get("nickname", ""),
            "remote": False,
            "articles": articles,
            "total": len(articles),
        },
        f"本地返回 {len(articles)} 篇文章",
    )
