"""Exercise rate-limit recovery without sending prompts or waiting for a provider."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import llm_provider


def quota_response(message="", **headers):
    return httpx.Response(429, headers=headers, json={"error": {"message": message}})


class GroqLimitTests(unittest.TestCase):
    def setUp(self):
        self.responses = []
        self.payloads = []
        self.enterContext(patch.object(llm_provider, "LLM_PROVIDER", "groq"))
        self.enterContext(patch.dict(os.environ, {"GROQ_MODEL": "openai/gpt-oss-120b"}))
        client = self.enterContext(httpx.Client(base_url="https://test.invalid/", transport=httpx.MockTransport(self.handle)))
        self.enterContext(patch.object(llm_provider, "client", return_value=client))
        self.sleep = self.enterContext(patch.object(llm_provider.time, "sleep"))

    def handle(self, request):
        self.payloads.append(json.loads(request.content))
        return self.responses.pop(0)

    def test_recovers_after_multiple_consecutive_limits(self):
        self.responses = [
            quota_response(**{"retry-after": "5.3"}),
            quota_response("Rate limit reached. Please try again in 2.5s."),
            quota_response("Rate limit reached on tokens per minute.", **{"x-ratelimit-reset-tokens": "4.50s"}),
            httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}),
        ]
        self.assertEqual(llm_provider.chat_json("Example"), "{}")
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [6, 3, 5])
        self.assertTrue(all(payload["reasoning_effort"] == "low" for payload in self.payloads))

    def test_daily_limits_do_not_retry_blindly_or_disclose_provider_details(self):
        cases = [
            (quota_response("TPD limit reached for private-account-example. Please try again in 1h2m3.1s."), 3724),
            (quota_response("Tokens per day (TPD) exceeded.", **{"x-ratelimit-reset-tokens": "1s"}), None),
            (quota_response(**{"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "2m18s"}), 138),
        ]
        for response, seconds in cases:
            with self.subTest(seconds=seconds):
                self.responses = [response]
                with self.assertLogs(llm_provider.logger, "WARNING") as log, self.assertRaises(llm_provider.LLMError) as error:
                    llm_provider.chat_json("Private prompt example")
                self.assertEqual(error.exception.error_code, "rate_limited")
                self.assertEqual(error.exception.retry_after_seconds, seconds)
                self.assertIn("daily", str(error.exception))
                output = str(error.exception) + "\n".join(log.output)
                self.assertNotIn("private-account-example", output)
                self.assertNotIn("Private prompt example", output)
                self.sleep.assert_not_called()

    def test_request_too_large_is_not_a_batch_cooldown(self):
        for response in [
            httpx.Response(413),
            quota_response("Request too large for model", **{"retry-after": "20"}),
            quota_response("Limit 8,000, Used 100, Requested 8,500"),
        ]:
            self.responses = [response]
            with self.assertRaises(llm_provider.LLMError) as error:
                llm_provider.chat_json("Example")
            self.assertEqual((error.exception.status_code, error.exception.error_code), (413, "input_too_large"))
            self.assertIsNone(error.exception.retry_after_seconds)
        self.sleep.assert_not_called()

    def test_missing_headers_back_off_with_bounded_total_wait(self):
        self.responses = [quota_response() for _ in range(5)]
        with self.assertRaises(llm_provider.LLMError) as error:
            llm_provider.chat_json("Example")
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [15, 30, 60])
        self.assertEqual(error.exception.error_code, "rate_limited")
        self.assertEqual(error.exception.retry_after_seconds, 60)


if __name__ == "__main__":
    unittest.main()
