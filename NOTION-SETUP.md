# Notion 401 修复步骤

## 问题
`API token is invalid` = Notion 拒绝了你的 Integration Token。

## 诊断结果（你的配置）
- Token 格式：以 `secret_` 开头，长度正常
- Database ID：32 位十六进制，格式正常
- **但 Notion API 仍返回 401** → token 本身已失效或复制错误

## 修复步骤

### 1. 重新获取 Token
1. 打开 https://www.notion.so/my-integrations
2. 选择你的 Integration（或新建一个 **Internal** Integration）
3. 进入 **Configuration** → **Secrets**
4. 点击 **Show** 复制 **Internal Integration Secret**
   - 必须以 `secret_` 开头
   - 如果之前点过 **Regenerate**，旧 token 已作废，必须用新的

### 2. 把 Integration 连接到数据库
1. 在 Notion 打开你的「购物清单」数据库页面
2. 右上角 **⋯** → **Connections**（连接）
3. 搜索并添加刚才的 Integration
4. 没做这一步即使 token 正确也会保存失败

### 3. 获取 Database ID
1. 打开数据库页面
2. 浏览器地址栏 URL 类似：
   `https://www.notion.so/你的工作区/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...`
3. 复制中间 **32 位** 字符（无横线）到 `.env`：
   ```
   NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

### 4. 更新 .env
用记事本打开 `D:\Programs\telegram-shopping-bot\.env`：

```env
NOTION_TOKEN=secret_粘贴新token
NOTION_DATABASE_ID=32位数据库ID
```

保存后重启 bot：

```cmd
cd /d D:\Programs\telegram-shopping-bot
start-shopping-bot.cmd
```

### 5. 验证
```cmd
check.cmd
```
应看到 `OK Notion database categories ...`

## 数据库字段要求
确保数据库有这些属性（名称可在 .env 里改）：

| 属性名 | 类型 |
|--------|------|
| Name | Title |
| URL | URL |
| Category | Select |
| Status | Status（需有 Want 选项） |
| Notes | Text |
| Added At | Date |
