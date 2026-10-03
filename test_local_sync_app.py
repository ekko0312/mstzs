"""Check the local feature sync through the cloud UI with synthetic data only."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import supabase_store

from test_cloud_app import ANSWER, QUESTION, CloudAppHarness


TECH_QUESTION = {
    **QUESTION,
    "id": "mysql-question",
    "category": "数据库",
    "seq": 1,
    "question": "为什么选择 B+树？",
    "context": {"scene": "为 MySQL 索引选择数据结构", "focus": "说明范围查询与节点结构"},
    "rubric": ["非叶子节点只保存索引", "叶子节点按顺序连接"],
    "core_points": ["索引结构", "非叶子节点只保存索引，叶子节点按顺序连接，适合范围查询。"],
    "extra_points": ["这条补充说明也应显示并传给判分器。"],
}
JAVA_QUESTION = {
    **QUESTION,
    "id": "java-question",
    "category": "Java",
    "seq": 2,
    "question": "HashMap 如何处理冲突？",
    "context": {"lead": "正在讨论 Java 集合", "topic": "Java 集合机制"},
    "core_points": ["数组和链表保存元素，冲突达到一定条件后采用红黑树。"],
    "rubric": ["数组和链表保存元素"],
}
HR_QUESTION = {
    **QUESTION,
    "id": "hr-question",
    "category": "软技能/HR",
    "seq": 0,
    "question": "介绍你参与 MySQL 项目的合作方式",
    "core_points": ["描述分工与沟通方式，说明自己的贡献和复盘。"],
}


class LocalSyncAppTests(CloudAppHarness):
    def setUp(self):
        super().setUp()
        # Put HR first and make selection deterministic, so missing technical
        # filtering cannot pass merely because random selection picked a tech q.
        self.stack.enter_context(patch.object(supabase_store, "QUESTIONS_JSON", Mock(
            read_text=Mock(return_value=json.dumps(
                [HR_QUESTION, TECH_QUESTION, JAVA_QUESTION], ensure_ascii=False,
            )),
        )))
        self.stack.enter_context(patch.object(supabase_store.random, "choice", side_effect=lambda candidates: candidates[0]))

    def radio(self, app, label):
        return next(radio for radio in app.radio if radio.label == label)

    def assert_no_write_or_grade(self):
        self.grade.assert_not_called()
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))

    def search(self, app, query):
        self.radio(app, "导航").set_value("查题").run()
        self.assert_safe(app)
        app.text_input(key="question_search_query").set_value(query)
        self.button(app, "搜索").click().run()
        self.assert_safe(app)

    def test_default_pool_excludes_nontechnical_questions(self):
        app = self.app(signed_in=True).run()
        self.assert_safe(app)
        self.assertEqual(app.selectbox(key="cat_filter").value, "技术题库")
        self.assertEqual(app.session_state["current"]["id"], TECH_QUESTION["id"])
        self.assertIn("当前题库 **2** 道", self.rendered(app))
        self.assertIn("非技术题只在", self.rendered(app))
        self.assertNotIn(HR_QUESTION["question"], self.rendered(app))
        self.assert_no_write_or_grade()

    def test_nontechnical_pool_requires_explicit_choice(self):
        app = self.app(signed_in=True).run()
        app.selectbox(key="cat_filter").set_value("软技能/HR").run()
        self.assert_safe(app)
        self.assertEqual(app.session_state["current"]["id"], HR_QUESTION["id"])
        self.assertIn("当前题库 **1** 道", self.rendered(app))
        self.assertIn(HR_QUESTION["question"], self.rendered(app))
        app.selectbox(key="cat_filter").set_value("技术题库").run()
        self.assert_safe(app)
        self.assertNotEqual(app.session_state["current"]["category"], "软技能/HR")
        self.assert_no_write_or_grade()

    def test_nontechnical_selection_and_answer_survive_disconnect(self):
        app = self.app(signed_in=True).run()
        app.selectbox(key="cat_filter").set_value("软技能/HR").run()
        app.text_area[0].input(ANSWER).run()
        self.fail_reads = True
        app.run()
        self.assert_safe(app)
        self.assertEqual(app.session_state["answer_text"], ANSWER)
        self.fail_reads = False
        self.button(app, "重试连接").click().run()
        self.assert_safe(app)
        self.assertEqual(app.selectbox(key="cat_filter").value, "软技能/HR")
        self.assertEqual(app.session_state["current"]["id"], HR_QUESTION["id"])
        self.assertEqual(app.text_area[0].value, ANSWER)
        self.assert_no_write_or_grade()

    def test_search_context_displays_reference_answer_without_grading(self):
        app = self.app(signed_in=True).run()
        self.search(app, "mysql")
        self.assertEqual(app.selectbox(key="question_search_category").value, "技术题库")
        self.assertEqual(app.selectbox(key="question_search_selected").value, TECH_QUESTION["id"])
        self.assertIn("找到 **1** 道题", self.rendered(app))
        for text in (
            TECH_QUESTION["question"], TECH_QUESTION["context"]["scene"],
            TECH_QUESTION["context"]["focus"], TECH_QUESTION["core_points"][1],
            TECH_QUESTION["extra_points"][0], "answer-layout",
        ):
            self.assertIn(text, self.rendered(app))
        self.assertNotIn(HR_QUESTION["question"], self.rendered(app))
        self.assert_no_write_or_grade()

    def test_search_all_pools_can_find_nontechnical_answer(self):
        app = self.app(signed_in=True).run()
        self.search(app, "mysql")
        app.selectbox(key="question_search_category").set_value("全部题库").run()
        self.assert_safe(app)
        self.assertIn("找到 **2** 道题", self.rendered(app))
        app.selectbox(key="question_search_selected").set_value(HR_QUESTION["id"]).run()
        self.assert_safe(app)
        self.assertIn(HR_QUESTION["question"], self.rendered(app))
        self.assertIn(HR_QUESTION["core_points"][0], self.rendered(app))
        self.assert_no_write_or_grade()

    def test_search_answer_keywords_and_no_match_feedback(self):
        app = self.app(signed_in=True).run()
        self.search(app, "叶子 节点")
        self.assertEqual(app.selectbox(key="question_search_selected").value, TECH_QUESTION["id"])
        app.text_input(key="question_search_query").set_value("不存在的测试关键词").run()
        self.assert_safe(app)
        self.assertIn("没有找到匹配的题目", self.rendered(app))
        self.assertNotIn("question_search_selected", [select.key for select in app.selectbox])
        self.assert_no_write_or_grade()

    def test_context_and_reference_display_in_practice_and_context_passed_to_grade(self):
        app = self.app(signed_in=True).run()
        self.assert_safe(app)
        self.assertIn(TECH_QUESTION["context"]["scene"], self.rendered(app))
        self.assertIn(TECH_QUESTION["context"]["focus"], self.rendered(app))
        self.button(app, "不会，看答案").click().run()
        self.assert_safe(app)
        self.assertIn(TECH_QUESTION["core_points"][1], self.rendered(app))
        self.assertIn(TECH_QUESTION["extra_points"][0], self.rendered(app))
        app.text_area[0].input(ANSWER).run()
        self.button(app, "提交判分").click().run()
        self.assert_safe(app)
        self.grade.assert_called_once_with(
            f"（题目场景：{TECH_QUESTION['context']['scene']}）{TECH_QUESTION['question']}",
            TECH_QUESTION["rubric"], ANSWER, extra_points=TECH_QUESTION["extra_points"],
        )
        self.assertEqual(app.session_state["session_done"], 1)
        self.assertIn(TECH_QUESTION["core_points"][1], self.rendered(app))

    def test_question_without_reference_points_can_receive_independent_grade(self):
        empty_question = {
            **TECH_QUESTION, "rubric": [], "core_points": [], "extra_points": [],
        }
        app = self.app(signed_in=True)
        app.session_state["current"] = empty_question
        app.run()
        self.assert_safe(app)
        app.text_area[0].input(ANSWER).run()
        self.button(app, "提交判分").click().run()
        self.assert_safe(app)
        self.grade.assert_called_once_with(
            f"（题目场景：{TECH_QUESTION['context']['scene']}）{TECH_QUESTION['question']}",
            [], ANSWER, extra_points=[],
        )
        self.assertEqual(app.session_state["session_done"], 1)
        self.assertIn("本题暂无具体参考答案", self.rendered(app))


if __name__ == "__main__":
    unittest.main()
