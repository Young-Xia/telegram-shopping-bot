from __future__ import annotations

import re

CODE_FENCE_RE = re.compile(r"```(?:\w+)?\n?(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
HEADING_MARK_RE = re.compile(r"^(#{1,6})\s+(.+)$")
BULLET_RE = re.compile(r"^([*+\-•▪◦])\s+(.+)$")
NUMBERED_RE = re.compile(r"^(\d+)[.)、]\s+(.+)$")
BOLD_LINE_RE = re.compile(r"^\*\*(.+)\*\*$")
HR_RE = re.compile(r"^[\*\-_]{3,}$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_UNDERSCORE_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

HEADING_EMOJI: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"总结|结论|小结|概览|summary|overview", re.I), "📝"),
    (re.compile(r"优点|优势|亮点|推荐理由|pros", re.I), "✅"),
    (re.compile(r"缺点|风险|注意|警告|cons|warning", re.I), "⚠️"),
    (re.compile(r"价格|费用|多少钱|price|cost", re.I), "💰"),
    (re.compile(r"规格|参数|配置|spec", re.I), "📋"),
    (re.compile(r"步骤|方法|怎么|如何|教程|steps", re.I), "🔧"),
    (re.compile(r"链接|网址|来源|link|url", re.I), "🔗"),
    (re.compile(r"搜索|结果|回答|答案|result", re.I), "🔍"),
    (re.compile(r"商品|产品|物品|product", re.I), "📦"),
    (re.compile(r"建议|推荐|recommend", re.I), "⭐"),
)


def _strip_emphasis(text: str) -> str:
    text = BOLD_RE.sub(r"\1", text)
    text = ITALIC_UNDERSCORE_RE.sub(r"\1", text)
    text = LINK_RE.sub(r"\1 (\2)", text)
    # Models often leave stray markdown markers; drop them for Telegram plain text.
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = text.replace("*", "").replace("`", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _emojify_heading(title: str) -> str:
    title = _strip_emphasis(title)
    if not title:
        return ""
    if title[0] in "📌📝✅⚠️💰📋🔧🔗🔍📦⭐💡•":
        return title
    for pattern, emoji in HEADING_EMOJI:
        if pattern.search(title):
            return f"{emoji} {title}"
    return f"📌 {title}"


def format_ai_text(text: str) -> str:
    """Turn model markdown into Telegram-friendly plain text with light emoji."""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = CODE_FENCE_RE.sub(lambda match: match.group(1).strip(), text)
    text = INLINE_CODE_RE.sub(r"\1", text)

    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if HR_RE.fullmatch(stripped):
            lines.append("————")
            continue

        heading = HEADING_MARK_RE.match(stripped)
        if heading:
            lines.append(_emojify_heading(heading.group(2)))
            continue

        bold_line = BOLD_LINE_RE.fullmatch(stripped)
        if bold_line:
            lines.append(_emojify_heading(bold_line.group(1)))
            continue

        bullet = BULLET_RE.match(stripped)
        if bullet:
            lines.append(f"• {_strip_emphasis(bullet.group(2))}")
            continue

        numbered = NUMBERED_RE.match(stripped)
        if numbered:
            lines.append(f"{numbered.group(1)}. {_strip_emphasis(numbered.group(2))}")
            continue

        # Keep indentation lightly for nested plain lines.
        prefix = "  " if line[:1] in {" ", "\t"} else ""
        lines.append(f"{prefix}{_strip_emphasis(stripped)}")

    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        cleaned.append(line)
    return "\n".join(cleaned).strip()
