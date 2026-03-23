#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP client for WeChat MP requests with retry, rate-limit and proxy support."""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message="urllib3 .* doesn't match a supported version!")
warnings.filterwarnings("ignore", message=".*doesn't match a supported version!.*")

import json
import random
import re
import time
from typing import Any
from urllib.parse import quote, urlparse

import requests
from requests import Session
from requests.exceptions import ProxyError, RequestException

from config import DEFAULT_USER_AGENT
from database import Database
from log_utils import get_logger
from session_store import get_login_session
from utils import cookiejar_to_entities, normalize_mp_article_short_url

try:  # pragma: no cover - environment-specific
    from requests.exceptions import RequestsDependencyWarning

    warnings.filterwarnings("ignore", category=RequestsDependencyWarning)
except Exception:  # pragma: no cover - optional
    pass


class WechatRequestError(RuntimeError):
    pass


class WechatLoginExpiredError(WechatRequestError):
    pass


class WechatArticleAccessError(WechatRequestError):
    pass


LOGGER = get_logger(__name__)


class WechatMPClient:
    def __init__(self, db: Database):
        self.db = db
        self._last_request_at = 0.0
        self.rate_limit_seconds = 1.0

    def new_session(self, cookies: list[dict[str, Any]] | None = None) -> Session:
        session = requests.Session()
        session.headers.update(
            {
                "Referer": "https://mp.weixin.qq.com/",
                "Origin": "https://mp.weixin.qq.com",
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Encoding": "identity",
            }
        )
        for item in cookies or []:
            name = item.get("name")
            value = item.get("value")
            if not name or not value or value == "EXPIRED":
                continue
            session.cookies.set(
                name,
                value,
                domain=item.get("domain") or ".mp.weixin.qq.com",
                path=item.get("path") or "/",
            )
        return session

    def authenticated_session(self) -> tuple[Session, dict[str, Any]]:
        session_record = get_login_session(self.db)
        if not session_record or not session_record.get("token"):
            raise WechatLoginExpiredError("未找到有效登录态，请先扫码登录或导入登录信息")
        return self.new_session(session_record.get("cookies") or []), session_record

    def request(
        self,
        session: Session,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        operation: str = "api",
        timeout: int = 30,
        allow_redirects: bool = True,
        retries: int = 3,
    ) -> requests.Response:
        proxies = self._resolve_proxies(operation)
        last_error: Exception | None = None
        parsed_url = urlparse(url)
        safe_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
        for attempt in range(1, retries + 1):
            self._respect_rate_limit()
            try:
                LOGGER.debug(
                    "request start method=%s url=%s operation=%s attempt=%s proxies=%s",
                    method,
                    safe_url,
                    operation,
                    attempt,
                    bool(proxies),
                )
                response = session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                    proxies=proxies,
                )
                if response.status_code >= 500:
                    raise WechatRequestError(f"微信接口返回 HTTP {response.status_code}")
                LOGGER.debug(
                    "request ok method=%s url=%s operation=%s status=%s",
                    method,
                    safe_url,
                    operation,
                    response.status_code,
                )
                return response
            except ProxyError as exc:
                last_error = WechatRequestError(
                    f"代理连接失败，请检查 proxy-set 配置或先禁用代理后重试。原始错误: {exc}"
                )
                LOGGER.warning("request proxy error method=%s url=%s attempt=%s error=%s", method, safe_url, attempt, exc)
                if attempt == retries:
                    break
                time.sleep(1.2 * attempt + random.random())
            except (RequestException, WechatRequestError) as exc:
                last_error = exc
                LOGGER.warning("request failed method=%s url=%s attempt=%s error=%s", method, safe_url, attempt, exc)
                if attempt == retries:
                    break
                time.sleep(1.2 * attempt + random.random())
        raise WechatRequestError(str(last_error or "微信请求失败"))

    def request_json(
        self,
        session: Session,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        operation: str = "api",
        timeout: int = 30,
        allow_redirects: bool = True,
        retries: int = 3,
    ) -> dict[str, Any]:
        response = self.request(
            session,
            method,
            url,
            params=params,
            data=data,
            operation=operation,
            timeout=timeout,
            allow_redirects=allow_redirects,
            retries=retries,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise WechatRequestError(f"微信接口返回非 JSON 数据: {exc}") from exc

        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict) and base_resp.get("ret") not in (None, 0):
            message = str(base_resp.get("err_msg") or "微信接口返回错误")
            if "登录" in message or "过期" in message or "未登录" in message:
                raise WechatLoginExpiredError(message)
            raise WechatRequestError(message)
        return payload

    def validate_login(self) -> dict[str, Any]:
        LOGGER.debug("validate_login start")
        session, login = self.authenticated_session()
        response = self.request(
            session,
            "GET",
            "https://mp.weixin.qq.com/cgi-bin/home",
            params={"t": "home/index", "token": login["token"], "lang": "zh_CN"},
            operation="api",
        )
        html = response.text
        nickname_match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"(?P<value>[^"]+)"', html)
        head_img_match = re.search(r'wx\.cgiData\.head_img\s*=\s*"(?P<value>[^"]+)"', html)
        nickname = nickname_match.group("value") if nickname_match else login.get("nickname") or ""
        head_img = head_img_match.group("value") if head_img_match else login.get("head_img") or ""
        return {
            "logged_in": True,
            "nickname": nickname,
            "head_img": head_img,
            "token": login["token"],
            "cookies": cookiejar_to_entities(session.cookies),
        }

    def check_proxy_health(self, operation: str = "sync", timeout: int = 5) -> dict[str, Any]:
        LOGGER.debug("check_proxy_health operation=%s timeout=%s", operation, timeout)
        row = self.db.row("SELECT * FROM proxy_config WHERE name = 'default'") or {}
        result: dict[str, Any] = {
            "operation": operation,
            "enabled": bool(row.get("enabled")),
            "proxy_url": str(row.get("proxy_url") or ""),
            "apply_article_fetch": bool(row.get("apply_article_fetch")),
            "apply_sync": bool(row.get("apply_sync")),
            "applied": False,
            "healthy": None,
            "message": "",
        }
        if not result["enabled"]:
            result["message"] = "代理未启用"
            return result
        if not result["proxy_url"]:
            result["healthy"] = False
            result["message"] = "代理已启用但未配置 URL"
            return result

        proxies = self._resolve_proxies(operation)
        result["applied"] = proxies is not None
        if not proxies:
            result["message"] = "当前操作未启用代理"
            return result

        try:
            if operation == "article":
                health_url = self._build_article_gateway_url("https://mp.weixin.qq.com/")
                response = requests.get(health_url, timeout=timeout, allow_redirects=True)
            else:
                session = self.new_session()
                response = session.get(
                    "https://mp.weixin.qq.com/",
                    timeout=timeout,
                    allow_redirects=True,
                    proxies=proxies,
                )
            result["healthy"] = True
            result["status_code"] = response.status_code
            result["message"] = f"代理连通性正常，HTTP {response.status_code}"
            return result
        except RequestException as exc:
            result["healthy"] = False
            result["message"] = f"代理连通性检查失败: {exc}"
            return result

    def search_accounts(self, keyword: str, count: int = 10) -> list[dict[str, Any]]:
        LOGGER.debug("search_accounts keyword=%s count=%s", keyword, count)
        session, login = self.authenticated_session()
        payload = self.request_json(
            session,
            "GET",
            "https://mp.weixin.qq.com/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "begin": 0,
                "count": count,
                "query": keyword,
                "token": login["token"],
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            operation="api",
        )
        return payload.get("list") or []

    def fetch_article_page(
        self,
        fakeid: str,
        begin: int = 0,
        count: int = 5,
        keyword: str = "",
    ) -> dict[str, Any]:
        LOGGER.debug(
            "fetch_article_page fakeid=%s begin=%s count=%s keyword=%s",
            fakeid,
            begin,
            count,
            keyword,
        )
        session, login = self.authenticated_session()
        is_searching = bool(keyword)
        payload = self.request_json(
            session,
            "GET",
            "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
            params={
                "sub": "search" if is_searching else "list",
                "search_field": "7" if is_searching else "null",
                "begin": begin,
                "count": count,
                "query": keyword,
                "fakeid": fakeid,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
                "token": login["token"],
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            operation="sync",
        )
        publish_page = payload.get("publish_page")
        if not publish_page:
            return {"total_count": 0, "articles": []}
        page = json.loads(publish_page)
        articles: list[dict[str, Any]] = []
        for item in page.get("publish_list") or []:
            publish_info_raw = item.get("publish_info")
            if not publish_info_raw:
                continue
            publish_info = json.loads(publish_info_raw)
            for article in publish_info.get("appmsgex") or []:
                articles.append(article)
        LOGGER.debug(
            "fetch_article_page result fakeid=%s begin=%s total_count=%s articles=%s",
            fakeid,
            begin,
            int(page.get("total_count") or 0),
            len(articles),
        )
        return {
            "total_count": int(page.get("total_count") or 0),
            "articles": articles,
        }

    def fetch_public_article(self, link: str) -> str:
        LOGGER.debug("fetch_public_article link=%s", link)
        candidates: list[Session] = [self.new_session()]
        login_record = get_login_session(self.db)
        if login_record and login_record.get("cookies"):
            candidates.append(self.new_session(login_record["cookies"]))

        last_html = ""
        for session in candidates:
            headers = {
                "User-Agent": session.headers.get("User-Agent", DEFAULT_USER_AGENT),
                "Referer": session.headers.get("Referer", "https://mp.weixin.qq.com/"),
                "Origin": session.headers.get("Origin", "https://mp.weixin.qq.com"),
            }
            cookie_header = requests.utils.dict_from_cookiejar(session.cookies)
            if cookie_header:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_header.items())

            if self._is_article_gateway_enabled():
                html = self._fetch_via_article_gateway(link, headers)
            else:
                response = self.request(
                    session,
                    "GET",
                    link,
                    operation="article",
                    allow_redirects=True,
                )
                html = response.text
            if "id=\"js_content\"" in html or "id='js_content'" in html:
                LOGGER.debug("fetch_public_article success link=%s", link)
                return html
            last_html = html

        if "环境异常" in last_html or "verify" in last_html:
            LOGGER.warning("fetch_public_article blocked link=%s", link)
            raise WechatArticleAccessError("微信返回环境异常校验页，请配置代理后重试文章详情抓取")
        raise WechatArticleAccessError("未能抓取到有效文章正文")

    def download_binary(self, url: str, referer: str | None = None, operation: str = "article") -> bytes:
        session = self.new_session()
        if referer:
            session.headers["Referer"] = referer
        if url.startswith("//"):
            url = f"https:{url}"

        if operation == "article" and self._is_article_gateway_enabled():
            headers = {
                "User-Agent": session.headers.get("User-Agent", DEFAULT_USER_AGENT),
                "Referer": session.headers.get("Referer", referer or "https://mp.weixin.qq.com/"),
            }
            return self._download_via_article_gateway(url, headers)

        response = self.request(session, "GET", url, operation=operation, allow_redirects=True)
        return response.content

    def _respect_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_at = time.time()

    def _proxy_row(self) -> dict[str, Any]:
        return self.db.row("SELECT * FROM proxy_config WHERE name = 'default'") or {}

    def _is_article_gateway_enabled(self) -> bool:
        row = self._proxy_row()
        return bool(row.get("enabled") and row.get("proxy_url") and row.get("apply_article_fetch"))

    def _build_article_gateway_url(self, url: str, headers: dict[str, str] | None = None, include_headers: bool = False) -> str:
        row = self._proxy_row()
        proxy_url = str(row.get("proxy_url") or "").strip()
        if not proxy_url:
            raise WechatArticleAccessError("未配置文章详情抓取代理")
        if not urlparse(proxy_url).scheme:
            proxy_url = f"https://{proxy_url}"
        short_url = normalize_mp_article_short_url(url)
        separator = '&' if '?' in proxy_url else '?'
        gateway_url = f"{proxy_url}{separator}url={quote(short_url, safe=':/')}"
        if include_headers and headers:
            header_json = json.dumps(headers or {}, ensure_ascii=False)
            gateway_url += f"&headers={quote(header_json, safe='')}"
        return gateway_url

    def _fetch_via_article_gateway(self, url: str, headers: dict[str, str] | None = None) -> str:
        last_error: Exception | None = None
        for include_headers in (False, True):
            gateway_url = self._build_article_gateway_url(url, headers, include_headers=include_headers)
            try:
                response = requests.get(gateway_url, timeout=30, allow_redirects=True)
                response.raise_for_status()
                return response.text
            except RequestException as exc:
                last_error = exc
                LOGGER.warning("article gateway fetch failed include_headers=%s url=%s error=%s", include_headers, url, exc)
        raise WechatArticleAccessError(f"文章代理抓取失败: {last_error}")

    def _download_via_article_gateway(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        last_error: Exception | None = None
        for include_headers in (False, True):
            gateway_url = self._build_article_gateway_url(url, headers, include_headers=include_headers)
            try:
                response = requests.get(gateway_url, timeout=30, allow_redirects=True)
                response.raise_for_status()
                return response.content
            except RequestException as exc:
                last_error = exc
                LOGGER.warning("article gateway download failed include_headers=%s url=%s error=%s", include_headers, url, exc)
        raise WechatArticleAccessError(f"文章资源代理下载失败: {last_error}")

    def _resolve_proxies(self, operation: str) -> dict[str, str] | None:
        row = self.db.row("SELECT * FROM proxy_config WHERE name = 'default'")
        if not row or not row.get("enabled") or not row.get("proxy_url"):
            return None
        use_proxy = False
        if operation == "article" and row.get("apply_article_fetch"):
            use_proxy = True
        if operation == "sync" and row.get("apply_sync"):
            use_proxy = True
        if not use_proxy:
            return None
        proxy_url = str(row["proxy_url"]).strip()
        parsed = urlparse(proxy_url)
        if not parsed.scheme:
            proxy_url = f"http://{proxy_url}"
        return {"http": proxy_url, "https": proxy_url}
