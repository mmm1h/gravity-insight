from __future__ import annotations

import unittest
from unittest import mock

try:
    from gravity_insight import content_encoding
    from gravity_insight import http_runtime
except ModuleNotFoundError:  # source checkout without an editable install
    from gravity_insight import content_encoding
    from gravity_insight import http_runtime


class GravityInsightEncodingTests(unittest.TestCase):
    def test_no_optional_decoder_advertises_only_standard_encodings(self):
        with mock.patch.object(
            content_encoding,
            "_load_optional_content_encodings",
            return_value=frozenset(),
        ):
            self.assertEqual(
                "gzip, deflate",
                content_encoding._build_accept_encoding(),
            )

    def test_brotli_decoder_adds_br(self):
        with mock.patch.object(
            content_encoding,
            "_load_optional_content_encodings",
            return_value=frozenset({"br"}),
        ):
            self.assertEqual(
                "gzip, deflate, br",
                content_encoding._build_accept_encoding(),
            )

    def test_header_never_exceeds_available_decoders(self):
        for available in (
            frozenset(),
            frozenset({"br"}),
            frozenset({"zstd"}),
            frozenset({"br", "zstd"}),
        ):
            with self.subTest(available=available):
                advertised = set(
                    content_encoding._build_accept_encoding(available).split(", ")
                )
                self.assertEqual({"gzip", "deflate"}, advertised - available)
                self.assertLessEqual(
                    advertised,
                    {"gzip", "deflate"} | available,
                )

    def test_detection_failure_falls_back_without_breaking_headers(self):
        with mock.patch.object(
            content_encoding,
            "_load_optional_content_encodings",
            side_effect=RuntimeError("damaged decoder"),
        ):
            self.assertEqual(
                "gzip, deflate",
                content_encoding._build_accept_encoding(),
            )

        with mock.patch(
            "urllib3.response._get_decoder",
            side_effect=RuntimeError("damaged decoder"),
        ):
            self.assertEqual(
                frozenset(),
                content_encoding._load_optional_content_encodings(),
            )

    def test_browser_headers_use_the_once_cached_detection(self):
        self.assertEqual(
            content_encoding.ACCEPT_ENCODING,
            http_runtime.browser_headers(150)["Accept-Encoding"],
        )


if __name__ == "__main__":
    unittest.main()
