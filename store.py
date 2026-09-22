# -*- coding: utf-8 -*-
"""数据层：SQLite 建表 / 题库导入 / 复习记录 / 错题集 / 进度统计。

表设计
------
questions     题库（题目 + 参考要点 rubric + 分类）
reviews       每一次作答记录（我的答案 / AI 评分明细 / 用时）
card_state    每道题的 FSRS 记忆状态（调度用）
"""

import json
import random as _random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "trainer.db"
QUESTIONS_JSON = ROOT / "questions.json"


# ------------------------------------------------------------ 时间统一走 UTC
#
# ⚠️ 这里曾经踩过一个坑：fsrs 的 Scheduler 返回的 card.due 是 **UTC**
# （带 +00:00 时区），而查询到期题时用的是 datetime.now() —— 本地时间（UTC+8）。
# 两者直接做字符串比较，东八区下 due 永远"早于"现在，
# 结果就是【刚答完的题立刻又被判定为已到期】，下一题永远回到刚做过的那道。
#
# 规矩：凡是写进 card_state.due / 用来和 due 比较的时间，一律用 UTC，
# 且都格式化成不带时区后缀的统一字符串（naive UTC ISO），
# 避免 "+00:00" 和不带时区的字符串混着比较。

def _utc_now_iso() -> str:
    """当前 UTC 时间（naive ISO，秒精度），与 fsrs 的 due 对齐。"""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _to_utc_naive(iso: str | None) -> str | None:
    """把任意 ISO 时间字符串规整成 naive UTC ISO。

    兼容三种输入：带时区的（2026-01-01T10:00:00+00:00）、
    不带时区的本地时间（历史数据）、以及空值。
    按本地时区解释不带时区的历史值，再换算成 UTC。
    """
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        # 历史数据认为是本地时间写进去的
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id            TEXT PRIMARY KEY,
    date          TEXT NOT NULL,
    question      TEXT NOT NULL,
    answer_text   TEXT NOT NULL,      -- 参考答案全文（要点拼接，展示用）
    rubric        TEXT NOT NULL,      -- JSON: 打分点列表
    extra_points  TEXT NOT NULL,      -- JSON: 补充说明（不计分，给 AI 参考）
    category      TEXT NOT NULL,
    seq           INTEGER NOT NULL    -- 文档原始顺序
);
CREATE INDEX IF NOT EXISTS idx_q_cat ON questions(category);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id   TEXT NOT NULL,
    user_answer   TEXT NOT NULL,
    score         REAL NOT NULL,      -- 0~100
    grade         TEXT NOT NULL,      -- again/hard/good/easy
    hit_points    TEXT NOT NULL,      -- JSON
    miss_points   TEXT NOT NULL,      -- JSON
    wrong_points  TEXT NOT NULL,      -- JSON: 答错/不准确的表述
    feedback      TEXT NOT NULL,      -- AI 总评与改进建议
    ref_hit       REAL NOT NULL,      -- 要点覆盖率 0~1
    elapsed_sec   INTEGER NOT NULL DEFAULT 0,
    model         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_r_q ON reviews(question_id);
CREATE INDEX IF NOT EXISTS idx_r_time ON reviews(created_at);

CREATE TABLE IF NOT EXISTS card_state (
    question_id    TEXT PRIMARY KEY,
    stability      REAL NOT NULL DEFAULT 0,
    difficulty     REAL NOT NULL DEFAULT 0,
    due            TEXT,              -- ISO 时间，NULL=未学
    last_review    TEXT,
    reps           INTEGER NOT NULL DEFAULT 0,   -- 累计作答次数
    lapses         INTEGER NOT NULL DEFAULT 0,   -- 累计遗忘次数
    state          INTEGER NOT NULL DEFAULT 0,   -- fsrs State
    step           INTEGER,                      -- 学习步
    best_score     REAL NOT NULL DEFAULT 0,      -- 历史最高分
    last_score     REAL                           -- 最近一次得分
);
"""


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def import_questions(force: bool = False) -> int:
    """把 questions.json 导入 questions 表。force=True 时清空重导（保留复习记录）。"""
    init_db()
    data = json.loads(QUESTIONS_JSON.read_text(encoding="utf-8"))
    with conn() as c:
        if force:
            c.execute("DELETE FROM questions")
        cur = c.execute("SELECT COUNT(*) n FROM questions")
        if cur.fetchone()["n"] > 0 and not force:
            return 0
        rows = []
        for i, q in enumerate(data, 1):
            answer_text = "\n".join(q["core_points"] + q["extra_points"])
            rows.append((
                q["id"], q["date"], q["question"], answer_text,
                json.dumps(q["rubric"], ensure_ascii=False),
                json.dumps(q["extra_points"], ensure_ascii=False),
                q["category"], i,
            ))
        c.executemany(
            "INSERT OR REPLACE INTO questions"
            "(id,date,question,answer_text,rubric,extra_points,category,seq)"
            " VALUES(?,?,?,?,?,?,?,?)", rows,
        )
        return len(rows)


# ------------------------------------------------------------ FSRS 调度

# fsrs 包的 API 在不同版本略有差异，这里做一层薄封装 + 纯 Python 兜底实现，
# 保证「没装 fsrs 也能跑」。
try:
    from fsrs import Scheduler, Card, Rating, State  # type: ignore

    _HAS_FSRS = True
except Exception:  # pragma: no cover
    _HAS_FSRS = False

    class Rating:  # type: ignore
        Again, Hard, Good, Easy = 1, 2, 3, 4


# 分数 -> FSRS 评级 的映射阈值
#   >=85  → Easy（答得完整，间隔拉长）
#   >=70  → Good
#   >=50  → Hard（有遗漏，短间隔重来）
#   < 50  → Again（基本没答对）
GRADE_THRESHOLDS = ((85, "easy"), (70, "good"), (50, "hard"), (0, "again"))

# 「看了答案才过」这种跳过，单独给一个评级。
# 不能复用 again —— again 会被 FSRS 排到 ~1 分钟后，一分钟后这题又变成"到期题"，
# 于是每次点「下一题」都优先弹回它，看起来就像卡死在同一道题上。
# skipped 的语义是"今天先跳过，隔几天再来"，所以固定给一个较长的间隔。
SKIPPED_GRADE = "skipped"
SKIPPED_DAYS = 2


def score_to_grade(score: float) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "again"


def _simple_next(due_prev: str | None, grade: str, reps: int) -> tuple[str, float, float]:
    """FSRS 兜底：简化的间隔计算（SM-2 风格）。

    返回 (下次到期ISO, stability, difficulty)

    注意：和 fsrs 分支一样必须用 UTC，否则查询端（UTC）会比出 8 小时的差，
    刚答完的题会立刻又被当成到期题。
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    intervals = {"again": 0, "hard": 1, "good": 3, "easy": 7}
    base = intervals[grade]
    if base == 0:
        step = timedelta(minutes=10)
        return (now + step).isoformat(timespec="seconds"), 0.5, 7.0
    # 每连续答对一次，间隔按 easy/good/hard 放大
    mult = {"hard": 1.6, "good": 2.2, "easy": 3.0}[grade]
    days = max(base, round(base * (mult ** max(0, reps - 1)))) if reps else base
    days = min(days, 180)
    stability = days * (1.4 if grade == "easy" else 1.0)
    diff = {"hard": 7.5, "good": 6.0, "easy": 4.5}[grade]
    return (now + timedelta(days=days)).isoformat(timespec="seconds"), stability, diff


def schedule(question_id: str, grade: str) -> dict:
    """根据评级更新记忆状态，返回新的调度结果。"""
    with conn() as c:
        row = c.execute(
            "SELECT * FROM card_state WHERE question_id=?", (question_id,)
        ).fetchone()

        if row is None:
            stability, difficulty, reps = 0.0, 0.0, 0
            lapses, state, step = 0, 0, None
        else:
            stability = row["stability"]
            difficulty = row["difficulty"]
            reps = row["reps"]
            lapses = row["lapses"]
            state = row["state"]
            step = row["step"]

        if grade == "again":
            lapses += 1

        # 「跳过」不走 FSRS：直接给一个固定间隔，避免 review_card 把它排到 1 分钟后
        if grade == SKIPPED_GRADE:
            due_iso = (datetime.now(timezone.utc).replace(tzinfo=None)
                       + timedelta(days=SKIPPED_DAYS)).isoformat(timespec="seconds")
            reps += 1
            c.execute("""
                INSERT INTO card_state
                  (question_id,stability,difficulty,due,last_review,reps,lapses,state,step)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(question_id) DO UPDATE SET
                  due=excluded.due, last_review=excluded.last_review,
                  reps=excluded.reps
            """, (question_id, stability or 1.0, difficulty or 6.0, due_iso,
                  _utc_now_iso(), reps, lapses, state if state is not None else 0, step))
            return {"due": due_iso, "stability": stability, "difficulty": difficulty,
                    "skipped": True}

        if _HAS_FSRS:
            try:
                sched = Scheduler()
                if row is None:
                    card = Card()
                else:
                    card = Card(
                        card_id=None,
                        state=State(state),
                        step=step,
                        stability=stability or None,
                        difficulty=difficulty or None,
                        due=datetime.fromisoformat(row["due"]) if row["due"] else None,
                        last_review=(datetime.fromisoformat(row["last_review"])
                                     if row["last_review"] else None),
                    )
                rating = {
                    "again": Rating.Again, "hard": Rating.Hard,
                    "good": Rating.Good, "easy": Rating.Easy,
                }[grade]
                card, _ = sched.review_card(card, rating)
                # fsrs 给的是带时区的 UTC，统一成 naive UTC，和查询端保持一致
                due_iso = _to_utc_naive(card.due.isoformat())
                stability = float(card.stability or 0)
                difficulty = float(card.difficulty or 0)
                state = int(card.state)
                step = card.step
            except Exception:
                due_iso, stability, difficulty = _simple_next(None, grade, reps)
                state, step = 0, None
        else:
            due_iso, stability, difficulty = _simple_next(None, grade, reps)

        reps += 1
        c.execute("""
            INSERT INTO card_state
              (question_id,stability,difficulty,due,last_review,reps,lapses,state,step)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(question_id) DO UPDATE SET
              stability=excluded.stability, difficulty=excluded.difficulty,
              due=excluded.due, last_review=excluded.last_review,
              reps=excluded.reps, lapses=excluded.lapses,
              state=excluded.state, step=excluded.step
        """, (question_id, stability, difficulty, due_iso,
              _utc_now_iso(), reps, lapses, state, step))

    return {"due": due_iso, "stability": stability, "difficulty": difficulty}


def record_review(question_id: str, user_answer: str, result: dict,
                  elapsed_sec: int = 0, model: str = "") -> str:
    """写入一条作答记录并更新调度。返回 grade。

    result["skipped"] = True 表示"看了答案才过"，走 SKIPPED_GRADE
    （固定隔几天再来），而不是按 0 分判成 again（1 分钟后又会弹回来）。
    """
    if result.get("skipped"):
        grade = SKIPPED_GRADE
    else:
        grade = score_to_grade(result["score"])
    with conn() as c:
        c.execute("""
            INSERT INTO reviews
              (question_id,user_answer,score,grade,hit_points,miss_points,
               wrong_points,feedback,ref_hit,elapsed_sec,model,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            question_id, user_answer, result["score"], grade,
            json.dumps(result.get("hit", []), ensure_ascii=False),
            json.dumps(result.get("miss", []), ensure_ascii=False),
            json.dumps(result.get("wrong", []), ensure_ascii=False),
            result.get("feedback", ""), result.get("coverage", 0.0),
            elapsed_sec, model, datetime.now().isoformat(timespec="seconds"),
        ))
    # 错题集的"最低分"判定不应该把"跳过"算成错题，所以跳过时记一个中性分
    schedule(question_id, grade)
    return grade


# ------------------------------------------------------------ 取题


def _pick_new(c, cat_clause: str, ex_sql: str, args: list) -> dict | None:
    """挑一道「还没背过」的新题。

    ⚠️ 别改回 `ORDER BY q.seq LIMIT 1`。
    那样只要没有到期题，每次新开会话的第一题都会固定是题库里
    第一道没背过的题（因为 seq 最小的那道是确定的），
    用户感受就是"怎么老是同一道题"。

    改成：在【最早的若干道新题】里随机取一道 —— 既保持了大致顺着
    题库顺序推进（不会一上来就跳到第 300 题），又不会固定。
    """
    sql = (f"SELECT q.* FROM questions q LEFT JOIN card_state s "
           f"ON q.id=s.question_id WHERE s.question_id IS NULL"
           f"{cat_clause}{ex_sql} ORDER BY q.seq LIMIT 20")
    rows = c.execute(sql, args).fetchall()
    if not rows:
        return None
    return _row_to_q(_random.choice(rows))

def get_question(qid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    return _row_to_q(r) if r else None


def _row_to_q(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["rubric"] = json.loads(d["rubric"])
    d["extra_points"] = json.loads(d["extra_points"])
    return d


def list_categories() -> list[tuple[str, int]]:
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT category, COUNT(*) n FROM questions GROUP BY category ORDER BY n DESC"
        ).fetchall()
    return [(r["category"], r["n"]) for r in rows]


def next_question(category: str | None = None, mode: str = "due",
                  exclude_id: str | None = None) -> dict | None:
    """取下一道题。

    mode:
      due     —— 优先取到期的复习题（FSRS），没有则取新题
      new     —— 只取没背过的新题
      wrong   —— 只取错题（历史最低分 < 60）
      random  —— 随机抽（含新题）

    exclude_id:
      当前正在做的题号。必须传，否则在「这题还没产生作答记录」的情况下
      （比如点了"不会，看答案"、或第一次打开），查询会一次次返回同一道题，
      表现就是"切不了下一题"。
      排除后如果实在没有别的题可给（例如题库只剩这一道），则退回原题。
    """
    init_db()
    # due 存的是 UTC，比较也必须用 UTC（用本地时间会差 8 小时，
    # 导致刚答完的题立刻又被判定为到期）
    now = _utc_now_iso()
    cat_clause = " AND q.category = ? " if category and category != "全部" else ""
    cat_args = [category] if cat_clause else []
    order_clause = " ORDER BY q.seq"

    # 排除当前题：SQL 片段 + 绑定参数（放在 cat 参数之前）
    def ex_sql() -> str:
        return " AND q.id != ? " if exclude_id else ""

    def ex_args() -> list:
        return [exclude_id] if exclude_id else []

    def ex_args_tail() -> list:
        return cat_args + ex_args()

    with conn() as c:
        if mode == "new":
            r = _pick_new(c, cat_clause, ex_sql(), ex_args_tail())
            if r is not None:
                return r
            mode = "random"      # 新题背完了，退回随机

        if mode == "wrong":
            sql = (f"SELECT q.* FROM questions q JOIN ("
                   f"  SELECT question_id, MIN(score) minscore, MAX(created_at) lastat"
                   f"  FROM reviews GROUP BY question_id HAVING minscore < 60"
                   f") w ON q.id=w.question_id WHERE 1=1{cat_clause}{ex_sql()}"
                   f" ORDER BY w.minscore ASC, w.lastat DESC LIMIT 1")
            r = c.execute(sql, ex_args_tail()).fetchone()
            if r:
                return _row_to_q(r)

        if mode == "due":
            # 优先取到期的复习题。
            #
            # 这里踩过两次坑，务必别改回简单写法：
            #
            # 坑 A（原版 `ORDER BY s.due LIMIT 1`）：只要有几道题同时到期
            #   （同一天开始背的话很常见），每次都固定返回最早到期那道，
            #   它会永远霸占队列 → 用户看到"下一题老是同一道题"。
            #
            # 坑 B（改成按 last_review 排）：虽然不会连续重复，
            #   但只要不写作业，每次【新开会话】的第一题都会固定是同一道
            #   （因为 last_review 最小的那道是确定的），体验同样很差。
            #
            # 正确做法：分成两档，档内随机。
            #   第一档：已经逾期较久（due 远早于现在）—— 这些该优先补
            #   第二档：刚到期不久 —— 随机打散，避免固定首题
            # 再加一层「最近刚复习过的不选」，防止同一道题连着蹦出来。
            rows = c.execute(
                f"SELECT q.*, s.due, s.last_review FROM questions q "
                f"JOIN card_state s ON q.id=s.question_id "
                f"WHERE s.due IS NOT NULL AND s.due <= ?{cat_clause}{ex_sql()}",
                [now] + ex_args_tail()).fetchall()
            if rows:
                # 排除"刚刚才碰过"的（30 分钟内），避免立刻回来
                recent_cut = (datetime.now(timezone.utc).replace(tzinfo=None)
                              - timedelta(minutes=30)).isoformat(timespec="seconds")
                pool = [r for r in rows if (r["last_review"] or "") < recent_cut]
                if not pool:
                    pool = list(rows)
                # 逾期超过 1 天的算"该补的"，优先；其余打散
                overdue_cut = (datetime.now(timezone.utc).replace(tzinfo=None)
                               - timedelta(days=1)).isoformat(timespec="seconds")
                urgent = [r for r in pool if r["due"] < overdue_cut]
                return _row_to_q(_random.choice(urgent or pool))
            # 没有到期题 → 补充新题
            r = _pick_new(c, cat_clause, ex_sql(), ex_args_tail())
            if r is not None:
                return r
            mode = "random"

        if mode == "random":
            sql = (f"SELECT q.* FROM questions q WHERE 1=1{cat_clause}{ex_sql()}"
                   f" ORDER BY RANDOM() LIMIT 1")
            r = c.execute(sql, ex_args_tail()).fetchone()
            if r:
                return _row_to_q(r)

        # 兜底：排除当前题之后一道都没有（题库只够这一题时）
        # 放宽 exclude，保证界面永远有题可做
        if exclude_id:
            return next_question(category=category, mode=mode, exclude_id=None)

    return None


def pending_count(category: str | None = None) -> dict:
    """待办统计：新题 / 到期复习 / 错题。"""
    init_db()
    # 与 due 的存储口径保持一致：UTC
    now = _utc_now_iso()
    cat_clause = " AND category = ? " if category and category != "全部" else ""
    cat_args = [category] if cat_clause else []
    with conn() as c:
        total = c.execute(f"SELECT COUNT(*) n FROM questions WHERE 1=1{cat_clause}",
                          cat_args).fetchone()["n"]
        learned = c.execute(
            f"SELECT COUNT(*) n FROM card_state s JOIN questions q ON q.id=s.question_id"
            f" WHERE 1=1{cat_clause}", cat_args).fetchone()["n"]
        due = c.execute(
            f"SELECT COUNT(*) n FROM card_state s JOIN questions q ON q.id=s.question_id"
            f" WHERE s.due <= ?{cat_clause}", [now] + cat_args).fetchone()["n"]
        wrong = c.execute(
            f"SELECT COUNT(DISTINCT q.id) n FROM questions q JOIN ("
            f"  SELECT question_id, MIN(score) ms FROM reviews GROUP BY question_id"
            f"  HAVING ms < 60) w ON q.id=w.question_id WHERE 1=1{cat_clause}",
            cat_args).fetchone()["n"]
    return {"total": total, "learned": learned, "due": due,
            "new": total - learned, "wrong": wrong}


# ------------------------------------------------------------ 统计

def stats_overview() -> dict:
    init_db()
    with conn() as c:
        total = c.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
        learned = c.execute("SELECT COUNT(*) n FROM card_state").fetchone()["n"]
        cnt = c.execute("SELECT COUNT(*) n FROM reviews").fetchone()["n"]
        avg = c.execute("SELECT AVG(score) a FROM reviews").fetchone()["a"] or 0.0
        mastered = c.execute(
            "SELECT COUNT(*) n FROM ("
            "  SELECT question_id, MAX(score) mx FROM reviews GROUP BY question_id"
            ") WHERE mx >= 85").fetchone()["n"]
        streak = _streak_days(c)
    return {
        "total": total, "learned": learned, "reviews": cnt,
        "avg_score": round(avg, 1), "mastered": mastered,
        "streak_days": streak,
        "progress": round(learned / total * 100, 1) if total else 0.0,
    }


def _streak_days(c: sqlite3.Connection) -> int:
    """连续打卡天数（从今天往前数，允许今天还没打卡）。"""
    rows = c.execute(
        "SELECT DISTINCT substr(created_at,1,10) d FROM reviews ORDER BY d DESC"
    ).fetchall()
    days = [r["d"] for r in rows]
    if not days:
        return 0
    today = datetime.now().date()
    first = datetime.fromisoformat(days[0]).date()
    if (today - first).days > 1:      # 断签超过一天，连续中断
        return 0
    streak, cursor = 1, first
    for d in days[1:]:
        cur = datetime.fromisoformat(d).date()
        if (cursor - cur).days == 1:
            streak += 1
            cursor = cur
        else:
            break
    return streak


def category_progress() -> list[dict]:
    """各分类的掌握情况。"""
    init_db()
    with conn() as c:
        rows = c.execute("""
            SELECT q.category,
                   COUNT(DISTINCT q.id) total,
                   COUNT(DISTINCT s.question_id) learned,
                   AVG(r.score) avg_score,
                   COALESCE(SUM(CASE WHEN r.score >= 85 THEN 1 ELSE 0 END), 0) good
            FROM questions q
            LEFT JOIN card_state s ON q.id = s.question_id
            LEFT JOIN reviews r ON q.id = r.question_id
            GROUP BY q.category ORDER BY total DESC
        """).fetchall()
    return [{
        "category": r["category"], "total": r["total"], "learned": r["learned"],
        "avg_score": round(r["avg_score"] or 0, 1),
        "good": r["good"],
        "rate": round(r["learned"] / r["total"] * 100, 1) if r["total"] else 0.0,
    } for r in rows]


def wrong_book(limit: int = 300, only_unmastered: bool = True) -> list[dict]:
    """错题集：按「最低分」升序（最惨的排前面），带答错次数。"""
    init_db()
    having = "HAVING MIN(r.score) < 60" if only_unmastered else ""
    with conn() as c:
        rows = c.execute(f"""
            SELECT q.id, q.category, q.question,
                   MIN(r.score)   minscore,
                   MAX(r.score)   maxscore,
                   COUNT(r.id)    times,
                   SUM(CASE WHEN r.score < 60 THEN 1 ELSE 0 END) fail_times,
                   MAX(r.created_at) last_at,
                   (SELECT miss_points FROM reviews r2
                     WHERE r2.question_id=q.id ORDER BY r2.created_at DESC LIMIT 1) last_miss,
                   (SELECT feedback FROM reviews r3
                     WHERE r3.question_id=q.id ORDER BY r3.created_at DESC LIMIT 1) last_feedback
            FROM questions q JOIN reviews r ON q.id = r.question_id
            GROUP BY q.id {having}
            ORDER BY minscore ASC, fail_times DESC LIMIT ?
        """, (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["last_miss"] = json.loads(d["last_miss"]) if d["last_miss"] else []
        out.append(d)
    return out


def score_trend(days: int = 30) -> list[dict]:
    """最近 N 天的每日作答量与平均分。"""
    init_db()
    since = (datetime.now() - timedelta(days=days)).date().isoformat()
    with conn() as c:
        rows = c.execute("""
            SELECT substr(created_at,1,10) d,
                   COUNT(*) n, ROUND(AVG(score),1) avg_score
            FROM reviews WHERE substr(created_at,1,10) >= ?
            GROUP BY d ORDER BY d
        """, (since,)).fetchall()
    return [dict(r) for r in rows]


def grade_distribution() -> dict:
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT grade, COUNT(*) n FROM reviews GROUP BY grade").fetchall()
    return {r["grade"]: r["n"] for r in rows}


def recent_reviews(limit: int = 50) -> list[dict]:
    init_db()
    with conn() as c:
        rows = c.execute("""
            SELECT r.*, q.question, q.category
            FROM reviews r JOIN questions q ON q.id = r.question_id
            ORDER BY r.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    n = import_questions(force=True)
    print(f"导入题库: {n} 条")
    print("待办统计:", pending_count())
    print("总览:", stats_overview())
    print("分类:", list_categories())
