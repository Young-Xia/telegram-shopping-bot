# Telegram Shopping Bot

[English](#english) · [中文](#中文)

A private Telegram bot that saves shopping items to Notion, powered by OpenRouter AI. Includes a **CustomTkinter GUI** for setup, start/stop, and logs.

**Repository:** https://github.com/Young-Xia/telegram-shopping-bot

---

## English

### Features

- **Save to Notion** — title, URL, category, status, notes, and timestamp
- **Forward flow** — forward text, links, or photos → choose **Search / Add / Cancel**
- **Photo recognition** — vision model identifies products from forwarded images
- **AI product extraction** — reads reply chains and link previews to infer product name and category
- **General AI search** — `/search` for Q&A unrelated to shopping (not saved to Notion)
- **Model switching** — `/model` to switch OpenRouter models
- **GUI control panel** — configure `.env`, start/stop/restart bot, view logs, light/dark theme
- **Message acknowledgment** — reacts with 👀 when your message is received

### Requirements

- Python **3.11+**
- Windows (GUI scripts are Windows-oriented; the bot itself runs on any OS with Python)
- Accounts / keys: **Telegram Bot**, **OpenRouter**, **Notion**

### Quick Start

**1. Clone and install**

```powershell
git clone https://github.com/Young-Xia/telegram-shopping-bot.git
cd telegram-shopping-bot
.\bootstrap-gui.cmd
```

**2. Configure**

- Open the GUI: double-click `打开控制面板.bat` or run `start-gui.vbs`
- Go to **Setup**, fill in API keys, click **Save**
- Click **Test connection** to verify Telegram / OpenRouter / Notion

Or copy and edit manually:

```powershell
copy .env.example .env
# Edit .env with your credentials
```

**3. Run**

- From the GUI: **Control** → **Start**
- Or from the command line:

```powershell
.\start-bot-background.cmd
```

> **Note:** The same Telegram Bot Token cannot run in two apps at once. Stop other instances before starting.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) |
| `ALLOWED_TELEGRAM_USER_IDS` | No | Comma-separated user IDs; empty = no restriction |
| `OPENROUTER_API_KEY` | Yes | From [OpenRouter](https://openrouter.ai) |
| `OPENROUTER_DEFAULT_MODEL` | No | Default chat model (default: `openrouter/free`) |
| `OPENROUTER_VISION_MODEL` | No | Vision model for photos (default: `google/gemini-2.5-flash`) |
| `OPENROUTER_MODELS` | No | Comma-separated models for `/model` |
| `NOTION_TOKEN` | Yes | Notion integration secret |
| `NOTION_DATABASE_ID` | Yes | 32-character database ID |
| `SEARCH_PROVIDER` | No | `duckduckgo` (default) or `google` |
| `GOOGLE_CSE_API_KEY` / `GOOGLE_CSE_ID` | No | Only if `SEARCH_PROVIDER=google` |

Notion database properties (names configurable via `NOTION_*_PROPERTY`):

| Property | Type |
|----------|------|
| Name | Title |
| URL | URL |
| Category | Select |
| Status | Status |
| Notes | Text |
| Added At | Date |

See [NOTION-SETUP.md](./NOTION-SETUP.md) for detailed Notion setup.

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Command list |
| `/save` | AI-extract product from a reply chain and save |
| `/search <query>` | General AI search (not saved to Notion) |
| `/ask <question>` | Ask AI (can reply to a message with `/ask`) |
| `/add <name> <url>` | Add item by link |
| `/model [name]` | View or switch AI model |
| `/clear` | Clear AI conversation context |
| `/cancel` | Cancel current shopping flow |

### Shopping Workflows

**Forward a message**

1. Forward text, a link, or a photo to the bot
2. Bot reacts with 👀 and shows a preview
3. Tap **Search**, **Add to list**, or **Cancel**

**Reply chain**

1. Reply to a message containing product info
2. Send `/save`
3. AI extracts product details → pick a Notion category → saved

**Quick paste**

Send `description + product URL` directly → choose category → saved

### Project Structure

```
telegram-shopping-bot/
├── src/shopping_bot/
│   ├── bot.py              # Telegram bot handlers
│   ├── config.py           # Settings loader
│   ├── gui/                # CustomTkinter control panel
│   └── services/           # Notion, OpenRouter, search, vision
├── scripts/                # Setup checks
├── bootstrap-gui.cmd       # First-time install
├── start-gui.vbs           # Launch GUI
├── start-bot-background.cmd
└── .env.example
```

### Development

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
python -m shopping_bot.bot          # bot only
python -m shopping_bot.gui          # GUI
python scripts/check_setup.py       # test connections
```

### License

Personal project — use and modify freely. Do **not** commit `.env` or API keys.

---

## 中文

### 功能

- **保存到 Notion** — 名称、链接、分类、状态、备注、添加时间
- **转发流程** — 转发文字、链接或照片 → 选择 **搜索 / 添加商品 / 取消**
- **照片识别** — 视觉模型识别转发图片中的商品信息
- **AI 商品提取** — 阅读回复链和链接预览，推断商品名与分类
- **AI 通用搜索** — `/search` 用于与购物无关的问答（不写入 Notion）
- **模型切换** — `/model` 切换 OpenRouter 模型
- **GUI 控制面板** — 配置 `.env`、启停/重启机器人、查看日志、浅色/深色主题
- **消息确认** — 收到消息时用 👀 表情回应

### 环境要求

- Python **3.11+**
- Windows（GUI 脚本面向 Windows；机器人本体可在任意 Python 环境运行）
- 需要：**Telegram Bot**、**OpenRouter**、**Notion** 账号与密钥

### 快速开始

**1. 克隆并安装**

```powershell
git clone https://github.com/Young-Xia/telegram-shopping-bot.git
cd telegram-shopping-bot
.\bootstrap-gui.cmd
```

**2. 配置**

- 打开控制面板：双击 `打开控制面板.bat` 或运行 `start-gui.vbs`
- 进入 **初始设置**，填写密钥后点 **保存配置**
- 点 **测试连接** 检查 Telegram / OpenRouter / Notion

或手动配置：

```powershell
copy .env.example .env
# 编辑 .env 填入密钥
```

**3. 运行**

- 控制面板：**运行控制** → **启动**
- 或命令行：

```powershell
.\start-bot-background.cmd
```

> **注意：** 同一个 Telegram Bot Token 不能同时在两个程序里运行，启动前请先停止其他实例。

### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | 是 | 从 [@BotFather](https://t.me/BotFather) 获取 |
| `ALLOWED_TELEGRAM_USER_IDS` | 否 | 逗号分隔的用户 ID；留空则不限制 |
| `OPENROUTER_API_KEY` | 是 | 从 [OpenRouter](https://openrouter.ai) 获取 |
| `OPENROUTER_DEFAULT_MODEL` | 否 | 默认对话模型（默认 `openrouter/free`） |
| `OPENROUTER_VISION_MODEL` | 否 | 照片识别模型（默认 `google/gemini-2.5-flash`） |
| `OPENROUTER_MODELS` | 否 | 供 `/model` 切换的模型列表 |
| `NOTION_TOKEN` | 是 | Notion Integration Secret |
| `NOTION_DATABASE_ID` | 是 | 32 位数据库 ID |
| `SEARCH_PROVIDER` | 否 | `duckduckgo`（默认）或 `google` |
| `GOOGLE_CSE_API_KEY` / `GOOGLE_CSE_ID` | 否 | 仅 `SEARCH_PROVIDER=google` 时需要 |

Notion 数据库属性（名称可通过 `NOTION_*_PROPERTY` 自定义）：

| 属性 | 类型 |
|------|------|
| 名称 | 标题 (Title) |
| 链接 | 链接 (URL) |
| 分类 | 选择 (Select) |
| 状态 | 状态 (Status) |
| 备注 | 文本 (Text) |
| Added At | 日期 (Date) |

详细 Notion 配置见 [NOTION-SETUP.md](./NOTION-SETUP.md)。

### 机器人命令

| 命令 | 说明 |
|------|------|
| `/start` | 欢迎说明 |
| `/help` | 命令列表 |
| `/save` | 从回复链 AI 提取商品并保存 |
| `/search <问题>` | AI 通用搜索（不写入 Notion） |
| `/ask <问题>` | 向 AI 提问（可回复消息后发送 `/ask`） |
| `/add <名称> <链接>` | 通过链接添加商品 |
| `/model [模型名]` | 查看或切换 AI 模型 |
| `/clear` | 清除 AI 对话上下文 |
| `/cancel` | 取消当前购物流程 |

### 购物流程

**转发消息**

1. 将文字、链接或照片转发给机器人
2. 机器人回复 👀 并显示预览
3. 点击 **搜索**、**添加商品** 或 **取消**

**回复链保存**

1. 回复一条包含商品信息的消息
2. 发送 `/save`
3. AI 提取商品信息 → 选择 Notion 分类 → 保存

**快速粘贴**

直接发送「描述 + 商品链接」→ 选择分类 → 保存

### 项目结构

```
telegram-shopping-bot/
├── src/shopping_bot/
│   ├── bot.py              # Telegram 机器人主逻辑
│   ├── config.py           # 配置加载
│   ├── gui/                # CustomTkinter 控制面板
│   └── services/           # Notion、OpenRouter、搜索、视觉识别
├── scripts/                # 连接测试脚本
├── bootstrap-gui.cmd       # 首次安装依赖
├── start-gui.vbs           # 启动控制面板
├── start-bot-background.cmd
└── .env.example
```

### 开发

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
python -m shopping_bot.bot          # 仅运行机器人
python -m shopping_bot.gui          # 控制面板
python scripts/check_setup.py       # 测试连接
```

### 许可

个人项目，可自由使用和修改。请勿提交 `.env` 或 API 密钥。
