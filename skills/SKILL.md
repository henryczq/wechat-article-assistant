---
name: wechat-article-assistant
description: 微信公众号文章助手。通过本地 Python 脚本直接完成微信公众号登录、登录态保存、代理配置、公众号搜索与管理、文章同步、文章清单查询、文章详情抓取与导出，不依赖单独部署的 Web 服务。用于 OpenClaw/Trae 中需要统一以 Skill 智能体方式管理公众号文章的场景，尤其适合需要通过 Inbound Context 发送登录二维码、用 SQLite 持久化数据、通过 OpenClaw cron 调用同步脚本的工作流。
---

# WeChat Article Assistant

## 什么时候使用这个 Skill

当用户需要以下能力时使用：

- 登录微信公众号后台并保存登录态
- 搜索、添加、删除公众号
- 同步公众号最新文章到本地 SQLite
- 查询公众号远端文章列表
- 抓取单篇公众号文章正文、图片、Markdown、JSON
- 配置 OpenClaw 定时任务，定期同步全部公众号

---

## 核心原则

### 1. 主入口

统一使用：

```bash
python scripts/wechat_article_assistant.py --help
```

### 2. 登录优先用一体化方式

优先使用：

```bash
python scripts/wechat_article_assistant.py login-start --wait true ...
```

也就是：
- 生成二维码
- 发到当前会话
- 后端继续等待登录
- 登录成功后自动通知

不要优先设计成“用户扫完码后再手动回来回报已登录”。

### 2.1 登录时必须传递 channel / target / account

**登录二维码要发回当前会话时，必须从 Inbound Context 读取 `channel`、`target` 和 `account`（即 `account_id`）。不要省略，不要擅自“优化掉”。**

如果缺少这些参数，常见后果是：
- 收不到二维码
- 二维码发错会话
- 登录成功通知发不回来

#### 步骤1：读取 Inbound Context

Inbound Context 典型格式：

```json
{
  "schema": "openclaw.inbound_meta.v1",
  "chat_id": "telegram:5747692163",
  "account_id": "8606699467",
  "channel": "telegram"
}
```

#### 提取参数

| 参数 | 来源字段 | 示例值 | 说明 |
|------|---------|--------|------|
| `channel` | `channel` | `telegram` | 消息渠道 |
| `target` | `chat_id` | `telegram:5747692163` | 目标会话/用户ID |
| `account` | `account_id` | `8606699467` | 消息账号ID |

#### 步骤2：执行登录脚本

```bash
python scripts/wechat_article_assistant.py login-start \
  --channel "${channel}" \
  --target "${target}" \
  --account "${account}" \
  --wait true \
  --json
```

#### 强规则

- **不要省略 `channel`**
- **不要省略 `target`**
- **只要 Inbound Context 里有 `account_id`，就应传 `--account`**
- **以后不要把这一步当成“可选优化项”删掉**
- 如果没有正确读取 Inbound Context，就不要假设二维码一定能送达

### 3. 文章详情代理和同步代理是两回事

- `apply_article_fetch`：用于抓取单篇文章正文
- `apply_sync`：用于同步公众号文章列表

不要默认把两者混为一谈。

### 4. 文章详情代理优先按“网关模式”理解

如果用户提供的是类似下面的地址：

```text
https://wechat.zzgzai.online
```

优先把它当成**文章抓取网关**，而不是标准 HTTP CONNECT 代理。

文章详情抓取应优先走：

```text
proxy_url?url=<文章短链接>
```

必要时再回退尝试：

```text
proxy_url?url=<文章短链接>&headers=<json>
```

### 5. 文章详情统一优先走短链接

`article-detail` 抓取时，优先把文章链接归一化为：

```text
https://mp.weixin.qq.com/s/...
```

不要优先依赖带大量 query 参数的长链接。

### 6. 定时任务优先方案 B

如果用户希望每天固定时间自动同步全部公众号，优先使用：

```bash
bash ${HOME}/.openclaw/workspace/skills/wechat-article-assistant/scripts/run_sync_all.sh
```

再配合 OpenClaw cron 调度，而不是让 agent 每次临时拼接 Python 命令。

### 7. 批量同步注意频控

同步多个公众号时，建议显式设置间隔，例如：

```bash
python scripts/wechat_article_assistant.py sync-all --interval-seconds 180 --json
```

当前固定脚本也默认采用 180 秒间隔，降低频控风险。

### 8. 先检查 Skill 环境再排障

当用户反馈“脚本报错”“命令跑不起来”“依赖可能没装”“二维码发不出来”“文章抓取失败”时，优先先做一次环境检查，不要直接假设是业务逻辑问题。

### 9. 排障默认只读，不擅自改文件

当用户的意图是：
- 检查
- 排查
- 看报错
- 分析原因
- 解释为什么失败

默认执行**只读诊断**，也就是：
- 读取文件
- 检查环境
- 运行只读诊断命令
- 输出报错信息、原因分析、修复建议

**不要自动执行以下动作：**
- 修改代码
- 新增文件
- 删除文件
- 改配置
- 安装依赖
- 替用户“顺手修复”问题

只有当用户明确表达以下意图时，才允许进入写操作：
- 修复
- 修改
- 帮我改
- 新增
- 直接处理
- 直接帮我装

**例外白名单：**
- `env-check` 可以自动创建缺失的基础运行路径，例如：
  - 二维码目录
  - 日志目录
  - 数据目录
  - 数据库文件

这类操作属于环境自检自愈，默认允许；但除这些基础路径外，不要因为排障而自动改业务代码或业务配置。

建议检查以下几类依赖：

在文档层面，也应明确把这些依赖写进：
- `requirements.txt`
- `README.md`
- `SKILL.md`

避免出现“脚本 import 了，但安装说明没写”的情况。

1. **Python 依赖与运行环境**
   - 读取 `requirements.txt`
   - 当前至少依赖：
     - `beautifulsoup4`
     - `requests`
     - `markdownify`
   - 另外不要只信 `requirements.txt`，还要**扫描脚本里的 import**，确认运行期第三方依赖是否真的都能导入
   - 同时检查 `python` / `python3` 命令是否真的可用，而不是被系统拦截
   - **Windows 特别注意**：Windows 10/11 可能启用了 Python 的“应用执行别名（App execution aliases）”，导致输入 `python` 或 `python3` 时跳转到 Microsoft Store，而不是真正执行本机 Python

     如果用户在 Windows 上遇到“输入 python 后打开微软商店”的情况，优先提示用户：
     1. 打开开始菜单，搜索 **应用执行别名**（英文系统：**App execution aliases**）
     2. 进入“管理应用执行别名”
     3. 找到：
        - `python.exe`
        - `python3.exe`
     4. 将这两个开关关闭

     关闭后：
     - 如果 `python` / `python3` 可以正常执行，说明问题解决
     - 如果提示“找不到命令”，说明机器上还没有正确安装或配置 Python PATH

2. **Skill 脚本是否齐全**
   - 重点检查：
     - `scripts/wechat_article_assistant.py`
     - `scripts/cli.py`
     - `scripts/login_service.py`
     - `scripts/article_service.py`
     - `scripts/sync_service.py`
     - `scripts/openclaw_messaging.py`
     - `scripts/run_sync_all.sh`

3. **OpenClaw 侧运行依赖**
   - `openclaw` 命令是否可调用（二维码/消息发送依赖它）
   - 当前工作目录是否正确
   - 媒体目录是否可写（例如 `~/.openclaw/media/wechat-article-assistant/`）

4. **登录与网络条件**
   - 是否已有登录态
   - 抓文章详情时是否需要代理
   - 代理配置是否已启用，并区分：
     - `apply_article_fetch`
     - `apply_sync`

### 环境检查推荐命令

优先执行：

```bash
python scripts/wechat_article_assistant.py env-check --json
python scripts/wechat_article_assistant.py doctor --json
python scripts/wechat_article_assistant.py login-info --validate true --json
python scripts/wechat_article_assistant.py proxy-show --json
```

必要时补充：

```bash
python -m pip show beautifulsoup4 requests markdownify
python -m pip install -r requirements.txt
bash scripts/run_sync_all.sh --help
```

如果用户在 Windows 上报 `ModuleNotFoundError`，优先建议使用：

```bash
python -m pip install -r requirements.txt
```

而不是只说“运行 pip install”，避免 `pip` 和当前 `python` 指向不同解释器。

或检查关键文件是否存在：

```bash
ls -la scripts/
ls -la requirements.txt
```

### 新增命令说明

```bash
python scripts/wechat_article_assistant.py env-check --json
```

用于检查：
- `python` / `python3` 是否可用
- Python 依赖包是否安装
- 每个依赖都会显示：`installed / version / import_name / package_name`
- 脚本 import 扫描出的第三方依赖是否都能导入
- 关键脚本文件是否存在
- `openclaw` 命令是否可用
- Skill 数据目录 / 媒体目录 / 二维码目录是否存在
- 如果二维码目录不存在，会自动创建
- 如果数据目录或数据库文件不存在，会自动创建

```bash
python scripts/wechat_article_assistant.py doctor --json
```

现在除了检查登录与代理状态，还会顺带附带 `env-check` 结果，适合一条命令看全局状态。

### 处理原则

- 如果是**依赖缺失**，先补依赖，再重试业务命令
- 如果是**旧脚本名引用**，统一改为：
  - `scripts/wechat_article_assistant.py`
- 如果是**路径错误**，优先核对当前 skill 目录、媒体目录、cron 任务路径
- 如果是**详情抓取被微信风控**，优先检查代理，不要误判成脚本损坏

---

## 最短使用路径

### 1. 登录

```bash
python scripts/wechat_article_assistant.py login-start \
  --channel feishu \
  --target user:YOUR_OPEN_ID \
  --account default \
  --wait true \
  --json
```

### 2. 添加公众号

```bash
python scripts/wechat_article_assistant.py add-account-by-keyword "成都发布" --json
```

### 3. 拉文章列表

```bash
python scripts/wechat_article_assistant.py list-account-articles \
  --fakeid "MzA4MTg1NzYyNQ==" \
  --remote true \
  --count 10 \
  --json
```

### 4. 抓文章详情

```bash
python scripts/wechat_article_assistant.py article-detail \
  --link "https://mp.weixin.qq.com/s/xxxxxxxx" \
  --json
```

### 5. 同步全部公众号

```bash
python scripts/wechat_article_assistant.py sync-all --interval-seconds 180 --json
```

---

## OpenClaw 定时任务建议

如果用户要新建 OpenClaw 内置定时任务：

- 优先使用 `run_sync_all.sh` 作为固定入口
- 推荐使用 `openclaw cron add`
- 推荐参数：
  - `--session isolated`
  - `--announce`
  - `--tz "Asia/Shanghai"`
  - 如果要求整点精确执行，加 `--exact`

适用场景：
- 每天下午固定时间同步全部公众号
- 长期稳定运行的后台任务
- 需要自动把同步结果回传到当前聊天

---

## 代理测试建议

如果用户给的是“文章抓取网关代理”，统一优先这样测试：

```text
代理地址/?url=https://www.baidu.com/
```

例如：

```text
https://wechat.zzgzai.online/?url=https://www.baidu.com/
```

不要一开始就用标准代理健康检查方式判断它是否可用。

---

## 相关文档

更详细的使用说明、接口参数和设计细节见：

- 面向用户使用：`README.md`
- 接口文档：`references/interface-reference.md`
- 设计说明：`references/design.md`
- 评审记录：`references/review-notes-2026-03-22.md`

如果只是为了“会用”，先看 `README.md`。
如果是为了“扩展或排障”，再看 `references/`。