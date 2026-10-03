"""Cloud UI regression checks; use only synthetic credentials and mocked HTTP."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import grader
import streamlit as st

import supabase_store


APP = Path(__file__).with_name("app.py")
TEST_TEMP = APP.parent.parent / "cloud-app-test-temp"
TEST_TEMP.mkdir(parents=True, exist_ok=True)
# AppTest's from-string scratch directory is unused here. Keep it inside work/,
# avoiding the Windows sandbox's restricted mkdtemp directory cleanup.
with patch.object(tempfile, "TemporaryDirectory", return_value=SimpleNamespace(name=str(TEST_TEMP))):
    from streamlit.testing.v1 import AppTest

QUESTION = {
    "id": "test-question",
    "category": "测试分类",
    "date": "2026-10-01",
    "question": "解释测试知识点",
    "seq": 1,
    "context": {},
    "core_points": ["测试要点一", "测试要点二"],
    "rubric": ["测试要点一", "测试要点二"],
    "extra_points": [],
}
RESULT = {
    "score": 85.0,
    "coverage": 1.0,
    "hit": [{"point": "测试要点一", "evidence": "测试作答"}],
    "miss": [],
    "wrong": [],
    "feedback": "测试反馈：回答已评分。",
    "model": "mock:model",
}
ANSWER = "这是测试作答，刷新界面也应保留。"
USER = {"id": "fake-user", "token": "fake-user-token", "email": "test@example.invalid"}
FAKE_SECRETS = {
    "SUPABASE_URL": "https://fake-cloud.example.invalid",
    "SUPABASE_ANON_KEY": "fake-public-key",
}
PRIVATE_ERROR = "private-error-detail-that-must-not-appear"


class JsonResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.data).encode("utf-8")


class CloudAppHarness(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.fail_reads = False
        self.fail_writes = False
        self.fail_auth = False
        self.fail_after_schedule = False
        self.requests = []
        self.stack.enter_context(patch("streamlit.secrets", FAKE_SECRETS))
        self.stack.enter_context(patch.dict("os.environ", {
            "APP_PASSWORD": "", "SUPABASE_URL": "", "SUPABASE_ANON_KEY": "",
            "AI_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "",
            "DASHSCOPE_API_KEY": "", "ZHIPU_API_KEY": "",
            "MIMO_API_KEY": "", "CUSTOM_API_KEY": "",
        }))
        self.stack.enter_context(patch.object(grader, "read_env", return_value={}))
        self.stack.enter_context(patch.object(grader, "load_api_key", return_value=""))
        self.grade = self.stack.enter_context(patch.object(grader, "grade", return_value=RESULT.copy()))
        self.stack.enter_context(patch.object(supabase_store, "QUESTIONS_JSON", Mock(
            read_text=Mock(return_value=json.dumps([QUESTION], ensure_ascii=False)),
        )))
        # Catch both default urllib and custom proxy-free opener transports.
        self.stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=self.http))
        self.stack.enter_context(patch.object(urllib.request.OpenerDirector, "open", side_effect=self.http))
        st.cache_resource.clear()

    def http(self, request, *_args, **_kwargs):
        self.assertIsInstance(request, urllib.request.Request)
        self.assertTrue(request.full_url.startswith(FAKE_SECRETS["SUPABASE_URL"]))
        method = request.get_method()
        url = request.full_url
        self.requests.append((method, url, request.data))
        if ((self.fail_auth and "/auth/v1/" in url)
                or (self.fail_reads and method == "GET")
                or (self.fail_writes and method == "POST" and "/rest/v1/reviews" in url)):
            raise urllib.error.URLError(socket.gaierror(-2, PRIVATE_ERROR))
        if "/auth/v1/" in url:
            return JsonResponse({"access_token": USER["token"], "user": {"id": USER["id"], "email": USER["email"]}})
        if self.fail_after_schedule and method == "POST" and "/rest/v1/card_state" in url:
            self.fail_reads = True
        return JsonResponse([])

    def app(self, signed_in=False):
        app = AppTest.from_file(str(APP), default_timeout=30)
        if signed_in:
            app.session_state["cloud_user"] = USER.copy()
        return app

    def button(self, app, label):
        return next(button for button in app.button if button.label == label)

    def rendered(self, app):
        text = []
        for kind in ("error", "warning", "caption", "markdown", "success", "info"):
            text.extend(str(element.value) for element in getattr(app, kind))
        return "\n".join(text)

    def assert_safe(self, app):
        self.assertEqual(len(app.exception), 0, self.rendered(app))
        self.assertNotIn(PRIVATE_ERROR, self.rendered(app))
        self.assertNotIn(USER["token"], self.rendered(app))
        self.assertNotIn(FAKE_SECRETS["SUPABASE_ANON_KEY"], self.rendered(app))


class CloudAppTests(CloudAppHarness):
    def test_login_dns_failure_shows_safe_error_without_traceback(self):
        self.fail_auth = True
        app = self.app().run()
        app.text_input(key="login_email").set_value(USER["email"])
        app.text_input(key="login_password").set_value("fake-password")
        self.button(app, "登录").click().run()
        self.assert_safe(app)
        self.assertGreater(len(app.error), 0)
        self.assertIn("云端", self.rendered(app))
        self.assertNotIn("cloud_user", app.session_state)
        self.assertFalse(any(method == "GET" for method, _, _ in self.requests))

    def test_signed_in_read_failure_offers_recovery_without_fake_zero_progress(self):
        self.fail_reads = True
        app = self.app(signed_in=True).run()
        self.assert_safe(app)
        self.assertIn("重试连接", [button.label for button in app.button])
        self.assertIn("重新登录", [button.label for button in app.button])
        self.assertIn("不会", self.rendered(app))
        self.assertNotIn("整体进度 0", self.rendered(app))
        self.assertNotIn("总进度 0", self.rendered(app))
        self.assertEqual(len(app.get("progress")), 0)
        self.assertNotIn("已背 / 共", self.rendered(app))
        self.assertNotIn("错题集是空的", self.rendered(app))

    def test_failed_review_write_preserves_grade_and_does_not_retry_insert(self):
        app = self.app(signed_in=True).run()
        self.assert_safe(app)
        app.text_area[0].input(ANSWER).run()
        self.fail_writes = True
        self.button(app, "提交判分").click().run()
        self.assert_safe(app)
        self.assertEqual(app.session_state["answer_text"], ANSWER)
        self.assertEqual(app.session_state["result"]["score"], RESULT["score"])
        self.assertEqual(app.session_state["session_done"], 1)
        self.assertEqual(app.session_state["session_scores"], [RESULT["score"]])
        self.assertIn("评分已保留", self.rendered(app))
        self.assertIn(RESULT["feedback"], self.rendered(app))
        app.run()
        self.assert_safe(app)
        self.grade.assert_called_once_with(
            QUESTION["question"], QUESTION["rubric"], ANSWER,
            extra_points=QUESTION["extra_points"],
        )
        review_posts = [request for request in self.requests if request[0] == "POST" and "/rest/v1/reviews" in request[1]]
        self.assertEqual(len(review_posts), 1, "Uncertain review inserts must not be retried automatically")
        self.assertEqual(json.loads(review_posts[0][2])["user_answer"], ANSWER)

    def test_sidebar_disconnect_preserves_answer_and_retry_restores_editor(self):
        app = self.app(signed_in=True).run()
        self.assert_safe(app)
        original_key = app.text_area[0].key
        app.text_area[0].input(ANSWER).run()
        self.fail_reads = True
        app.run()
        self.assert_safe(app)
        self.assertIn("本次作答", self.rendered(app))
        self.assertIn("保留", self.rendered(app))
        self.assertEqual(app.session_state["answer_text"], ANSWER)
        self.assertEqual(app.text_area[0].value, ANSWER)
        self.fail_reads = False
        self.button(app, "重试连接").click().run()
        self.assert_safe(app)
        self.assertEqual(app.text_area[0].key, original_key)
        self.assertEqual(app.text_area[0].value, ANSWER)
        self.assertEqual(app.session_state["answer_text"], ANSWER)
        self.assertEqual(app.session_state["session_done"], 0)
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))

    def test_disconnect_loading_next_after_giveup_keeps_existing_answer_widget(self):
        app = self.app(signed_in=True).run()
        self.assert_safe(app)
        app.text_area[0].input(ANSWER).run()
        self.button(app, "不会，看答案").click().run()
        self.assert_safe(app)
        self.fail_after_schedule = True
        self.button(app, "我记住了，下一题 →").click().run()
        self.assert_safe(app)
        self.assertIn("本次作答", self.rendered(app))
        self.assertIn("重试连接", [button.label for button in app.button])
        self.assertEqual(len(app.text_area), 1)
        self.assertEqual(app.text_area[0].value, ANSWER)
        self.assertEqual(app.session_state["answer_text"], ANSWER)
        self.assertEqual(app.session_state["current"]["id"], QUESTION["id"])
        review_posts = [request for request in self.requests if request[0] == "POST" and "/rest/v1/reviews" in request[1]]
        self.assertEqual(len(review_posts), 1)
        self.assertEqual(json.loads(review_posts[0][2])["user_answer"], ANSWER)


if __name__ == "__main__":
    unittest.main()
