"""Grading synchronization checks; credentials and AI responses are synthetic."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

import grader
import streamlit as st


CONFIG = {
    "name": "deepseek",
    "label": "DeepSeek",
    "base_url": "https://ai.example.invalid/v1",
    "model": "fake-model",
    "api_key": "fake-api-key",
}
RESULT = {
    "score": 95,
    "coverage": 1,
    "hit": [{"point": "4", "evidence": "4"}],
    "miss": [],
    "wrong": [],
    "feedback": "本题无具体参考答案，采用 AI 独立判断。回答正确。",
}


class GradingSyncTests(unittest.TestCase):
    def ai_grader(self):
        with patch.object(grader, "provider_config", return_value=CONFIG.copy()):
            return grader.Grader()

    def test_no_reference_uses_ai_and_passes_background_separately(self):
        ai = self.ai_grader()
        with patch.object(ai, "_call", return_value=json.dumps(RESULT)) as call:
            result = ai.grade("2+2 等于几？", [], "4", retries=0,
                              extra_points=["只需简短回答"])
        self.assertEqual(result["score"], 95)
        system, user, model = call.call_args.args
        self.assertIn("本题评分要点为空，必须采用上述独立评分", system)
        self.assertIn("不要因为题库缺答案而给候选人零分", system)
        self.assertIn("（无具体参考答案）", user)
        self.assertIn("# 补充说明", user)
        self.assertIn("只需简短回答", user)
        self.assertEqual(model, "fake-model")

    def test_normal_reference_keeps_rubric_as_primary_baseline(self):
        ai = self.ai_grader()
        with patch.object(ai, "_call", return_value=json.dumps(RESULT)) as call:
            ai.grade("2+2 等于几？", ["  等于4  ", "", None], "4", retries=0)
        system, user, _model = call.call_args.args
        self.assertIn("本题优先采用题库要点评分", system)
        self.assertIn("1. 等于4", user)
        self.assertNotIn("2.", user)

    def test_top_level_grade_forwards_extra_points_to_ai(self):
        with patch.object(grader, "load_api_key", return_value="fake-api-key"), \
                patch.object(grader, "provider_config", return_value=CONFIG.copy()), \
                patch.object(grader.Grader, "_call", return_value=json.dumps(RESULT)) as call:
            result = grader.grade("2+2 等于几？", [], "4", extra_points=["数学追问"])
        self.assertEqual(result["score"], 95)
        self.assertIn("数学追问", call.call_args.args[1])

    def test_missing_key_and_reference_do_not_fabricate_zero_score(self):
        with patch.object(grader, "load_api_key", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "本次不记录分数"):
                grader.grade("2+2 等于几？", [], "4")

    def test_blank_reference_also_requires_ai(self):
        with self.assertRaisesRegex(RuntimeError, "需要 AI 独立判断"):
            grader.grade_offline(["", "  ", None], "4")

    def test_normal_rubric_retains_offline_grading(self):
        result = grader.grade_offline(["Java 支持重写和重载"], "Java 支持重写和重载")
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["coverage"], 1)
        self.assertEqual(result["model"], "offline")

    def test_ungradable_ai_response_is_an_error_without_score(self):
        ai = self.ai_grader()
        response = {"ungradable": True, "feedback": "缺少题目上下文"}
        with patch.object(ai, "_call", return_value=json.dumps(response)):
            with self.assertRaisesRegex(RuntimeError, "缺少题目上下文"):
                ai.grade("这个呢？", [], "是", retries=0)

    def test_incomplete_ai_response_does_not_default_to_zero(self):
        ai = self.ai_grader()
        with patch.object(ai, "_call", return_value='{"feedback": "回答不错"}'):
            with self.assertRaisesRegex(RuntimeError, "AI 未返回完整评分"):
                ai.grade("2+2 等于几？", [], "4", retries=0)

    def test_cloud_secrets_supply_ai_config_without_local_env(self):
        secrets = {"AI_PROVIDER": "custom", "AI_MODEL": "cloud-model",
                   "AI_BASE_URL": "https://ai.example.invalid/v1",
                   "CUSTOM_API_KEY": "fake-cloud-key"}
        with patch.dict(os.environ, {}, clear=True), patch.object(st, "secrets", secrets), \
                patch.object(grader, "ENV_FILE", Mock(exists=Mock(return_value=False))):
            config = grader.provider_config()
        self.assertEqual(config["name"], "custom")
        self.assertEqual(config["model"], "cloud-model")
        self.assertEqual(config["base_url"], "https://ai.example.invalid/v1")
        self.assertEqual(config["api_key"], "fake-cloud-key")

    def test_local_env_and_process_environment_override_cloud_defaults(self):
        env_file = Mock(exists=Mock(return_value=True), read_text=Mock(
            return_value="AI_MODEL=local-model\nDEEPSEEK_API_KEY=fake-local-key\n"))
        with patch.dict(os.environ, {"AI_MODEL": "process-model"}, clear=True), \
                patch.object(st, "secrets", {"AI_MODEL": "cloud-model",
                                           "DEEPSEEK_API_KEY": "fake-cloud-key"}), \
                patch.object(grader, "ENV_FILE", env_file):
            config = grader.read_env()
        self.assertEqual(config["AI_MODEL"], "process-model")
        self.assertEqual(config["DEEPSEEK_API_KEY"], "fake-local-key")

    def test_missing_cloud_secrets_do_not_break_local_configuration(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(st, "secrets", Mock(get=Mock(side_effect=RuntimeError("no secrets")))), \
                patch.object(grader, "ENV_FILE", Mock(exists=Mock(return_value=False))):
            self.assertEqual(grader.read_env(), {})


if __name__ == "__main__":
    unittest.main()
