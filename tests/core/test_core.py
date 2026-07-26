"""Tests for the shared core: transport decoding, retry, error mapping.

These are the layer the review flagged as "100% of where bugs are subtle and
silent". Testing them once here is the whole point of the merge — the gzip
sniff and the 429 policy are now proven for every carrier at the same time.
"""
from __future__ import annotations

import gzip
import logging
import pathlib
import sys
import unittest
import zlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tests"))

from carriers._core.config import env_value, load_env_file
from carriers._core.errors import CarrierRateLimitError, CarrierTransportError
from carriers._core.multipart import encode_multipart_form_data
from carriers._core.retry import RetryPolicy, retry_after_seconds
from carriers._core.transport import decode_response_body
from carriers.fedex import FedExClient, FedExConfig
from carriers.ups import UPSClient, UPSConfig
from support import FakeTransport, RecordingSleep, json_response, transport_error


class DecodeResponseBodyTests(unittest.TestCase):
    def test_plain_utf8_passes_through(self):
        self.assertEqual(decode_response_body(b'{"a":1}', {}), '{"a":1}')

    def test_gzip_declared_by_header(self):
        raw = gzip.compress(b'{"ok":true}')
        self.assertEqual(
            decode_response_body(raw, {"Content-Encoding": "gzip"}), '{"ok":true}'
        )

    def test_gzip_detected_by_magic_bytes_when_header_lies(self):
        # This is the case that used to raise UnicodeDecodeError on FedEx.
        raw = gzip.compress(b'{"ok":true}')
        self.assertEqual(decode_response_body(raw, {}), '{"ok":true}')

    def test_header_name_matching_is_case_insensitive(self):
        raw = gzip.compress(b"hello")
        self.assertEqual(decode_response_body(raw, {"content-encoding": "GZIP"}), "hello")

    def test_deflate_with_zlib_header(self):
        raw = zlib.compress(b"hello")
        self.assertEqual(decode_response_body(raw, {"Content-Encoding": "deflate"}), "hello")

    def test_raw_deflate_without_zlib_header(self):
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        raw = compressor.compress(b"hello") + compressor.flush()
        self.assertEqual(decode_response_body(raw, {"Content-Encoding": "deflate"}), "hello")


class RetryAfterTests(unittest.TestCase):
    def test_delta_seconds(self):
        self.assertEqual(retry_after_seconds({"Retry-After": "12"}), 12.0)

    def test_http_date_is_relative_to_now(self):
        value = retry_after_seconds({"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        # Long past, so it clamps to zero rather than going negative.
        self.assertEqual(value, 0.0)

    def test_missing_header(self):
        self.assertIsNone(retry_after_seconds({}))

    def test_unparseable_header(self):
        self.assertIsNone(retry_after_seconds({"Retry-After": "soon"}))


class RetryPolicyTests(unittest.TestCase):
    def test_attempts_are_capped(self):
        policy = RetryPolicy(attempts=2)
        self.assertTrue(policy.should_retry(attempt=1, method="GET", status_code=503))
        self.assertFalse(policy.should_retry(attempt=2, method="GET", status_code=503))

    def test_non_retryable_status(self):
        policy = RetryPolicy()
        self.assertFalse(policy.should_retry(attempt=1, method="GET", status_code=404))

    def test_post_does_not_retry_5xx_by_default(self):
        # A 500 on POST /ship may mean the label was bought and the response
        # lost. Retrying would double-book.
        policy = RetryPolicy()
        self.assertFalse(policy.should_retry(attempt=1, method="POST", status_code=503))

    def test_post_does_retry_429(self):
        policy = RetryPolicy()
        self.assertTrue(policy.should_retry(attempt=1, method="POST", status_code=429))

    def test_post_retries_5xx_when_explicitly_opted_in(self):
        policy = RetryPolicy(retry_non_idempotent=True)
        self.assertTrue(policy.should_retry(attempt=1, method="POST", status_code=503))

    def test_transport_failure_retries_only_for_idempotent_methods(self):
        policy = RetryPolicy()
        self.assertTrue(policy.should_retry(attempt=1, method="GET", status_code=None))
        self.assertFalse(policy.should_retry(attempt=1, method="POST", status_code=None))

    def test_retry_after_header_beats_computed_backoff(self):
        policy = RetryPolicy(backoff_factor=0.5, jitter=False)
        self.assertEqual(policy.delay_for(attempt=1, headers={"Retry-After": "7"}), 7.0)

    def test_retry_after_is_clamped_to_max_backoff(self):
        policy = RetryPolicy(max_backoff=5.0)
        self.assertEqual(policy.delay_for(attempt=1, headers={"Retry-After": "900"}), 5.0)

    def test_backoff_is_exponential_without_jitter(self):
        policy = RetryPolicy(backoff_factor=0.5, jitter=False)
        self.assertEqual(policy.delay_for(attempt=1), 0.5)
        self.assertEqual(policy.delay_for(attempt=2), 1.0)
        self.assertEqual(policy.delay_for(attempt=3), 2.0)

    def test_disabled_policy_never_retries(self):
        policy = RetryPolicy.disabled()
        self.assertFalse(policy.should_retry(attempt=1, method="GET", status_code=503))


class ClientRetryTests(unittest.TestCase):
    def config(self):
        return UPSConfig(
            client_id="id",
            client_secret="secret",
            base_url="https://example.test",
        )

    def token(self):
        return json_response(200, {"access_token": "t", "expires_in": "3600"})

    def test_rate_limited_get_retries_and_then_succeeds(self):
        sleep = RecordingSleep()
        transport = FakeTransport(
            [
                self.token(),
                json_response(429, {"message": "slow down"}, {"Retry-After": "3"}),
                json_response(200, {"ok": True}),
            ]
        )
        client = UPSClient(
            self.config(),
            transport=transport,
            retry_policy=RetryPolicy(attempts=3, sleep=sleep),
        )

        response = client.get("/api/track/v1/details/1Z")

        self.assertEqual(response.data, {"ok": True})
        self.assertEqual(sleep.calls, [3.0])
        self.assertEqual(len(transport.requests), 3)

    def test_retries_are_exhausted_and_the_error_carries_retry_after(self):
        sleep = RecordingSleep()
        transport = FakeTransport(
            [
                self.token(),
                json_response(429, {"message": "slow"}, {"Retry-After": "1"}),
                json_response(429, {"message": "slow"}, {"Retry-After": "1"}),
            ]
        )
        client = UPSClient(
            self.config(),
            transport=transport,
            retry_policy=RetryPolicy(attempts=2, sleep=sleep),
        )

        with self.assertRaises(CarrierRateLimitError) as raised:
            client.get("/api/track/v1/details/1Z")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, 1.0)
        self.assertEqual(len(sleep.calls), 1)

    def test_post_is_not_retried_on_server_error(self):
        transport = FakeTransport(
            [self.token(), json_response(503, {"message": "unavailable"})]
        )
        client = UPSClient(
            self.config(),
            transport=transport,
            retry_policy=RetryPolicy(attempts=3, sleep=RecordingSleep()),
        )

        with self.assertRaises(Exception):
            client.post("/api/shipments/v2409/ship", {"ShipmentRequest": {}})

        # Two requests: the token and the single ship attempt.
        self.assertEqual(len(transport.requests), 2)

    def test_transport_failure_on_get_is_retried_then_reraised(self):
        sleep = RecordingSleep()
        transport = FakeTransport(
            [self.token(), transport_error(), transport_error()]
        )
        client = UPSClient(
            self.config(),
            transport=transport,
            retry_policy=RetryPolicy(attempts=2, sleep=sleep),
        )

        with self.assertRaises(CarrierTransportError):
            client.get("/api/track/v1/details/1Z")

        self.assertEqual(len(sleep.calls), 1)


class UrlBuildingTests(unittest.TestCase):
    def client(self):
        return UPSClient(
            UPSConfig(
                client_id="id", client_secret="secret", base_url="https://example.test/"
            ),
            transport=FakeTransport([]),
        )

    def test_absolute_paths_bypass_the_base_url(self):
        url = self.client()._build_url("https://other.test/thing", None)
        self.assertEqual(url, "https://other.test/thing")

    def test_none_valued_query_params_are_dropped(self):
        url = self.client()._build_url("/api/x", {"a": 1, "b": None})
        self.assertEqual(url, "https://example.test/api/x?a=1")

    def test_all_none_query_yields_no_question_mark(self):
        url = self.client()._build_url("/api/x", {"a": None})
        self.assertEqual(url, "https://example.test/api/x")


class ErrorMessageTests(unittest.TestCase):
    def ups(self):
        return UPSClient(
            UPSConfig(client_id="i", client_secret="s", base_url="https://x.test"),
            transport=FakeTransport([]),
        )

    def fedex(self):
        return FedExClient(
            FedExConfig(client_id="i", client_secret="s", base_url="https://x.test"),
            transport=FakeTransport([]),
        )

    def test_ups_errors_are_read_through_the_response_envelope(self):
        payload = {"response": {"errors": [{"code": "120100", "message": "Bad field"}]}}
        self.assertEqual(self.ups()._error_message(payload), "120100: Bad field")

    def test_fedex_errors_are_read_at_the_top_level(self):
        payload = {"errors": [{"code": "BAD.REQUEST", "message": "Invalid"}]}
        self.assertEqual(self.fedex()._error_message(payload), "BAD.REQUEST: Invalid")

    def test_multiple_errors_are_joined(self):
        payload = {"errors": [{"code": "A", "message": "one"}, {"code": "B", "message": "two"}]}
        self.assertEqual(self.fedex()._error_message(payload), "A: one; B: two")

    def test_oauth_style_error_description(self):
        payload = {"error": "invalid_client", "error_description": "bad secret"}
        self.assertEqual(self.fedex()._error_message(payload), "bad secret")

    def test_unrecognised_shape_returns_none(self):
        self.assertIsNone(self.fedex()._error_message(["nope"]))


class SharedErrorHierarchyTests(unittest.TestCase):
    def test_carrier_errors_share_a_base(self):
        from carriers import CarrierAPIError
        from carriers.fedex import FedExAPIError
        from carriers.ups import UPSAPIError

        self.assertTrue(issubclass(UPSAPIError, CarrierAPIError))
        self.assertTrue(issubclass(FedExAPIError, CarrierAPIError))
        # ...but neither is catchable as the other.
        self.assertFalse(issubclass(UPSAPIError, FedExAPIError))


class TokenCachingTests(unittest.TestCase):
    def test_token_is_fetched_once_and_reused(self):
        transport = FakeTransport(
            [
                json_response(200, {"access_token": "t1", "expires_in": "3600"}),
                json_response(200, {"ok": 1}),
                json_response(200, {"ok": 2}),
            ]
        )
        client = UPSClient(
            UPSConfig(client_id="i", client_secret="s", base_url="https://x.test"),
            transport=transport,
        )

        client.get("/a")
        client.get("/b")

        token_requests = [r for r in transport.requests if r["url"].endswith("/oauth/token")]
        self.assertEqual(len(token_requests), 1)

    def test_expired_token_is_refreshed(self):
        transport = FakeTransport(
            [
                json_response(200, {"access_token": "t1", "expires_in": "1"}),
                json_response(200, {"access_token": "t2", "expires_in": "3600"}),
                json_response(200, {"ok": 1}),
            ]
        )
        client = UPSClient(
            UPSConfig(client_id="i", client_secret="s", base_url="https://x.test"),
            transport=transport,
        )

        first = client.get_access_token()
        second = client.get_access_token()

        self.assertEqual(first.value, "t1")
        self.assertEqual(second.value, "t2")

    def test_token_is_never_written_to_disk(self):
        # Guards against reintroducing a token cache file. The client holds
        # the token in memory behind a lock and nowhere else.
        client = UPSClient(
            UPSConfig(client_id="i", client_secret="s", base_url="https://x.test"),
            transport=FakeTransport([]),
        )
        self.assertFalse(
            any("cache" in name.lower() for name in vars(client)),
            "client grew a cache attribute; check nothing persists tokens",
        )


class MultipartTests(unittest.TestCase):
    def test_fields_and_files_are_encoded_with_one_boundary(self):
        body, content_type = encode_multipart_form_data(
            fields=[("document", '{"a":1}', "application/json")],
            files=[("attachment", "inv.pdf", b"%PDF-1.4", "application/pdf")],
        )
        boundary = content_type.split("boundary=")[1]

        self.assertIn(f"--{boundary}".encode(), body)
        self.assertIn(b'name="document"', body)
        self.assertIn(b'filename="inv.pdf"', body)
        self.assertIn(b"%PDF-1.4", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_quotes_in_filenames_are_escaped(self):
        body, _ = encode_multipart_form_data(
            fields=[], files=[("a", 'in"v.pdf', b"x", "application/pdf")]
        )
        self.assertIn(b'filename="in\\"v.pdf"', body)


class ConfigTests(unittest.TestCase):
    def test_process_env_wins_over_env_file(self):
        import os

        os.environ["CARRIERS_TEST_VAR"] = "from-process"
        try:
            value = env_value("CARRIERS_TEST_VAR", values={"CARRIERS_TEST_VAR": "from-file"})
            self.assertEqual(value, "from-process")
        finally:
            del os.environ["CARRIERS_TEST_VAR"]

    def test_env_file_is_used_when_process_env_is_unset(self):
        value = env_value("CARRIERS_UNSET_VAR", values={"CARRIERS_UNSET_VAR": "from-file"})
        self.assertEqual(value, "from-file")

    def test_env_file_parsing_strips_quotes_and_comments(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
            handle.write('# comment\nA="one"\nB=\'two\'\n\nBAD_LINE\n')
            path = handle.name
        values = load_env_file(path)
        self.assertEqual(values, {"A": "one", "B": "two"})

    def test_ups_maps_test_and_sandbox_to_cie(self):
        import os

        os.environ.update(
            {
                "UPS_CLIENT_ID": "i",
                "UPS_CLIENT_SECRET": "s",
                "UPS_ENVIRONMENT": "sandbox",
            }
        )
        try:
            self.assertEqual(UPSConfig.from_env().environment, "cie")
        finally:
            for key in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ENVIRONMENT"):
                os.environ.pop(key, None)


class LoggingTests(unittest.TestCase):
    def test_a_failed_request_is_logged_with_the_carrier_message(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("carriers.test-capture")
        logger.setLevel(logging.DEBUG)
        handler = Capture()
        logger.addHandler(handler)

        transport = FakeTransport(
            [json_response(404, {"response": {"errors": [{"code": "1", "message": "nope"}]}})]
        )
        client = UPSClient(
            UPSConfig(client_id="i", client_secret="s", base_url="https://x.test"),
            transport=transport,
            logger=logger,
            retry_policy=RetryPolicy.disabled(),
        )

        with self.assertRaises(Exception):
            client.get("/a", authenticated=False)

        logger.removeHandler(handler)
        self.assertTrue(any("1: nope" in message for message in records), records)


if __name__ == "__main__":
    unittest.main()
