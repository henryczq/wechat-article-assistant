# WeChat Article Assistant - Test Status (2026-03-22)

## 目标

记录本轮对 `wechat-article-assistant` 的实际测试情况，区分：

- 已实测通过
- 已修改但未充分测试
- 后续建议补测

---

## 一、已实测通过

### 1. 登录主链路

已验证：

- `login-start`
- 发送二维码到当前飞书会话
- `login-wait`
- 登录成功后保存登录态
- 登录成功后通知当前会话
- 一体化登录：`login-start --wait true`

结论：

- 登录主链路通过
- 自动通知链路通过

---

### 2. 公众号搜索与添加

已验证：

- `add-account-by-keyword "学习强国"`
- `add-account-by-keyword "成都发布"`
- `list-accounts`

结论：

- 搜号 / 加号 / 列表功能通过

---

### 3. 公众号删除

已验证：

- `delete-account --nickname "学习强国"`

结论：

- 删除公众号及其本地数据功能通过
- 事务改造后的删除链路已实测

---

### 4. 远端文章列表

已验证：

- `list-account-articles --remote true`
- 成功拉取“成都发布”最新第一页文章
- 成功拉取“学习强国”最新第一页文章

结论：

- 远端文章列表查询通过

---

### 5. 单篇文章详情抓取

已验证：

- `article-detail --link ...`
- Markdown 导出成功
- JSON 导出成功
- 图片下载成功
- 本地文件落地成功

重点验证：

- 旧项目兼容代理模式生效
- article-detail 统一优先走短链接
- 先试 `proxy_url?url=<短链接>`，必要时再回退到 `&headers=`

已实际抓取成功的示例：

- 成都发布：《微信可以用“龙虾”了！》
- 学习强国：《答应我，胖哪都千万不要胖这里！！！（不是肚子）》
- 成都发布短链接代理样例文章

结论：

- 文章详情主链路通过
- 文章网关代理模式通过

---

### 6. 单公众号同步

已验证：

- `sync --fakeid ...`
- 成都发布同步成功
- 学习强国同步成功（新增 5 篇）

结论：

- 单公众号同步通过

---

### 7. OpenClaw 定时任务（方案 B）

已验证：

- 固定脚本入口：`scripts/run_sync_all.sh`
- OpenClaw cron job 创建成功
- 手动触发 cron 成功
- 至少一次 run 状态显示：
  - `lastRunStatus = ok`
  - `lastDelivered = true`

结论：

- 方案 B 可用
- cron + 固定脚本 + announce 回传链路通过

---

## 二、已修改但未充分测试

### 1. `login-import`

状态：
- 代码保留
- 未使用真实旧 cookie/token 文件完整验证

### 2. `login-poll`

状态：
- 与 `login-wait` 共用部分链路
- 未单独做一轮完整测试

### 3. `login-clear`

状态：
- 未专门测试“清空后重新登录”闭环

### 4. `resolve-account-url`

状态：
- 功能存在
- 未做完整成功/失败场景验证

### 5. `add-account-by-url`

状态：
- 功能存在
- 未完整实测

### 6. `set-sync-target` / `list-sync-targets`

状态：
- 功能存在
- 未专门测试同步时间配置更新

### 7. `sync-due`

状态：
- 已改成支持 `--grace-minutes`
- 未完整验证补跑、防重、跨分钟行为

### 8. `sync-logs`

状态：
- 日志应已在写入
- 未专门用 CLI 做结果核查

### 9. `article-detail --include-html true`

状态：
- HTML 保存逻辑在
- 本轮主要测试 Markdown / JSON / 图片

### 10. `article-detail` 缓存命中回归

状态：
- 已修复缓存命中与首次抓取返回结构不一致问题
- 但未专门做“同一链接抓两次”的回归验证

### 11. `doctor` 对网关代理的测试语义

状态：
- 文档已补充说明
- 但工具输出仍偏向标准代理健康检查语义

---

## 三、已知行为与结论

### 1. 文章详情代理 ≠ 同步代理

已确认：

- `wechat.zzgzai.online` / `wechat2.zzgzai.online` 这类地址更适合文章详情抓取
- 不适合作为 `sync` 链路的标准 CONNECT 代理

因此当前推荐配置为：

- `apply_article_fetch = true`
- `apply_sync = false`

### 2. 批量同步存在频控风险

已确认：

- 多个公众号连续同步时，可能遇到 `freq control`

当前解决方案：

- `sync-all` 已支持 `--interval-seconds`
- 固定脚本 `run_sync_all.sh` 默认使用 `180` 秒间隔

---

## 四、建议后续补测顺序

推荐优先补测：

1. `article-detail` 缓存命中回归
2. `sync-logs`
3. `sync-due`
4. `login-import`
5. `login-clear`
6. `add-account-by-url`
7. `resolve-account-url`
8. `--include-html true`

---

## 五、当前总体判断

当前 Skill 已经进入“可用状态”。

主链路（登录 / 搜号 / 加号 / 列表 / 详情 / 同步 / 定时任务）已经基本打通。

未充分测试的部分主要集中在：

- 管理类辅助功能
- 回归验证
- 个别边界场景
- 长期稳定性观察
