# Telegram Shopping Bot

Private Telegram bot for:

- switching OpenRouter models
- answering quoted Telegram messages
- searching products with Google Custom Search
- parsing product links
- asking for a category
- saving shopping items into a Notion database

## 1. Setup

```powershell
cd D:\Programs\telegram-shopping-bot
setup-env.cmd
```

`setup-env.cmd` copies `.env.example` to `.env` and opens Notepad for editing.
If you prefer prompts in PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-env.ps1
```

Do not commit `.env`.

## 2. Required Credentials

### Telegram

Create a bot with `@BotFather`, then set:

```env
TELEGRAM_BOT_TOKEN=...
```

Recommended: restrict the bot to your own Telegram user ID:

```env
ALLOWED_TELEGRAM_USER_IDS=123456789
```

You can get your numeric Telegram user ID from bots such as `@userinfobot`.

### OpenRouter

Set your OpenRouter key:

```env
OPENROUTER_API_KEY=...
OPENROUTER_DEFAULT_MODEL=openrouter/free
OPENROUTER_MODELS=openrouter/free,qwen/qwen3-coder:free,qwen/qwen3-next-80b-a3b-instruct:free
```

These are direct OpenRouter model IDs. The bot also accepts OpenClaw-style
`openrouter/qwen/...` refs and normalizes them before sending requests.

### Google Custom Search

Optional. Default search uses DuckDuckGo and needs no API key.

To use Google instead, set:

```env
SEARCH_PROVIDER=google
GOOGLE_CSE_API_KEY=...
GOOGLE_CSE_ID=...
```

### Notion

Create a Notion integration and share your shopping database with it.

Set:

```env
NOTION_TOKEN=...
NOTION_DATABASE_ID=...
```

Create these database properties in Notion:

- `Name`: title
- `URL`: url
- `Category`: select
- `Status`: status, with an option named `Want`
- `Notes`: text/rich text
- `Added At`: date

If you use different property names, update the matching `NOTION_*_PROPERTY` values in `.env`.

## 3. Run

First check all external services:

```powershell
cd D:\Programs\telegram-shopping-bot
check.cmd
```

Then run the bot:

```powershell
start-shopping-bot.cmd
```

This disconnects Telegram from OpenClaw (same bot token cannot run in two apps), then starts the shopping bot.

Or use `run.cmd` if OpenClaw is not using your Telegram bot.

## 4. Commands

```text
/start
/help
/model
/model openrouter/free
/ask 你好
/search 机械键盘
/search https://example.com/product
```

Quoted-message Q&A:

1. Reply to a Telegram message.
2. Send `/ask`.
3. The bot answers the quoted message using your current model.

In private chat, replying with normal text also asks the bot to answer the quoted message.
In groups, mention the bot in the reply to avoid accidental auto-responses.

## 5. Shopping Flow

1. Send `/search 商品名` or `/search 商品链接`.
2. If it is a keyword, choose one Google result.
3. Choose an existing Notion category or add a new one.
4. The bot creates a Notion page with title, URL, category, status, notes, and added time.
