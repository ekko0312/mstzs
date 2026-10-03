"""关键词检索：本地和云端题库共用，不读取或修改背题记录。"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def search_questions(questions: Iterable[dict], query: str,
                     category: str | None = "技术题库") -> list[dict]:
    """多个空格分隔的关键词须同时命中；题干匹配优先于答案匹配。"""
    terms = list(dict.fromkeys(_normalize(query).split()))
    if not terms:
        return []

    ranked = []
    for index, question in enumerate(questions):
        q_category = question.get("category", "")
        if category in (None, "全部", "技术题库"):
            if q_category == "软技能/HR":
                continue
        elif category != "全部题库" and q_category != category:
            continue

        title = _normalize(question.get("question", ""))
        context = question.get("context") or {}
        fields = [title, q_category, question.get("answer_text", "")]
        for name in ("core_points", "rubric", "extra_points"):
            fields.extend(question.get(name) or [])
        fields.extend(context.get(name, "") for name in ("scene", "focus", "lead", "topic"))
        searchable = _normalize("\n".join(str(field) for field in fields))
        if not all(term in searchable for term in terms):
            continue

        title_hits = sum(term in title for term in terms)
        phrase_hit = " ".join(terms) in title
        ranked.append((-(title_hits == len(terms)), -title_hits, -phrase_hit,
                       index, question))

    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked]
