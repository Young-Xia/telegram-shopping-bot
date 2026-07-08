# Telegram Shopping Bot

[English](#english) · [中文](#中文)

A private Telegram bot that saves shopping items to Notion, with AI extraction and a **CustomTkinter GUI** for setup, start/stop, and logs.

**Repository:** https://github.com/Young-Xia/telegram-shopping-bot

---

## English

### Features

- **Save to Notion** — title, URL, category, status, notes, images, and timestamp
- **Forward flow** — forward text, links, or photos → **Search** (learn more) or **Add item** (save to list)
- **Link reading** — fetches page title, price, and body text, then AI extracts product fields
- **Photo recognition** — vision model identifies products; photos are uploaded to a Notion **Files** column
- **Smart update** — if the link matches or the title is very similar, updates the existing row instead of duplicating
- **General AI search** — `/search` or forward → Search (not written to Notion)
- **Mixed AI providers** — any OpenAI-compatible chat API (DeepSeek, OpenRouter, OpenAI, …) plus optional separate vision API
- **GUI control panel** — configure `.env`, start/stop/restart, logs, light/dark theme
- **Message acknowledgment** — reacts with 👀 when your message is received

#### Recent updates (2026‑07‑08)

- **Mixed image+text routing** — when a message has both photo and caption, the bot decides whether to focus on the image, the text, or both based on your question (e.g. “翻译图片里的文字” vs “总结这段文字”).
- **Markdown-free answers** — AI outputs are normalized to plain text (no `**bold**`, `` `code` ``, or `[]()` links) while keeping emoji and bullet lists.
- **More robust vision pipeline** — retries Telegram photo downloads and falls back cleanly to text-only answers when vision is unavailable.
- **OpenRouter compatibility** — adds a diagnostic script and safer error messages when privacy / data-policy settings block providers; supports `qwen/qwen3-vl-32b-instruct` as an alternative vision model when OpenAI/Google vision are restricted.

### Requirements

- Python **3.11+**
- Windows recommended for the GUI scripts (the bot itself runs on any OS with Python)
- Accounts / keys:
  - **Telegram Bot** ([@BotFather](https://t.me/BotFather))
  - **AI API** — OpenAI-compatible Chat Completions (OpenRouter / OpenAI / DeepSeek / …)
  - **Vision API** — only if the chat API cannot see images (e.g. DeepSeek chat + OpenRouter vision)
  - **Notion** integration + database

### Quick Start

**1. Clone and install**

```powershell
git clone https://github.com/Young-Xia/telegram-shopping-bot.git
cd telegram-shopping-bot
.\bootstrap-gui.cmd
```

**2. Configure (GUI recommended)**

1. Double-click `打开控制面板.bat` or run `start-gui.vbs`
2. Open **Setup** and fill in:
   - Telegram Bot Token
   - Allowed Telegram user IDs (optional; empty = anyone)
   - Notion Integration Token (`ntn_…` or `secret_…`) and Database ID
   - AI API base URL + key + default model
   - Vision API fields if the chat provider has no vision (common: DeepSeek chat + OpenRouter vision)
3. Click **Save**, then **Test connection**

Or copy and edit manually:

```powershell
copy .env.example .env
# Edit .env — see Environment Variables below
```

Notion database setup: [NOTION-SETUP.md](./NOTION-SETUP.md).

**3. Run**

- GUI: **Control** → **Start** (use **Stop** / **Restart** from the same panel)
- CLI:

```powershell
.\start-bot-background.cmd
```

> **Note:** One Telegram bot token can only run in one process. If the panel shows a stale process or startup sticks, close the panel, run `stop-bot.cmd`, delete `logs\bot.pid` if it remains, then open the panel again.

### Environment Variables

Primary names (preferred). Legacy `OPENROUTER_*` keys still work.

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) |
| `ALLOWED_TELEGRAM_USER_IDS` | No | Comma-separated user IDs; empty = no restriction |
| `AI_API_BASE_URL` | No | OpenAI-compatible base URL (default OpenRouter) |
| `AI_API_KEY` | Yes* | Chat API key (`OPENROUTER_API_KEY` also accepted) |
| `AI_DEFAULT_MODEL` | No | Default chat model (auto-inferred from base URL if empty) |
| `AI_MODELS` | No | Comma-separated models for `/model` |
| `AI_VISION_API_BASE_URL` | No | Separate vision API when chat has no vision |
| `AI_VISION_API_KEY` | No | Vision API key |
| `AI_VISION_MODEL` | No | Vision model (default `google/gemini-2.5-flash` on OpenRouter) |
| `NOTION_TOKEN` | Yes | Integration secret (`ntn_…` or `secret_…`) |
| `NOTION_DATABASE_ID` | Yes | Database ID (32 hex chars) |
| `SEARCH_PROVIDER` | No | `duckduckgo` (default) or `google` |
| `GOOGLE_CSE_API_KEY` / `GOOGLE_CSE_ID` | No | Only if `SEARCH_PROVIDER=google` |

\*Required unless you only use the legacy `OPENROUTER_API_KEY` name.

**Notion property names** (optional; defaults match a Chinese database):

| Variable | Default | Notion type |
|----------|---------|-------------|
| `NOTION_TITLE_PROPERTY` | `名称` | Title |
| `NOTION_URL_PROPERTY` | `链接` | URL |
| `NOTION_CATEGORY_PROPERTY` | `分类` | Select |
| `NOTION_STATUS_PROPERTY` | `状态` | Status / Select |
| `NOTION_DEFAULT_STATUS` | `未开始` | option name |
| `NOTION_NOTES_PROPERTY` | `备注` | Rich text |
| `NOTION_IMAGES_PROPERTY` | `图片` | Files & media |
| `NOTION_ADDED_AT_PROPERTY` | `Added At` | Date |

Missing URL / notes / category / images columns are created automatically when possible. The title column must already exist.

**Example: DeepSeek chat + OpenRouter vision**

```env
AI_API_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=sk-...
AI_DEFAULT_MODEL=deepseek-chat
AI_VISION_API_BASE_URL=https://openrouter.ai/api/v1
AI_VISION_API_KEY=sk-or-v1-...
AI_VISION_MODEL=google/gemini-2.5-flash
```

See [`.env.example`](./.env.example) for a full template.

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome / how to use |
| `/help` | Longer help |
| `/save` | Reply to a message, then extract and save the product |
| `/search <query>` | General AI search (not saved to Notion) |
| `/ask <question>` | Ask AI (or reply to a message with `/ask`) |
| `/add <url>` or `/add <name> <url>` | Add by link |
| `/model [name]` | List or switch chat model |
| `/clear` | Clear AI chat history and unfinished add flow |
| `/cancel` | Cancel current add flow |

### Shopping Workflows

**Forward a message**

1. Forward text, a link, or a photo
2. Bot reacts with 👀, reads links when present, shows a preview
3. **Search** — general Q&A about the content (no Cancel button on the result)
4. **Add item** — AI extracts fields → pick category → save (or update a similar existing row)

**Paste a link**

Send a product URL (optionally with a short description) → page is fetched → AI extracts → pick category → save

**Reply + `/save`**

Reply to a message that contains product info, send `/save` → extract → pick category → save

### Project Structure

```
telegram-shopping-bot/
├── src/shopping_bot/
│   ├── bot.py              # Telegram handlers
│   ├── config.py           # Settings loader
│   ├── text_format.py      # Clean AI markdown for Telegram
│   ├── gui/                # Control panel
│   └── services/           # Notion, AI, search, vision, product extract
├── scripts/check_setup.py  # Connection tests
├── bootstrap-gui.cmd       # First-time install
├── 打开控制面板.bat / start-gui.vbs
├── start-bot-background.cmd / stop-bot.cmd
├── .env.example
└── NOTION-SETUP.md
```

### Development

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
python -m shopping_bot.bot          # bot only
python -m shopping_bot.gui          # GUI
python scripts/check_setup.py       # test connections
python scripts/check_setup.py --write-test   # optional Notion write test
```

### License

Personal project — use and modify freely. Do **not** commit `.env` or API keys.

---

## 中文

### 功能

- **保存到 Notion** — 名称、链接、分类、状态、备注、图片、添加时间
- **转发流程** — 转发文字、链接或图片 → **搜索**（了解内容）或 **添加商品**（写入清单）
- **读取链接** — 抓取页面标题、价格、正文，再用 AI 提取商品字段
- **照片识别** — 视觉模型识别商品；图片上传到 Notion **文件**列
- **智能更新** — 链接相同或标题很相似时，更新已有条目而不是重复添加
- **AI 通用搜索** — `/search` 或转发后点搜索（不写入 Notion）
- **混合 AI 供应商** — 任意 OpenAI 兼容对话接口，并可单独配置视觉 API
- **GUI 控制面板** — 配置 `.env`、启停/重启、日志、浅色/深色主题
- **消息确认** — 收到消息时用 👀 回应

#### 本次更新（2026‑07‑08）

- **图文混合路由**：转发里同时有图片和文字时，根据你的提问自动判断重点看图还是看文字（例如 “翻译图片里的文字” / “总结这段文字”）。
- **去掉 markdown**：AI 回复统一清理为纯文本，不再出现 `**加粗**`、`` `代码` ``、`[链接](...)` 等 markdown 语法，保留表情和项目符号。
- **识图链路更稳**：Telegram 下载图片支持重试，视觉模型不可用时会优雅降级为“只根据文字回答”，避免直接报错。
- **OpenRouter 兼容性**：加入诊断脚本和更清晰的错误提示，当隐私 / 数据策略导致所有提供商被禁用时能直接指向 `openrouter.ai/settings/privacy`；在 OpenAI / Google 视觉被策略限制时，可改用 `qwen/qwen3-vl-32b-instruct` 作为视觉模型。

### 环境要求

- Python **3.11+**
- Windows（控制面板脚本面向 Windows；机器人本体可在任意 Python 环境运行）
- 需要：
  - **Telegram Bot**（[@BotFather](https://t.me/BotFather)）
  - **AI API**（OpenAI 兼容：OpenRouter / OpenAI / DeepSeek 等）
  - **视觉 API**（仅当对话 API 不支持图片时，例如 DeepSeek 对话 + OpenRouter 识图）
  - **Notion** Integration 与数据库

### 快速开始

**1. 克隆并安装**

```powershell
git clone https://github.com/Young-Xia/telegram-shopping-bot.git
cd telegram-shopping-bot
.\bootstrap-gui.cmd
```

**2. 配置（推荐控制面板）**

1. 双击 `打开控制面板.bat`，或运行 `start-gui.vbs`
2. 进入 **初始设置**，填写：
   - Telegram Bot Token
   - 允许使用的用户 ID（可选；留空表示不限制）
   - Notion Integration Token（`ntn_…` 或 `secret_…`）和数据库 ID
   - AI API 地址、Key、默认对话模型
   - 若对话 API 不能识图，再填视觉 API 地址 / Key / 模型
3. 点 **保存配置**，再点 **测试连接**

或手动配置：

```powershell
copy .env.example .env
# 编辑 .env，见下方环境变量
```

Notion 数据库详细步骤见 [NOTION-SETUP.md](./NOTION-SETUP.md)。

**3. 运行**

- 控制面板：**运行控制** → **启动**（同一面板可 **停止** / **重启**）
- 命令行：

```powershell
.\start-bot-background.cmd
```

> **注意：** 同一个 Telegram Bot Token 只能有一个进程在跑。若面板显示旧进程或启动卡住：关闭面板 → 运行 `stop-bot.cmd` → 如仍有 `logs\bot.pid` 则删除 → 再打开面板。

### 环境变量

优先使用下列名称；旧的 `OPENROUTER_*` 仍兼容。

| 变量 | 必填 | 说明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | 是 | 从 [@BotFather](https://t.me/BotFather) 获取 |
| `ALLOWED_TELEGRAM_USER_IDS` | 否 | 逗号分隔用户 ID；留空不限制 |
| `AI_API_BASE_URL` | 否 | OpenAI 兼容接口地址（默认 OpenRouter） |
| `AI_API_KEY` | 是* | 对话 API Key（也可用 `OPENROUTER_API_KEY`） |
| `AI_DEFAULT_MODEL` | 否 | 默认对话模型（留空则按 API 地址推断） |
| `AI_MODELS` | 否 | 供 `/model` 切换的模型列表 |
| `AI_VISION_API_BASE_URL` | 否 | 对话 API 不支持图片时单独配置 |
| `AI_VISION_API_KEY` | 否 | 视觉 API Key |
| `AI_VISION_MODEL` | 否 | 视觉模型（OpenRouter 默认 `google/gemini-2.5-flash`） |
| `NOTION_TOKEN` | 是 | Integration Secret（`ntn_…` 或 `secret_…`） |
| `NOTION_DATABASE_ID` | 是 | 数据库 ID（32 位） |
| `SEARCH_PROVIDER` | 否 | `duckduckgo`（默认）或 `google` |
| `GOOGLE_CSE_API_KEY` / `GOOGLE_CSE_ID` | 否 | 仅 `SEARCH_PROVIDER=google` 时需要 |

\*若使用旧变量名 `OPENROUTER_API_KEY`，可不写 `AI_API_KEY`。

**Notion 列名**（可选；默认按中文数据库）：

| 变量 | 默认 | Notion 类型 |
|------|------|-------------|
| `NOTION_TITLE_PROPERTY` | `名称` | 标题 |
| `NOTION_URL_PROPERTY` | `链接` | URL |
| `NOTION_CATEGORY_PROPERTY` | `分类` | 选择 |
| `NOTION_STATUS_PROPERTY` | `状态` | 状态 / 选择 |
| `NOTION_DEFAULT_STATUS` | `未开始` | 选项名 |
| `NOTION_NOTES_PROPERTY` | `备注` | 文本 |
| `NOTION_IMAGES_PROPERTY` | `图片` | 文件 |
| `NOTION_ADDED_AT_PROPERTY` | `Added At` | 日期 |

缺少链接 / 备注 / 分类 / 图片列时，保存时会尽量自动创建；标题列必须事先存在。

**示例：DeepSeek 对话 + OpenRouter 识图**

```env
AI_API_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=sk-...
AI_DEFAULT_MODEL=deepseek-chat
AI_VISION_API_BASE_URL=https://openrouter.ai/api/v1
AI_VISION_API_KEY=sk-or-v1-...
AI_VISION_MODEL=google/gemini-2.5-flash
```

完整模板见 [`.env.example`](./.env.example)。

### 机器人命令

| 命令 | 说明 |
|------|------|
| `/start` | 欢迎与用法 |
| `/help` | 详细说明 |
| `/save` | 回复一条消息后提取并保存商品 |
| `/search <问题>` | AI 通用搜索（不写入清单） |
| `/ask <问题>` | 向 AI 提问（可先回复消息再 `/ask`） |
| `/add <链接>` 或 `/add <名称> <链接>` | 通过链接添加 |
| `/model [模型名]` | 查看或切换对话模型 |
| `/clear` | 清除对话记录和未完成添加流程 |
| `/cancel` | 取消当前添加流程 |

### 购物流程

**转发消息**

1. 转发文字、链接或图片
2. 机器人回复 👀；有链接时会先读取页面
3. **搜索** — 了解内容（结果页不再显示取消）
4. **添加商品** — AI 提取字段 → 选分类 → 保存（相似条目会更新）

**粘贴链接**

直接发送商品链接（可带简短描述）→ 读取页面 → AI 提取 → 选分类 → 保存

**回复 + `/save`**

回复包含商品信息的消息，发送 `/save` → 提取 → 选分类 → 保存

### 项目结构

```
telegram-shopping-bot/
├── src/shopping_bot/
│   ├── bot.py              # Telegram 主逻辑
│   ├── config.py           # 配置加载
│   ├── text_format.py      # AI 输出清理（去 markdown）
│   ├── gui/                # 控制面板
│   └── services/           # Notion、AI、搜索、视觉、商品提取
├── scripts/check_setup.py  # 连接测试
├── bootstrap-gui.cmd       # 首次安装
├── 打开控制面板.bat / start-gui.vbs
├── start-bot-background.cmd / stop-bot.cmd
├── .env.example
└── NOTION-SETUP.md
```

### 开发

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
python -m shopping_bot.bot          # 仅机器人
python -m shopping_bot.gui          # 控制面板
python scripts/check_setup.py       # 测试连接
python scripts/check_setup.py --write-test   # 可选：写一条测试行到 Notion
```

### 许可

个人项目，可自由使用和修改。请勿提交 `.env` 或 API 密钥。
