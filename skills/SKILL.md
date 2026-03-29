---
name: wechat-article-assistant
description: 微信公众号文章同步与详情抓取助手。支持公众号登录、搜索与添加、同步策略配置、主题分类配置、文章详情抓取、24 小时汇总导出，以及按主题分组输出 Markdown 汇总。
---

# WeChat Article Assistant

这个 Skill 现在主要处理 6 类事情：
1. 登录微信公众号后台并保存登录态
2. 搜索 / 添加 / 删除公众号
3. 配置公众号同步策略
4. 配置公众号主题分类
5. 同步公众号文章并抓取详情
6. 导出 Markdown 汇总

## 当前支持的能力

### 1. 公众号可以配置同步策略

每个公众号都可以设置：
- `processing_mode=sync_only`
  只同步文章列表，不自动抓详情
- `processing_mode=sync_and_detail`
  同步文章列表后，自动抓取新增文章详情

还可以设置：
- `auto_export_markdown=true`
  表示该公众号会参与总汇总 Markdown 输出

示例：
```bash
python scripts/wechat_article_assistant.py set-account-config \
  --nickname "学习强国" \
  --processing-mode sync_and_detail \
  --auto-export-markdown true \
  --json
```

### 2. 公众号只设置一个主题分类

每个公众号只保留一个主题分类，避免后续汇总分组混乱。例如：
- `AI`
- `时政`
- `经济`
- `学习主题`
- `新闻主题`

示例：
```bash
python scripts/wechat_article_assistant.py set-account-config \
  --nickname "成都发布" \
  --categories "新闻主题" \
  --json
```

如果一次传入多个分类，当前实现会只保留第一个。

### 3. 汇总会优先按主题分组

合并汇总 Markdown 现在会：
- 只汇总 `auto_export_markdown=true` 的公众号
- 默认统计最近 24 小时文章
- 先按主题分类分组
- 同主题下再按公众号分组
- 最后按发布时间排序

也就是说，如果你给多个公众号设置成同一个主题，它们会优先排在一起。

### 4. 自动导出策略

当前自动行为是：
- 同步时如果公众号是 `sync_and_detail`
- 且该公众号开启了 `auto_export_markdown=true`
- 且本次确实抓到了新增文章详情

那么同步完成后会自动生成一份“最近 24 小时多公众号合并总汇总”。

注意：
- 自动同步时已经关闭“单公众号自动汇总”
- 现在默认只自动生成“总汇总”
- 单公众号汇总仍可手动导出

## 统一入口

```bash
python scripts/wechat_article_assistant.py --help
```

## 常用命令

### 查看公众号列表

```bash
python scripts/wechat_article_assistant.py list-accounts --json
```

### 设置公众号同步策略和主题

```bash
python scripts/wechat_article_assistant.py set-account-config \
  --fakeid "FAKEID" \
  --processing-mode sync_and_detail \
  --categories "学习主题" \
  --auto-export-markdown true \
  --json
```

### 同步单个公众号

```bash
python scripts/wechat_article_assistant.py sync --fakeid "FAKEID" --json
```

### 同步全部公众号

```bash
python scripts/wechat_article_assistant.py sync-all --interval-seconds 180 --json
```

### 手动导出最近 24 小时总汇总

```bash
python scripts/wechat_article_assistant.py export-recent-report \
  --hours 24 \
  --save true \
  --include-markdown false \
  --only-markdown-accounts true \
  --json
```

### 手动导出单公众号汇总

```bash
python scripts/wechat_article_assistant.py export-account-report \
  --fakeid "FAKEID" \
  --save true \
  --include-markdown false \
  --json
```

## 文件输出规则

为了避免中文和特殊字符出现在文件名里，当前导出规则是：
- 合并总汇总：`YYYYMMDD-HHMMSS_combined-report.md`
- 单公众号汇总：`YYYYMMDD-HHMMSS_account-report_<fakeid>.md`
- 单篇文章详情：`article_<aid>.md`

## 登录与排障

### 检查登录状态

```bash
python scripts/wechat_article_assistant.py login-info --validate true --json
```

### 查看代理配置

```bash
python scripts/wechat_article_assistant.py proxy-show --json
```

### 环境检查

```bash
python scripts/wechat_article_assistant.py env-check --json
python scripts/wechat_article_assistant.py doctor --json
```

## 参考资料

需要更细的说明时再看：
- `references/operations.md`
- `references/interface-reference.md`
- `references/sqlite-schema.md`
- `references/account-classification.md`
