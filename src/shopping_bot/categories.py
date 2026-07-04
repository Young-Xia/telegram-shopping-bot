from __future__ import annotations

DEFAULT_CATEGORIES = ["食品", "日用品", "电子产品", "衣服", "其他"]

# Notion board columns use these colors so each category is a distinct area.
CATEGORY_COLORS: dict[str, str] = {
    "食品": "orange",
    "日用品": "blue",
    "电子产品": "purple",
    "衣服": "pink",
    "其他": "gray",
}

CATEGORY_PROPERTY_NAME = "分类"
URL_PROPERTY_NAME = "链接"
NOTES_PROPERTY_NAME = "备注"
IMAGES_PROPERTY_NAME = "图片"
TITLE_ALIASES = ("Name", "name", "名称", "标题")
URL_ALIASES = ("URL", "url", "链接", "Link", "link")
NOTES_ALIASES = ("Notes", "notes", "备注", "说明")
IMAGES_ALIASES = ("Images", "images", "Image", "image", "图片", "照片", "Photos", "photos", "Photo", "photo", "Files", "files")
