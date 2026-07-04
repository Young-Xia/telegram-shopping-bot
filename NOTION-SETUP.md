# Notion 初始配置

机器人会把商品写入你指定的 Notion **数据库**。按下面步骤配置一次即可。

## 1. 创建 Integration

1. 打开 [Notion Integrations](https://www.notion.so/my-integrations)
2. 新建 **Internal** Integration
3. 复制 **Internal Integration Secret**
   - 新 token 通常以 `ntn_` 开头
   - 旧 token 可能以 `secret_` 开头，两种都支持
   - 如果点过 **Regenerate**，旧 token 会立刻失效，必须用新的

## 2. 创建购物清单数据库

在 Notion 新建一个 **Database（表格）**，建议至少包含这些列：

| 属性名（默认中文） | 类型 | 说明 |
|--------------------|------|------|
| 名称 | Title | 商品名（必有标题列） |
| 链接 | URL | 商品链接 |
| 分类 | Select | 如：食品、日用品、电子产品、衣服、其他 |
| 状态 | Status 或 Select | 新建商品时的默认状态 |
| 备注 | Text (rich text) | 价格、规格等 |
| 图片 | Files & media | 转发图片会写入这一列 |
| Added At | Date | 添加时间（可选） |

说明：

- 列名可在 `.env` / 控制面板高级设置里改成英文（如 `Name`、`URL`、`Category`）
- 若缺少「链接 / 备注 / 分类 / 图片」等列，机器人在保存时会**尽量自动创建**
- 标题列必须已存在（Title 类型）

英文数据库示例：

| Property | Type |
|----------|------|
| Name | Title |
| URL | URL |
| Category | Select |
| Status | Status |
| Notes | Text |
| Images | Files & media |
| Added At | Date |

对应 `.env`：

```env
NOTION_TITLE_PROPERTY=Name
NOTION_URL_PROPERTY=URL
NOTION_CATEGORY_PROPERTY=Category
NOTION_STATUS_PROPERTY=Status
NOTION_STATUS_PROPERTY_TYPE=status
NOTION_DEFAULT_STATUS=Want
NOTION_NOTES_PROPERTY=Notes
NOTION_IMAGES_PROPERTY=Images
NOTION_ADDED_AT_PROPERTY=Added At
```

## 3. 把 Integration 连接到数据库

1. 打开购物清单数据库页面
2. 右上角 **⋯** → **Connections**（连接）
3. 添加刚才创建的 Integration

未连接时，即使 token 正确也无法读写数据库。

## 4. 获取 Database ID

打开数据库页面，浏览器地址类似：

```text
https://www.notion.so/workspace/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...
```

复制中间 **32 位**字符（可带或不带横线）到配置里的 `NOTION_DATABASE_ID`。

## 5. 写入配置

### 方式 A：控制面板（推荐）

1. 双击 `打开控制面板.bat` 或运行 `start-gui.vbs`
2. 进入 **初始设置**
3. 填写：
   - `Notion Integration Token`
   - `Notion 数据库 ID`
4. 点 **保存配置**，再点 **测试连接**

高级设置里可改各列名称（名称 / 链接 / 分类 / 状态 / 备注 / 图片 / 添加时间）。

### 方式 B：手动编辑 `.env`

```env
NOTION_TOKEN=ntn_你的token
NOTION_DATABASE_ID=32位数据库ID

# 中文数据库默认列名（可按实际修改）
NOTION_TITLE_PROPERTY=名称
NOTION_URL_PROPERTY=链接
NOTION_CATEGORY_PROPERTY=分类
NOTION_STATUS_PROPERTY=状态
NOTION_STATUS_PROPERTY_TYPE=status
NOTION_DEFAULT_STATUS=未开始
NOTION_NOTES_PROPERTY=备注
NOTION_IMAGES_PROPERTY=图片
NOTION_ADDED_AT_PROPERTY=Added At
```

保存后在控制面板 **重启** 机器人，或：

```powershell
.\stop-bot.cmd
.\start-bot-background.cmd
```

## 6. 验证

控制面板点 **测试连接**，或：

```powershell
.\.venv\Scripts\python.exe scripts\check_setup.py
```

应看到类似：

```text
OK Notion database categories ...
```

可选写入测试行：

```powershell
.\.venv\Scripts\python.exe scripts\check_setup.py --write-test
```

会创建一条 `BOT_CHECK_DELETE_ME`，可在 Notion 里手动删除。

## 机器人如何写入 Notion

- **新建**：写入名称、链接、分类、状态、备注、添加时间；有图片则上传到「图片」列
- **更新**：若链接相同（忽略追踪参数）或标题足够相似，会更新已有条目，而不是重复添加；更新时不改状态和添加时间
- **图片**：转发图片并「添加商品」时，最多附加 3 张到 Files 列

## 常见问题：401 Unauthorized

表示 token 无效，或 Integration 未连接到数据库。

1. 在 Integrations 页面重新复制 token（`ntn_` / `secret_`）
2. 确认数据库 **Connections** 已添加该 Integration
3. 更新控制面板 / `.env` 后 **重启机器人**
4. 再点 **测试连接**

不要把 `.env` 提交到 GitHub。
