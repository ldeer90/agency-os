from __future__ import annotations

import unittest

from scripts.smoke_reporting_apis import (
    GOOGLE_ENV_KEYS,
    SE_RANKING_ENV_KEYS,
    parse_assignment,
    sanitized_error,
)


class SmokeReportingApisTest(unittest.TestCase):
    def test_parse_assignment_loads_only_allowed_keys(self) -> None:
        self.assertEqual(
            parse_assignment('export GOOGLE_CLOUD_PROJECT="seo-agency-work"', GOOGLE_ENV_KEYS),
            ("GOOGLE_CLOUD_PROJECT", "seo-agency-work"),
        )
        self.assertEqual(
            parse_assignment("PROJECT_API_TOKEN=secret-value", SE_RANKING_ENV_KEYS),
            ("PROJECT_API_TOKEN", "secret-value"),
        )
        self.assertIsNone(parse_assignment("MONDAY_API_KEY=secret-value", GOOGLE_ENV_KEYS))

    def test_sanitized_error_masks_token_like_values(self) -> None:
        error_class, message = sanitized_error(RuntimeError("failed with token=abc123 and Authorization: Token abc123"))

        self.assertEqual(error_class, "RuntimeError")
        self.assertIn("token=[redacted]", message)
        self.assertIn("Token [redacted]", message)
        self.assertNotIn("abc123", message)


if __name__ == "__main__":
    unittest.main()
