"""Failure cases that must stay usable and never disclose cloud response bodies."""

import io
import socket
import traceback
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cloud_connection import CloudServiceError, auth_request, request_json
from supabase_store import ReviewScheduleError, SupabaseStore


class CloudConnectionTests(unittest.TestCase):
    def setUp(self):
        self.request = urllib.request.Request("https://example.invalid/rest/v1/reviews")

    def test_dns_failure_has_safe_actionable_message(self):
        failure = urllib.error.URLError(socket.gaierror(-2, "sensitive server address"))
        with patch("cloud_connection.urllib.request.urlopen", side_effect=failure) as opener:
            with self.assertRaises(CloudServiceError) as caught:
                request_json(self.request)
        opener.assert_called_once()
        self.assertEqual(caught.exception.kind, "connection")
        self.assertIn("Supabase", str(caught.exception))
        self.assertNotIn("sensitive", str(caught.exception))

    def test_timeout_is_classified_for_both_wrapped_and_direct_errors(self):
        for failure in (TimeoutError("sensitive timeout"),
                        urllib.error.URLError(TimeoutError("sensitive timeout"))):
            with self.subTest(failure=type(failure).__name__):
                with patch("cloud_connection.urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(CloudServiceError) as caught:
                        request_json(self.request)
                self.assertEqual(caught.exception.kind, "timeout")
                self.assertIn("超时", str(caught.exception))
                self.assertNotIn("sensitive", str(caught.exception))

    def test_rest_401_requests_new_login_without_exposing_body(self):
        self._assert_http_error(401, "authentication", "重新登录")

    def test_503_text_response_does_not_require_json_or_expose_body(self):
        self._assert_http_error(503, "unavailable", "Supabase")

    def test_rate_limit_has_distinct_message(self):
        self._assert_http_error(429, "rate_limit", "频繁")

    def _assert_http_error(self, status, kind, expected):
        body = io.BytesIO(b"private-api-key and private server response")
        failure = urllib.error.HTTPError(self.request.full_url, status, "private header", {}, body)
        with patch("cloud_connection.urllib.request.urlopen", side_effect=failure):
            try:
                request_json(self.request)
            except CloudServiceError as exc:
                self.assertEqual(exc.kind, kind)
                self.assertEqual(exc.status, status)
                self.assertIn(expected, str(exc))
                self.assertNotIn("private", str(exc))
                self.assertNotIn("private", "".join(traceback.format_exception(exc)))
            else:
                self.fail("Expected safe cloud error")
        self.assertTrue(body.closed)

    def test_auth_rejected_has_safe_login_message(self):
        for status in (400, 401):
            with self.subTest(status=status):
                failure = urllib.error.HTTPError(
                    "https://example.invalid/auth/v1/token", status, "private rejection", {},
                    io.BytesIO(b"private email and password details"),
                )
                with patch("cloud_connection.urllib.request.urlopen", side_effect=failure) as opener:
                    with self.assertRaises(CloudServiceError) as caught:
                        auth_request("https://example.invalid", "fake-key", "token?grant_type=password",
                                     "someone@example.invalid", "fake-password")
                opener.assert_called_once()
                self.assertIn("登录失败", str(caught.exception))
                self.assertFalse(caught.exception.write_may_have_succeeded)
                self.assertNotIn("private", str(caught.exception))

    def test_signup_rejected_uses_registration_message(self):
        for status in (400, 401):
            with self.subTest(status=status):
                failure = urllib.error.HTTPError(
                    "https://example.invalid/auth/v1/signup", status, "private rejection", {},
                    io.BytesIO(b"private email and password details"),
                )
                with patch("cloud_connection.urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(CloudServiceError) as caught:
                        auth_request("https://example.invalid", "fake-key", "signup",
                                     "someone@example.invalid", "fake-password")
                self.assertIn("注册失败", str(caught.exception))
                self.assertNotIn("登录失败", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))

    def test_success_json_and_empty_write_response(self):
        for body, expected in ((b'[{"question_id": 1}]', [{"question_id": 1}]),
                               (b'{"access_token": "fake"}', {"access_token": "fake"}),
                               (b"", [])):
            with self.subTest(body=body):
                with patch("cloud_connection.urllib.request.urlopen", return_value=io.BytesIO(body)) as opener:
                    self.assertEqual(request_json(self.request, timeout=15), expected)
                opener.assert_called_once_with(self.request, timeout=15)

    def test_invalid_json_is_safe_and_does_not_hide_read_failure(self):
        for body in (b"private broken JSON", b"private bad UTF-8 \xff"):
            with self.subTest(body=body):
                with patch("cloud_connection.urllib.request.urlopen", return_value=io.BytesIO(body)):
                    with self.assertRaises(CloudServiceError) as caught:
                        request_json(self.request)
                self.assertEqual(caught.exception.kind, "response")
                self.assertFalse(caught.exception.write_may_have_succeeded)
                self.assertNotIn("private", str(caught.exception))

    def test_auth_non_dict_response_is_safe(self):
        with patch("cloud_connection.urllib.request.urlopen", return_value=io.BytesIO(b"[]")):
            with self.assertRaises(CloudServiceError) as caught:
                auth_request("https://example.invalid", "fake-key", "signup",
                             "someone@example.invalid", "fake-password")
        self.assertEqual(caught.exception.kind, "response")
        self.assertIn("重新登录", str(caught.exception))

    def test_connection_reset_is_safe(self):
        with patch("cloud_connection.urllib.request.urlopen", side_effect=ConnectionResetError("private server")):
            with self.assertRaises(CloudServiceError) as caught:
                request_json(self.request)
        self.assertEqual(caught.exception.kind, "connection")
        self.assertNotIn("private", str(caught.exception))

    def test_auth_request_constructor_error_is_safe(self):
        with patch("cloud_connection.urllib.request.Request", side_effect=ValueError("private URL")):
            with self.assertRaises(CloudServiceError) as caught:
                auth_request("private URL", "fake-key", "signup",
                             "someone@example.invalid", "fake-password")
        self.assertEqual(caught.exception.kind, "configuration")
        self.assertIn("管理员", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("SUPABASE_URL", str(caught.exception))

    def test_network_write_failure_is_not_retried(self):
        request = urllib.request.Request(self.request.full_url, data=b"{}", method="POST")
        with patch("cloud_connection.urllib.request.urlopen", side_effect=TimeoutError()) as opener:
            with self.assertRaises(CloudServiceError) as caught:
                request_json(request)
        opener.assert_called_once()
        self.assertTrue(caught.exception.write_may_have_succeeded)
        self.assertIn("避免重复提交", str(caught.exception))


class ReviewPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.store = SupabaseStore("https://example.invalid", "fake-key", "fake-token", "fake-user")
        self.result = {"score": 80, "feedback": "test feedback"}

    def test_saved_review_with_schedule_failure_is_distinct(self):
        with patch.object(self.store, "_request", return_value=[]) as request:
            with patch.object(self.store, "schedule", side_effect=CloudServiceError("安全连接提示")) as schedule:
                with self.assertRaises(ReviewScheduleError) as caught:
                    self.store.record_review(1, "answer", self.result)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[:2], ("POST", "/rest/v1/reviews"))
        schedule.assert_called_once_with(1, "good")
        self.assertTrue(caught.exception.review_saved)
        self.assertEqual(caught.exception.grade, "good")
        self.assertIn("记录已保存", str(caught.exception))
        self.assertIn("请勿重复提交", str(caught.exception))

    def test_data_request_constructor_error_is_safe(self):
        with patch("supabase_store.urllib.request.Request", side_effect=ValueError("private URL")):
            with patch("cloud_connection.urllib.request.urlopen") as opener:
                with self.assertRaises(CloudServiceError) as caught:
                    self.store._request("GET", "/rest/v1/reviews")
        opener.assert_not_called()
        self.assertEqual(caught.exception.kind, "configuration")
        self.assertIn("管理员", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("SUPABASE_URL", str(caught.exception))

    def test_failed_review_write_does_not_attempt_schedule(self):
        failure = CloudServiceError("状态未确认", write_may_have_succeeded=True)
        with patch.object(self.store, "_request", side_effect=failure) as request:
            with patch.object(self.store, "schedule") as schedule:
                with self.assertRaises(CloudServiceError) as caught:
                    self.store.record_review(1, "answer", self.result)
        self.assertIs(caught.exception, failure)
        self.assertNotIsInstance(caught.exception, ReviewScheduleError)
        request.assert_called_once()
        schedule.assert_not_called()

    def test_successful_review_preserves_grade_and_headers(self):
        with patch("cloud_connection.urllib.request.urlopen", side_effect=[
            io.BytesIO(b""), io.BytesIO(b"[]"), io.BytesIO(b""),
        ]) as opener:
            self.assertEqual(self.store.record_review(1, "answer", self.result), "good")
        self.assertEqual(opener.call_count, 3)
        requests = [call.args[0] for call in opener.call_args_list]
        self.assertEqual([req.get_method() for req in requests], ["POST", "GET", "POST"])
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer fake-token")
        self.assertEqual(requests[0].get_header("Apikey"), "fake-key")
        self.assertEqual(requests[0].get_header("Prefer"), "return=minimal")
        self.assertEqual(requests[2].get_header("Prefer"), "resolution=merge-duplicates,return=minimal")


if __name__ == "__main__":
    unittest.main()
