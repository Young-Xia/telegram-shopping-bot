from __future__ import annotations

import unittest

from shopping_bot.services.openrouter import format_api_error_message


class FormatApiErrorTests(unittest.TestCase):
    def test_tos_403_is_user_friendly(self) -> None:
        msg = format_api_error_message(
            status_code=403,
            parsed={
                "error": {
                    "message": "The request is prohibited due to a violation of provider Terms Of Service.",
                    "code": 403,
                    "metadata": {"provider_name": "OpenAI"},
                }
            },
        )
        self.assertIn("403", msg)
        self.assertIn("openai/gpt-4o", msg)

    def test_tos_403_privacy_routing(self) -> None:
        msg = format_api_error_message(
            status_code=403,
            parsed={
                "error": {
                    "message": "The request is prohibited due to a violation of provider Terms Of Service.",
                    "code": 403,
                    "metadata": {"provider_name": None},
                }
            },
        )
        self.assertIn("privacy", msg)
        self.assertIn("openrouter.ai/settings/privacy", msg)

    def test_rate_limit(self) -> None:
        msg = format_api_error_message(status_code=429, body="too many requests")
        self.assertIn("429", msg)

    def test_404_guardrail_policy(self) -> None:
        msg = format_api_error_message(
            status_code=404,
            parsed={
                "error": {
                    "message": "No endpoints available matching your guardrail restrictions and data policy. Configure: https://openrouter.ai/settings/privacy",
                    "code": 404,
                }
            },
        )
        self.assertIn("guardrail", msg)
        self.assertIn("settings/privacy", msg)


if __name__ == "__main__":
    unittest.main()
