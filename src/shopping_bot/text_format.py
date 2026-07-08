from __future__ import annotations

import re

CODE_FENCE_RE = re.compile(r"```(?:\w+)?\n?(.*?)```", re.DOTALL)
HEADING_MARK_RE = re.compile(r"^(#{1,6})\s+(.+)$")
BULLET_RE = re.compile(r"^([*+\-•▪◦])\s+(.+)$")
NUMBERED_RE = re.compile(r"^(\d+)[.)、]\s+(.+)$")
BOLD_LINE_RE = re.compile(r"^\*\*(.+)\*\*$")
HR_RE = re.compile(r"^[\*\-_]{3,}$")
INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BOLD_INLINE_RE = re.compile(r"\*\*([^*]+)\*\*")
UNDERLINE_INLINE_RE = re.compile(r"__([^_]+)__")
STRIKE_INLINE_RE = re.compile(r"~~([^~]+)~~")
ITALIC_INLINE_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
ITALIC_UNDER_RE = re.compile(r"(?<!_)_([^_]+)_(?!_)")


# Model often dumps chain-of-thought / prompt restatement before the real answer.
THINKING_LINE_RE = re.compile(
    r"^(我们需要理解|这是关于先前|在对话历史中|输出风格必须|所以，?我要|首先回顾|"
    r"我需要对|作为急诊|注意，这是基于|我按紧急|先给结论|"
    r"User Safety:|用户追问：|请根据对话历史|不要说你看不到)",
    re.IGNORECASE,
)
ANSWER_START_RE = re.compile(
    r"^(#{1,3}\s*)?("
    r"结论|优先|排序|顺序|最终|答案|回答|分诊|建议|"
    r"第一|最紧急|立即|总结|"
    r"[✅⚠️🚨📌⭐🔥💡]"
    r")"
)


def strip_model_thinking(text: str) -> str:
    """Drop prompt-echo / chain-of-thought, keep the final answer body."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = text.split("\n")

    # If the model never leaves "thinking mode", try to find a late answer block.
    answer_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if ANSWER_START_RE.match(stripped) and idx > 0:
            # Prefer the last strong answer marker (final conclusion).
            answer_idx = idx

    if answer_idx is not None and answer_idx > 2:
        # Only cut if the beginning looks like thinking.
        head = "\n".join(lines[: min(answer_idx, 8)])
        if THINKING_LINE_RE.search(head) or "对话历史" in head or "输出风格" in head:
            return "\n".join(lines[answer_idx:]).strip()

    # Strip leading thinking lines until a normal content line.
    start = 0
    thinking_hits = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if THINKING_LINE_RE.match(stripped) or "输出风格" in stripped or "对话历史" in stripped:
            thinking_hits += 1
            start = idx + 1
            continue
        if thinking_hits >= 2 and idx > 3:
            # Enough evidence the preamble is thinking; keep from here.
            return "\n".join(lines[idx:]).strip()
        break

    if start > 0 and start < len(lines):
        rest = "\n".join(lines[start:]).strip()
        if rest:
            return rest
    return text.strip()


def strip_inline_markdown(text: str) -> str:
    """Remove inline markdown markers while keeping the visible text."""
    if not text:
        return ""
    cleaned = text
    for _ in range(4):
        cleaned = INLINE_LINK_RE.sub(r"\1", cleaned)
        cleaned = BOLD_INLINE_RE.sub(r"\1", cleaned)
        cleaned = UNDERLINE_INLINE_RE.sub(r"\1", cleaned)
        cleaned = STRIKE_INLINE_RE.sub(r"\1", cleaned)
        cleaned = ITALIC_INLINE_RE.sub(r"\1", cleaned)
        cleaned = ITALIC_UNDER_RE.sub(r"\1", cleaned)
        cleaned = INLINE_CODE_RE.sub(r"\1", cleaned)
    return cleaned.replace("**", "").replace("__", "").replace("~~", "")


def format_ai_text(text: str) -> str:
    """Clean model output for Telegram: drop thinking and all markdown."""
    if not text:
        return ""

    text = strip_model_thinking(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Keep fenced code body, drop fences only.
    text = CODE_FENCE_RE.sub(lambda match: match.group(1).strip(), text)

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
            lines.append(heading.group(2).strip())
            continue

        bold_line = BOLD_LINE_RE.fullmatch(stripped)
        if bold_line:
            lines.append(bold_line.group(1).strip())
            continue

        bullet = BULLET_RE.match(stripped)
        if bullet:
            lines.append(f"• {bullet.group(2).strip()}")
            continue

        numbered = NUMBERED_RE.match(stripped)
        if numbered:
            lines.append(f"{numbered.group(1)}. {numbered.group(2).strip()}")
            continue

        lines.append(strip_inline_markdown(stripped))

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
