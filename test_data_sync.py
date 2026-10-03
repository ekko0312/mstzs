"""Verify the local feature sync without reading accounts or study databases."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import store
from supabase_store import SupabaseStore


class DataSyncTests(unittest.TestCase):
    def test_grade_boundaries_match_locally_and_in_cloud(self):
        for score, expected in (
            (0, "again"), (49.99, "again"), (50, "hard"), (69.99, "hard"),
            (70, "good"), (84.99, "good"), (85, "easy"), (100, "easy"),
        ):
            with self.subTest(score=score):
                self.assertEqual(store.score_to_grade(score), expected)
                self.assertEqual(SupabaseStore.score_to_grade(score), expected)

    def test_cloud_wrong_book_keeps_context_and_category_filter(self):
        cloud = object.__new__(SupabaseStore)
        context = {"scene": "为索引选择数据结构", "focus": "说明查找与维护成本"}
        cloud.questions = [
            {"id": "technical", "category": "Java", "question": "测试技术题", "context": context},
            {"id": "hr", "category": "软技能/HR", "question": "测试行为题"},
        ]
        cloud.by_id = {question["id"]: question for question in cloud.questions}
        reviews = [
            {"question_id": question_id, "score": 40, "created_at": "2026-10-03T00:00:00"}
            for question_id in ("technical", "hr")
        ]
        with patch.object(cloud, "_reviews", return_value=reviews):
            technical = cloud.wrong_book()
            hr = cloud.wrong_book(category="软技能/HR")
        self.assertEqual([row["id"] for row in technical], ["technical"])
        self.assertEqual(technical[0]["context"], context)
        self.assertEqual([row["id"] for row in hr], ["hr"])
        self.assertEqual(hr[0]["context"], {})

    def test_question_ids_preserve_existing_cloud_record_keys(self):
        questions = json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))
        ids = [question["id"] for question in questions]
        expected = {f"q{number:04d}" for number in range(1, 379)}
        self.assertEqual(len(ids), 378)
        self.assertEqual(len(set(ids)), 378)
        self.assertEqual(set(ids), expected)


if __name__ == "__main__":
    unittest.main()
