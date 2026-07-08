from __future__ import annotations

import unittest

from shopping_bot.routing import Intent, MessageSignals, classify_message, is_ask_bot_message
from shopping_bot.services.openrouter import OpenRouterClient
from shopping_bot.text_format import format_ai_text, strip_model_thinking

RESULT = "🔍 回答"
FOLLOWUP = "💬 继续回答"


def _signals(**kwargs) -> MessageSignals:
    base = dict(
        is_forwarded=False,
        has_reply=False,
        reply_is_forward=False,
        reply_is_ask_bot=False,
        awaiting_category=False,
        has_user_text=True,
    )
    base.update(kwargs)
    return MessageSignals(**base)


class ClassifyMessageTests(unittest.TestCase):
    def test_bare_forward_is_record_only(self) -> None:
        intent = classify_message(_signals(is_forwarded=True))
        self.assertEqual(intent, Intent.RECORD_FORWARD)

    def test_bare_forward_photo_is_record_only(self) -> None:
        intent = classify_message(_signals(is_forwarded=True, has_user_text=False))
        self.assertEqual(intent, Intent.RECORD_FORWARD)

    def test_reply_to_forward_starts_ask(self) -> None:
        intent = classify_message(
            _signals(has_reply=True, reply_is_forward=True, has_user_text=True)
        )
        self.assertEqual(intent, Intent.ASK_START)

    def test_reply_to_ask_bot_is_followup(self) -> None:
        intent = classify_message(
            _signals(has_reply=True, reply_is_ask_bot=True, has_user_text=True)
        )
        self.assertEqual(intent, Intent.ASK_FOLLOWUP)

    def test_followup_beats_forward_flag_on_reply_target(self) -> None:
        # If the bot answer somehow also looked like a forward, ask-bot wins.
        intent = classify_message(
            _signals(
                has_reply=True,
                reply_is_forward=True,
                reply_is_ask_bot=True,
            )
        )
        self.assertEqual(intent, Intent.ASK_FOLLOWUP)

    def test_plain_text_without_reply_is_ignore(self) -> None:
        intent = classify_message(_signals(has_user_text=True))
        self.assertEqual(intent, Intent.IGNORE)

    def test_plain_text_after_ask_without_reply_is_still_ignore(self) -> None:
        # Active session alone must not continue; only reply to AI answer.
        intent = classify_message(_signals(has_user_text=True, has_reply=False))
        self.assertEqual(intent, Intent.IGNORE)

    def test_reply_to_unrelated_message_is_ignore(self) -> None:
        intent = classify_message(
            _signals(has_reply=True, reply_is_forward=False, reply_is_ask_bot=False)
        )
        self.assertEqual(intent, Intent.IGNORE)

    def test_awaiting_category_wins(self) -> None:
        intent = classify_message(
            _signals(
                awaiting_category=True,
                is_forwarded=True,
                has_reply=True,
                reply_is_ask_bot=True,
            )
        )
        self.assertEqual(intent, Intent.SHOPPING_CATEGORY)


class StripThinkingTests(unittest.TestCase):
    def test_keeps_final_priority_block(self) -> None:
        raw = (
            "我们需要理解用户追问：xxx\n"
            "输出风格必须符合要求。\n"
            "首先回顾病例：a b c\n"
            "我按紧急排序：\n"
            "结论\n"
            "1. i 气道梗阻\n"
            "2. c 主动脉夹层\n"
        )
        cleaned = strip_model_thinking(raw)
        self.assertIn("1. i 气道梗阻", cleaned)
        self.assertNotIn("我们需要理解", cleaned)

    def test_format_keeps_emoji_lists(self) -> None:
        text = format_ai_text("结论\n• 先处理 A\n• 再处理 B")
        self.assertIn("• 先处理 A", text)

    def test_strips_inline_markdown(self) -> None:
        text = format_ai_text("**加粗** 和 `代码` 以及 [链接](https://x.com)")
        self.assertEqual(text, "加粗 和 代码 以及 链接")
        self.assertNotIn("**", text)
        self.assertNotIn("`", text)


class AskMediaFocusTests(unittest.TestCase):
    def test_photo_only_uses_image(self) -> None:
        from shopping_bot.routing import AskMediaFocus, decide_ask_media_focus

        self.assertEqual(
            decide_ask_media_focus("这是什么", has_photos=True, has_text=False),
            AskMediaFocus.IMAGE,
        )

    def test_text_only_uses_text(self) -> None:
        from shopping_bot.routing import AskMediaFocus, decide_ask_media_focus

        self.assertEqual(
            decide_ask_media_focus("总结这段话", has_photos=False, has_text=True),
            AskMediaFocus.TEXT,
        )

    def test_mixed_follows_image_instruction(self) -> None:
        from shopping_bot.routing import AskMediaFocus, decide_ask_media_focus

        self.assertEqual(
            decide_ask_media_focus("翻译图片里的文字", has_photos=True, has_text=True),
            AskMediaFocus.IMAGE,
        )

    def test_mixed_follows_text_instruction(self) -> None:
        from shopping_bot.routing import AskMediaFocus, decide_ask_media_focus

        self.assertEqual(
            decide_ask_media_focus("总结这段文字", has_photos=True, has_text=True),
            AskMediaFocus.TEXT,
        )

    def test_mixed_ambiguous_defaults_both(self) -> None:
        from shopping_bot.routing import AskMediaFocus, decide_ask_media_focus

        self.assertEqual(
            decide_ask_media_focus("介绍一下", has_photos=True, has_text=True),
            AskMediaFocus.BOTH,
        )


class ExtractMessageTextTests(unittest.TestCase):
    def test_string_content(self) -> None:
        text = OpenRouterClient._extract_message_text({"content": "  hello  "})
        self.assertEqual(text, "hello")

    def test_list_content(self) -> None:
        text = OpenRouterClient._extract_message_text(
            {"content": [{"type": "text", "text": "你好"}, {"type": "text", "text": "世界"}]}
        )
        self.assertEqual(text, "你好\n世界")

    def test_reasoning_fallback(self) -> None:
        text = OpenRouterClient._extract_message_text(
            {"content": "", "reasoning_content": "这是推理内容"}
        )
        self.assertEqual(text, "这是推理内容")


class AskBotMessageTests(unittest.TestCase):
    def test_result_prefix(self) -> None:
        self.assertTrue(is_ask_bot_message(f"{RESULT}\n\nhi", result_prefix=RESULT, followup_prefix=FOLLOWUP))

    def test_followup_prefix(self) -> None:
        self.assertTrue(
            is_ask_bot_message(f"{FOLLOWUP}\n\nhi", result_prefix=RESULT, followup_prefix=FOLLOWUP)
        )

    def test_normal_text_is_not_ask_bot(self) -> None:
        self.assertFalse(is_ask_bot_message("普通消息", result_prefix=RESULT, followup_prefix=FOLLOWUP))


if __name__ == "__main__":
    unittest.main()
