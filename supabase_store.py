"""Supabase-backed per-user study records.

Questions remain in the versioned JSON file. Reviews and scheduling state live in
Supabase, protected by row-level security so a signed-in user can only read and
write their own rows.
"""

from __future__ import annotations

import json
import random
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cloud_connection import CloudServiceError, request_json
from question_search import search_questions as _search_questions

ROOT = Path(__file__).parent
QUESTIONS_JSON = ROOT / "questions.json"
SKIPPED_GRADE = "skipped"
TECHNICAL_POOL = "技术题库"
NONTECH_CATEGORY = "软技能/HR"


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


class ReviewScheduleError(CloudServiceError):
    """The review is saved, so the caller must not submit it a second time."""

    def __init__(self, grade: str, cause: CloudServiceError):
        super().__init__(
            "本次作答记录已保存，但复习安排未确认更新。请勿重复提交本题；稍后查看统计或重新登录后继续。",
            kind="schedule", status=cause.status,
            write_may_have_succeeded=cause.write_may_have_succeeded,
        )
        self.grade = grade
        self.review_saved = True


class SupabaseStore:
    def __init__(self, url: str, anon_key: str, access_token: str, user_id: str):
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.token = access_token
        self.user_id = user_id
        self.questions = json.loads(QUESTIONS_JSON.read_text(encoding="utf-8"))
        self.by_id = {q["id"]: q for q in self.questions}

    def _request(self, method: str, path: str, payload=None, prefer: str | None = None):
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        try:
            req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        except ValueError:
            raise CloudServiceError("云端连接异常，请联系管理员检查 Supabase 项目状态。",
                                    kind="configuration") from None
        return request_json(req, timeout=20)

    def _reviews(self):
        return self._request("GET", "/rest/v1/reviews?select=*&order=created_at.desc")

    def _cards(self):
        return self._request("GET", "/rest/v1/card_state?select=*")

    def list_categories(self):
        counts = {}
        for q in self.questions:
            counts[q["category"]] = counts.get(q["category"], 0) + 1
        return sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    def get_question(self, qid):
        return self.by_id.get(qid)

    def search_questions(self, query, category=TECHNICAL_POOL):
        """关键词搜索使用随应用发布的题库，无需请求云端。"""
        return _search_questions(self.questions, query, category)

    @staticmethod
    def score_to_grade(score: float) -> str:
        if score >= 85: return "easy"
        if score >= 70: return "good"
        if score >= 50: return "hard"
        return "again"

    def _filtered(self, category):
        if category in (None, "全部", TECHNICAL_POOL):
            return [q for q in self.questions if q["category"] != NONTECH_CATEGORY]
        return [q for q in self.questions if q["category"] == category]

    def next_question(self, category=None, mode="due", exclude_id=None):
        qs = self._filtered(category)
        cards = {c["question_id"]: c for c in self._cards()}
        reviews = self._reviews()
        scores = {}
        for r in reviews:
            scores.setdefault(r["question_id"], []).append(float(r["score"]))
        candidates = [q for q in qs if q["id"] != exclude_id] or qs
        if mode == "wrong":
            wrong = [q for q in candidates if scores.get(q["id"]) and min(scores[q["id"]]) < 60]
            if wrong:
                return min(wrong, key=lambda q: min(scores[q["id"]]))
        if mode == "new":
            fresh = [q for q in candidates if q["id"] not in cards]
            if fresh:
                return random.choice(fresh[:20])
        if mode == "due":
            now = _now()
            due = [q for q in candidates if cards.get(q["id"], {}).get("due", "") <= now and q["id"] in cards]
            if due:
                return random.choice(due)
            fresh = [q for q in candidates if q["id"] not in cards]
            if fresh:
                return random.choice(fresh[:20])
        return random.choice(candidates) if candidates else None

    def pending_count(self, category=None):
        qs = self._filtered(category)
        cards = {c["question_id"]: c for c in self._cards()}
        scores = {}
        for r in self._reviews(): scores.setdefault(r["question_id"], []).append(float(r["score"]))
        now = _now()
        return {
            "total": len(qs),
            "new": sum(q["id"] not in cards for q in qs),
            "due": sum(q["id"] in cards and cards[q["id"]].get("due", "") <= now for q in qs),
            "wrong": sum(bool(scores.get(q["id"])) and min(scores[q["id"]]) < 60 for q in qs),
        }

    def schedule(self, question_id, grade):
        current = next((x for x in self._cards() if x["question_id"] == question_id), None) or {}
        days = {"again": 0, "hard": 1, "good": 3, "easy": 7, SKIPPED_GRADE: 2}[grade]
        due = datetime.now(timezone.utc).replace(tzinfo=None) + (timedelta(minutes=10) if days == 0 else timedelta(days=days))
        payload = {
            "user_id": self.user_id, "question_id": question_id, "due": due.isoformat(timespec="seconds"),
            "last_review": _now(), "reps": int(current.get("reps", 0)) + 1,
            "lapses": int(current.get("lapses", 0)) + (grade == "again"),
        }
        self._request("POST", "/rest/v1/card_state?on_conflict=user_id,question_id", payload,
                      "resolution=merge-duplicates,return=minimal")
        return payload

    def record_review(self, question_id, user_answer, result, elapsed_sec=0, model=""):
        grade = SKIPPED_GRADE if result.get("skipped") else self.score_to_grade(result["score"])
        payload = {
            "user_id": self.user_id, "question_id": question_id, "user_answer": user_answer,
            "score": result["score"], "grade": grade, "hit_points": result.get("hit", []),
            "miss_points": result.get("miss", []), "wrong_points": result.get("wrong", []),
            "feedback": result.get("feedback", ""), "ref_hit": result.get("coverage", 0),
            "elapsed_sec": elapsed_sec, "model": model, "created_at": _now(),
        }
        self._request("POST", "/rest/v1/reviews", payload, "return=minimal")
        try:
            self.schedule(question_id, grade)
        except CloudServiceError as exc:
            raise ReviewScheduleError(grade, exc) from None
        return grade

    def stats_overview(self):
        reviews, cards = self._reviews(), self._cards()
        scores = [float(r["score"]) for r in reviews]
        best = {}
        for r in reviews: best[r["question_id"]] = max(best.get(r["question_id"], 0), float(r["score"]))
        return {"total": len(self.questions), "learned": len(cards), "reviews": len(reviews),
                "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
                "mastered": sum(x >= 85 for x in best.values()), "streak_days": self._streak(reviews),
                "progress": round(len(cards) / len(self.questions) * 100, 1) if self.questions else 0}

    def _streak(self, reviews):
        days = sorted({r["created_at"][:10] for r in reviews}, reverse=True)
        if not days: return 0
        cursor = datetime.fromisoformat(days[0]).date()
        if (datetime.now().date() - cursor).days > 1: return 0
        n = 1
        for d in days[1:]:
            date = datetime.fromisoformat(d).date()
            if (cursor - date).days != 1: break
            n += 1; cursor = date
        return n

    def category_progress(self):
        cards = {x["question_id"] for x in self._cards()}
        reviews = self._reviews()
        out = []
        for category, total in self.list_categories():
            qids = {q["id"] for q in self.questions if q["category"] == category}
            rs = [r for r in reviews if r["question_id"] in qids]
            learned = len(qids & cards)
            out.append({"category": category, "total": total, "learned": learned,
                        "avg_score": round(sum(float(r["score"]) for r in rs)/len(rs), 1) if rs else 0,
                        "good": sum(float(r["score"]) >= 85 for r in rs),
                        "rate": round(learned/total*100, 1) if total else 0})
        return out

    def wrong_book(self, limit=300, only_unmastered=True, category=None):
        grouped = {}
        for r in self._reviews(): grouped.setdefault(r["question_id"], []).append(r)
        allowed = {q["id"] for q in self._filtered(category)}
        out = []
        for qid, rs in grouped.items():
            if qid not in allowed: continue
            scores = [float(r["score"]) for r in rs]
            if only_unmastered and min(scores) >= 60: continue
            q = self.by_id.get(qid)
            if not q: continue
            last = max(rs, key=lambda r: r["created_at"])
            out.append({"id": qid, "category": q["category"], "question": q["question"], "context": q.get("context") or {}, "minscore": min(scores), "maxscore": max(scores), "times": len(rs), "fail_times": sum(x < 60 for x in scores), "last_at": last["created_at"], "last_miss": last.get("miss_points", []), "last_feedback": last.get("feedback", "")})
        return sorted(out, key=lambda r: (r["minscore"], -r["fail_times"]))[:limit]

    def score_trend(self, days=30):
        since = (datetime.now() - timedelta(days=days)).date().isoformat()
        groups = {}
        for r in self._reviews():
            if r["created_at"][:10] >= since: groups.setdefault(r["created_at"][:10], []).append(float(r["score"]))
        return [{"d": d, "n": len(v), "avg_score": round(sum(v)/len(v), 1)} for d, v in sorted(groups.items())]

    def grade_distribution(self):
        out = {}
        for r in self._reviews(): out[r["grade"]] = out.get(r["grade"], 0) + 1
        return out

    def recent_reviews(self, limit=50):
        out = []
        for r in self._reviews()[:limit]:
            q = self.by_id.get(r["question_id"], {})
            out.append({**r, "question": q.get("question", ""), "category": q.get("category", "")})
        return out
