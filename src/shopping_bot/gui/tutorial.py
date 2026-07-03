"""Chinese in-app tutorial for the Telegram shopping bot."""

BOT_TUTORIAL_ZH = """\
购物助手使用教程

一、保存商品到 Notion
  1. 直接转发：把商品消息（文字、链接或照片）转发给机器人 → 点「搜索 / 添加商品 / 取消」
  2. 回复链保存：回复某条消息后发送 /save → AI 阅读整条回复链 → 选择分类
  3. 快速粘贴：直接发送「描述 + 商品链接」→ 选择分类保存

二、常用命令
  /start   查看欢迎说明
  /help    查看命令列表
  /save    从回复链 AI 提取商品并保存
  /search  关键词搜索或 AI 通用问答（与购物无关时不写入 Notion）
  /ask     向 AI 提问（可回复某条消息后发送 /ask）
  /model   查看或切换 AI 模型
  /clear   清除 AI 对话上下文
  /cancel  取消当前购物流程

三、AI 问答
  • 私聊中：回复某条消息后直接输入文字，机器人会用当前模型回答
  • 群聊中：回复消息时需 @机器人，避免误触发

四、控制面板
  1. 在「初始设置」填写密钥并保存，可点「测试连接」检查配置
  2. 回到「运行控制」点「启动」，机器人在后台运行
  3. 「运行日志」可查看 bot.log 输出

五、提示
  • 同一 Telegram Bot Token 不能同时在两个程序里运行
  • 修改 .env 或切换 AI 服务商后，请在控制面板重启机器人
"""

SETUP_GUIDE_ZH = """\
初始配置教程

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、Telegram 机器人
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 在 Telegram 搜索 @BotFather，发送 /newbot 创建机器人
2. 按提示取名，复制得到的 Bot Token
3. 填入「Telegram Bot Token」

可选 — 限制使用者：
  • 搜索 @userinfobot 获取你的数字 User ID
  • 填入「允许使用的 Telegram 用户 ID」（逗号分隔多个）
  • 留空表示不限制

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、AI 模型 / API（支持多家服务商）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本机器人使用 OpenAI 兼容的 Chat Completions 接口，可接入多家 API。

必填：
  • 「AI API Key」— 对应服务商的密钥

可选：
  • 「AI API 地址」— 留空默认 OpenRouter
  • 「默认对话模型」— 须与所选服务商匹配
  • 「视觉识别模型」— 识别转发照片时使用，须支持 vision
  • 「可选模型列表」— 逗号分隔，供 /model 切换

常用配置示例：

  OpenRouter（默认，多模型聚合）
    API 地址: https://openrouter.ai/api/v1
    Key: 在 https://openrouter.ai 创建
    模型示例: openrouter/free, google/gemini-2.5-flash

  DeepSeek
    API 地址: https://api.deepseek.com/v1
    Key: 在 platform.deepseek.com 创建
    模型示例: deepseek-chat
    ⚠ DeepSeek 不支持图片，照片识别需另配「视觉 API」（见下）

  照片识别（与对话 API 分开配置）
    若主 API 不支持图片（如 DeepSeek），请额外填写：
      • 视觉 API 地址: https://openrouter.ai/api/v1
      • 视觉 API Key: 你的 OpenRouter Key
      • 视觉识别模型: google/gemini-2.5-flash

  OpenAI
    API 地址: https://api.openai.com/v1
    Key: 在 platform.openai.com 创建
    模型示例: gpt-4o-mini, gpt-4o

  DeepSeek
    API 地址: https://api.deepseek.com/v1
    Key: 在 platform.deepseek.com 创建
    模型示例: deepseek-chat

  其他兼容接口（如 Groq、Together、本地 LM Studio / Ollama 等）
    API 地址: 填写服务商文档中的 /v1 地址
    模型示例: 按该服务商文档填写

提示：
  • 切换服务商后，请同步修改「默认对话模型」和「视觉识别模型」
  • 旧版 .env 中的 OPENROUTER_* 变量仍可使用，会自动映射到新字段

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、Notion 购物清单
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 打开 https://www.notion.so/my-integrations
2. 新建 Internal Integration，复制 Secret（ntn_ 或 secret_ 开头）
3. 填入「Notion Integration Token」

4. 在 Notion 创建购物清单数据库，右上角 ⋯ → 连接 → 添加该 Integration
   （未连接即使 Token 正确也无法写入）

5. 获取数据库 ID：
   • 打开数据库页面，看浏览器地址栏
   • URL 中 32 位字符即为 ID（无横线）
   • 填入「Notion 数据库 ID」

6. 数据库需包含以下属性（名称可在高级选项中修改）：

   属性名      类型
   ─────────────────
   Name        标题 (Title)
   URL         链接 (URL)
   Category    选择 (Select)
   Status      状态 (Status)，需有「Want」或你设定的默认状态
   Notes       文本 (Text)
   Added At    日期 (Date)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、保存与验证
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 点击「保存配置」写入 .env
2. 点击「测试连接」检查 Telegram / AI API / Notion
3. 全部通过后，到「运行控制」页点击「启动」

提示：Token 复制时不要带空格；修改配置后需重启机器人才生效。
"""
