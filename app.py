# -*- coding: utf-8 -*-
"""背面试题小助手 —— Streamlit 主界面

启动：  streamlit run app.py
"""

import html
import hmac
import json
import os
import time
import json as _json
import urllib.error
import urllib.request
from datetime import datetime

import pandas as pd
import streamlit as st

import grader
import store
from supabase_store import SupabaseStore

st.set_page_config(
    page_title="面试题背题助手",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------ 样式

CSS = """
<style>
  :root {
      --ink:#172033; --muted:#68738A; --line:#E4E9F2; --surface:#FFFFFF;
      --soft:#F6F8FC; --brand:#5B5CE2; --brand-dark:#4546C7;
  }
  .stApp { background: linear-gradient(180deg, #F7F8FD 0, #FFFFFF 22rem); color:var(--ink); }
  .main .block-container { padding-top: 1.25rem; padding-bottom:3rem; max-width:1120px; }
  [data-testid="stSidebar"] { background:#FBFCFF; border-right:1px solid var(--line); }
  [data-testid="stSidebar"] .block-container { padding-top:1.4rem; }
  [data-testid="stSidebar"] h3 { color:var(--ink); letter-spacing:-.02em; }
  [data-testid="stProgress"] > div > div { background:var(--brand); }
  div[data-testid="stRadio"] label, div[data-testid="stSelectbox"] label,
  div[data-testid="stTextArea"] label { color:var(--ink); font-weight:600; }
  div[role="radiogroup"] label { border-radius:9px; padding:.2rem .45rem; }
  div[data-testid="stHorizontalBlock"] { gap:.8rem; }
  .stButton > button { border-radius:9px; min-height:2.65rem; font-weight:650; }
  .stButton > button[kind="primary"] { background:var(--brand); border-color:var(--brand); }
  .stButton > button[kind="primary"]:hover { background:var(--brand-dark); border-color:var(--brand-dark); }
  textarea { border-radius:12px !important; border-color:#D9DFEA !important; line-height:1.65 !important; }
  textarea:focus { border-color:var(--brand) !important; box-shadow:0 0 0 3px #5B5CE21F !important; }
  [data-testid="stMetric"] { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:.9rem 1rem; }
  [data-testid="stExpander"] { border-color:var(--line); border-radius:12px; background:var(--surface); }
  div[data-baseweb="tab-list"] { gap:.35rem; }
  button[data-baseweb="tab"] { border-radius:9px 9px 0 0; padding-left:1rem; padding-right:1rem; }
  .practice-kicker { color:var(--brand); font-size:.78rem; font-weight:750; letter-spacing:.09em; text-transform:uppercase; }
  .practice-title { margin:.15rem 0 .9rem; font-size:1.65rem; line-height:1.25; letter-spacing:-.035em; color:var(--ink); font-weight:760; }
  .session-pill { display:inline-flex; align-items:center; gap:.4rem; background:#EEF0FF; color:#4546C7;
      border:1px solid #D9DCFF; border-radius:999px; padding:.28rem .7rem; font-size:.8rem; font-weight:650; }
  .q-card {
      background:var(--surface); border:1px solid var(--line); border-top:4px solid var(--brand);
      border-radius:14px; padding:22px 24px; margin-bottom:18px;
      box-shadow:0 10px 30px rgba(33,42,78,.06);
  }
  .q-card .q-label { font-size:.78rem; color:var(--brand); letter-spacing:.08em; font-weight:750;
      text-transform: uppercase; margin-bottom: 6px; }
  .q-card .q-text { font-size:1.3rem; font-weight:680; color:var(--ink); line-height:1.55; letter-spacing:-.015em; }
  .q-meta { font-size:.8rem; color:var(--muted); margin-top:13px; }
  .tag { display:inline-block; background:#EEF0FF; color:#4546C7; border-radius:999px;
      padding:3px 10px; font-size:.75rem; margin:3px 6px 0 0; font-weight:600;}
  .tag.gray { background:#F1F3F7; color:#59647A; }

  .score-box { border-radius: 12px; padding: 16px 20px; text-align:center; }
  .score-num { font-size: 2.5rem; font-weight: 700; line-height: 1.1; }
  .score-sub { font-size: .82rem; color: #475569; margin-top: 4px; }

  .pt { border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; font-size: .92rem;
        line-height: 1.6; }
  .pt-hit  { background:#F0FDF4; border-left:4px solid #16A34A; }
  .pt-miss { background:#FEF2F2; border-left:4px solid #DC2626; }
  .pt-part { background:#FFFBEB; border-left:4px solid #D97706; }
  .pt-wrong{ background:#FDF4FF; border-left:4px solid #A855F7; }
  .pt-ev { color:#475569; font-size:.85rem; margin-top:4px; }
  .pt-ev b { color:#0F172A; }

  .fb { background:#EFF6FF; border:1px solid #BFDBFE; border-radius:10px;
        padding:16px 20px; font-size:.95rem; line-height:1.75; color:#1E293B; }

  .stat-card { background:#fff; border:1px solid var(--line); border-radius:12px;
        padding:14px 16px; text-align:center; box-shadow:0 5px 18px rgba(33,42,78,.035); }
  .stat-num { font-size:1.9rem; font-weight:750; color:var(--brand); line-height:1.15; }
  .stat-lbl { font-size:.8rem; color:var(--muted); margin-top:3px; }
  @media (max-width: 768px) {
      .main .block-container { padding:1rem .85rem 2rem; }
      .practice-title { font-size:1.4rem; }
      .q-card { padding:18px 17px; border-radius:12px; }
      .q-card .q-text { font-size:1.12rem; }
      .score-num { font-size:2rem; }
      div[data-testid="stHorizontalBlock"] { gap:.45rem; }
  }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def require_access() -> None:
    """公网部署时启用一个轻量访问密码；本地未配置时不打扰使用。"""
    expected = os.getenv("APP_PASSWORD", "").strip()
    if not expected:
        try:
            expected = str(st.secrets.get("APP_PASSWORD", "")).strip()
        except Exception:  # 本地没有 secrets.toml
            expected = ""
    if not expected or st.session_state.get("authenticated"):
        return

    st.markdown(
        '<div class="practice-kicker">PRIVATE WORKSPACE</div>'
        '<div class="practice-title">进入面试题训练器</div>',
        unsafe_allow_html=True,
    )
    st.caption("请输入部署时设置的访问密码。")
    password = st.text_input("访问密码", type="password", placeholder="输入访问密码")
    if st.button("进入训练器", type="primary", width="stretch"):
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("密码不正确，请重试。")
    st.stop()


require_access()


def _cloud_config() -> tuple[str, str]:
    """Return Supabase public connection settings, or blanks during local development."""
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip()
        key = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()
    except Exception:
        url, key = "", ""
    return url or os.getenv("SUPABASE_URL", ""), key or os.getenv("SUPABASE_ANON_KEY", "")


def _supabase_auth(url: str, key: str, action: str, email: str, password: str) -> dict:
    data = _json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/auth/v1/{action}", data=data, method="POST",
        headers={"apikey": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return _json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _json.loads(exc.read().decode("utf-8", errors="replace"))
        raise ValueError(detail.get("msg") or detail.get("message") or "登录失败") from exc


def require_user() -> None:
    """Enable per-person accounts only when the cloud database has been configured."""
    global store
    url, key = _cloud_config()
    if not (url and key):
        return
    if "cloud_user" not in st.session_state:
        st.markdown('<div class="practice-kicker">PERSONAL STUDY SPACE</div><div class="practice-title">登录后保存你的错题本</div>', unsafe_allow_html=True)
        tab_login, tab_register = st.tabs(["登录", "注册"])
        with tab_login:
            email = st.text_input("邮箱", key="login_email")
            password = st.text_input("密码", type="password", key="login_password")
            if st.button("登录", type="primary", width="stretch"):
                try:
                    data = _supabase_auth(url, key, "token?grant_type=password", email, password)
                    st.session_state["cloud_user"] = {"id": data["user"]["id"], "token": data["access_token"], "email": data["user"]["email"]}
                    st.rerun()
                except (ValueError, KeyError) as exc:
                    st.error(str(exc))
        with tab_register:
            email = st.text_input("邮箱", key="register_email")
            password = st.text_input("设置密码（至少 6 位）", type="password", key="register_password")
            if st.button("注册账号", type="primary", width="stretch"):
                try:
                    data = _supabase_auth(url, key, "signup", email, password)
                    if data.get("access_token"):
                        st.session_state["cloud_user"] = {"id": data["user"]["id"], "token": data["access_token"], "email": data["user"]["email"]}
                        st.rerun()
                    st.success("注册成功，请到邮箱点击验证链接后再登录。")
                except ValueError as exc:
                    st.error(str(exc))
        st.stop()
    user = st.session_state["cloud_user"]
    store = SupabaseStore(url, key, user["token"], user["id"])


require_user()


# ------------------------------------------------------------------ 初始化

@st.cache_resource
def _bootstrap() -> dict:
    if isinstance(store, SupabaseStore):
        return {"imported": 0, "ready": True}
    store.init_db()
    n = store.import_questions()
    return {"imported": n, "ready": True}


_bootstrap()


def ensure_state() -> None:
    defaults = {
        "current": None,          # 当前题目 dict
        "result": None,           # 当前判分结果
        "started_at": None,       # 本题开始时间
        "answer_text": "",        # 输入框内容（纯状态，不做 widget key）
        "answer_nonce": 0,        # 换题计数器：递增即强制输入框重建为空
        "cat_filter": "全部",
        "mode": "due",
        "show_answer": False,     # 是否已放弃并看答案
        "session_done": 0,        # 本次会话已做题数
        "session_scores": [],     # 本次会话得分
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


ensure_state()


def _filters_changed() -> None:
    """筛选条件变化后立即换成符合新条件的题目。"""
    st.session_state["current"] = None
    st.session_state["result"] = None
    st.session_state["show_answer"] = False
    _reset_answer_box()


# ------------------------------------------------------------------ 侧边栏

def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 🎯 面试题背题助手")

        if "cloud_user" in st.session_state:
            st.caption(f"👤 {st.session_state['cloud_user']['email']}")
            if st.button("退出登录", width="stretch"):
                del st.session_state["cloud_user"]
                st.rerun()
            st.divider()

        ov = store.stats_overview()
        c1, c2 = st.columns(2)
        c1.markdown(
            f'<div class="stat-card"><div class="stat-num">{ov["learned"]}</div>'
            f'<div class="stat-lbl">已背 / 共 {ov["total"]}</div></div>',
            unsafe_allow_html=True)
        c2.markdown(
            f'<div class="stat-card"><div class="stat-num">{ov["streak_days"]}</div>'
            f'<div class="stat-lbl">连续打卡(天)</div></div>',
            unsafe_allow_html=True)

        st.progress(ov["progress"] / 100, text=f"整体进度 {ov['progress']}%")
        st.caption("")

        cats = ["全部"] + [c for c, _ in store.list_categories()]
        st.selectbox("分类", cats, key="cat_filter", on_change=_filters_changed)

        st.radio(
            "出题模式",
            options=["due", "new", "wrong", "random"],
            format_func=lambda m: {
                "due": "📅 复习优先（到期题+新题）",
                "new": "🆕 只背新题",
                "wrong": "❌ 只刷错题",
                "random": "🎲 随机抽题",
            }[m],
            key="mode",
            on_change=_filters_changed,
        )

        pc = store.pending_count(st.session_state["cat_filter"])
        st.caption(
            f"待复习 **{pc['due']}** · 新题 **{pc['new']}** · 错题 **{pc['wrong']}**")

        st.divider()

        if st.session_state["session_done"]:
            sc = st.session_state["session_scores"]
            st.caption(
                f"本次已做 **{st.session_state['session_done']}** 题 · "
                f"平均 **{sum(sc)/len(sc):.1f}** 分")

        if st.button("🔄 换一题", width='stretch'):
            _load_next(force=True)
            st.rerun()

        if st.button("📊 清空本次会话", width='stretch'):
            st.session_state["session_done"] = 0
            st.session_state["session_scores"] = []
            st.rerun()

        st.divider()
        render_ai_settings()


def render_ai_settings() -> None:
    """AI 供应商与 Key 设置。"""
    cfg = grader.provider_config()
    ok = bool(cfg["api_key"])
    label = "🤖 AI 判分设置"
    if ok:
        label += f" · {cfg['provider_label']}"
    else:
        label += " · ⚠️ 未配置"

    with st.expander(label, expanded=not ok):
        names = list(grader.PROVIDERS.keys())
        labels = {n: grader.PROVIDERS[n]["label"] for n in names}
        cur = grader.active_provider()

        choice = st.selectbox(
            "供应商", names, index=names.index(cur) if cur in names else 0,
            format_func=lambda n: labels[n])
        spec = grader.PROVIDERS[choice]
        st.caption(spec["note"])

        key_now = grader.load_api_key(choice)
        if key_now:
            st.success(f"✅ 已配置（{key_now[:7]}…{key_now[-4:]}）")
        else:
            st.warning("尚未配置 API Key，当前为离线粗判模式")

        new_key = st.text_input(
            f"{spec['env']}", value="", type="password",
            placeholder="sk-...", label_visibility="collapsed")

        c1, c2 = st.columns(2)
        if c1.button("保存并切换", width='stretch'):
            if not new_key.strip():
                st.warning("请先填入 Key")
            else:
                grader.save_api_key(new_key.strip(), choice)
                st.success(f"已切换到 {labels[choice]}")
                time.sleep(0.6)
                st.rerun()
        if c2.button("测试连接", width='stretch'):
            if not new_key.strip() and not key_now:
                st.warning("请先填入 Key")
            else:
                with st.spinner("测试中…"):
                    g = grader.Grader(
                        api_key=new_key.strip() or key_now, provider=choice)
                    good, msg = g.test_connection()
                (st.success if good else st.error)(msg)

        # 模型覆盖
        with st.expander("高级：模型 / 端点"):
            models = spec["alt_models"]
            env_now = grader.read_env()
            default_model = env_now.get("AI_MODEL") or spec["model"]
            if models:
                idx = models.index(default_model) if default_model in models else 0
                m = st.selectbox("模型", models, index=idx)
            else:
                m = st.text_input("模型", value=default_model)
            b = st.text_input("Base URL", value=env_now.get("AI_BASE_URL")
                              or spec["base_url"],
                              help="任何 OpenAI 兼容端点，如 http://localhost:11434/v1")
            if st.button("应用", width='stretch'):
                grader.write_env({"AI_PROVIDER": choice,
                                  "AI_MODEL": m, "AI_BASE_URL": b})
                st.success("已应用")
                time.sleep(0.5)
                st.rerun()

        st.caption("Key 只存在本机 `interview-trainer/.env`，不会外传。")
        if spec["key_url"]:
            st.caption(f"获取 Key：{spec['key_url']}")


# ------------------------------------------------------------------ 出题

def _reset_answer_box() -> None:
    """清空作答输入框。

    注意：输入框是用 key="answer_input" 实例化的，一旦本轮流式渲染跑过它，
    再直接写 st.session_state["answer_input"] 会抛
    StreamlitWidgetAlreadyInstantiatedError，整个回调被打断
    （"下一题"点了没反应 / 卡住就是这么来的）。

    正确做法：把输入框绑定到「哨兵 key」，换题目时递增计数器换个新 key，
    Streamlit 就会当成一个新控件，自然从空值开始。
    """
    st.session_state["answer_nonce"] = st.session_state.get("answer_nonce", 0) + 1
    st.session_state["answer_text"] = ""


def _load_next(force: bool = False) -> None:
    if st.session_state["current"] is not None and not force:
        return
    # 把当前题号传下去，否则在"这题还没有作答记录"时（比如点了「不会，看答案」）
    # 查出来的还是同一道题 —— 就是"切不了下一题"的根因
    cur = st.session_state.get("current")
    q = store.next_question(
        category=st.session_state["cat_filter"],
        mode=st.session_state["mode"],
        exclude_id=cur["id"] if cur else None,
    )
    st.session_state["current"] = q
    st.session_state["result"] = None
    st.session_state["show_answer"] = False
    _reset_answer_box()
    st.session_state["started_at"] = time.time()


# ------------------------------------------------------------------ 判分渲染

GRADE_META = {
    "easy":  ("Easy",  "#16A34A", "#F0FDF4", "答得完整，复习间隔拉长"),
    "good":  ("Good",  "#2563EB", "#EFF6FF", "基本掌握，正常间隔复习"),
    "hard":  ("Hard",  "#D97706", "#FFFBEB", "有遗漏，较短间隔重来"),
    "again": ("Again", "#DC2626", "#FEF2F2", "没答对，很快再考一次"),
}


def _score_color(s: float) -> str:
    if s >= 85:
        return "#16A34A"
    if s >= 70:
        return "#2563EB"
    if s >= 50:
        return "#D97706"
    return "#DC2626"


def render_result(res: dict, q: dict) -> None:
    grade = store.score_to_grade(res["score"])
    gname, gcolor, gbg, gdesc = GRADE_META[grade]
    sc = res["score"]
    scol = _score_color(sc)

    c1, c2, c3 = st.columns([1, 1, 2])
    c1.markdown(
        f'<div class="score-box" style="background:{scol}14;border:1px solid {scol}40">'
        f'<div class="score-num" style="color:{scol}">{sc:.0f}</div>'
        f'<div class="score-sub">AI 评分 / 100</div></div>', unsafe_allow_html=True)
    c2.markdown(
        f'<div class="score-box" style="background:{gbg};border:1px solid {gcolor}40">'
        f'<div class="score-num" style="color:{gcolor};font-size:1.6rem">{gname}</div>'
        f'<div class="score-sub">{gdesc}</div></div>', unsafe_allow_html=True)
    c3.markdown(
        f'<div class="score-box" style="background:#F8FAFC;border:1px solid #E2E8F0">'
        f'<div class="score-num" style="color:#4F46E5">{res["coverage"]*100:.0f}%</div>'
        f'<div class="score-sub">要点覆盖率</div></div>', unsafe_allow_html=True)

    st.caption("")
    st.markdown('<div class="fb">💬 ' + html.escape(res["feedback"]).replace("\n", "<br>")
                + "</div>", unsafe_allow_html=True)
    st.caption("")

    # ---- 逐要点对照 ----
    hit = res.get("hit", [])
    miss = res.get("miss", [])
    wrong = res.get("wrong", [])

    tab1, tab2, tab3 = st.tabs([
        f"✅ 命中 {len(hit)}", f"❌ 缺失 {len(miss)}",
        f"⚠️ 错误 {len(wrong)}"])

    with tab1:
        if not hit:
            st.info("没有命中任何要点。")
        for h in hit:
            pt = h.get("point", "") if isinstance(h, dict) else str(h)
            ev = h.get("evidence", "") if isinstance(h, dict) else ""
            partial = isinstance(h, dict) and h.get("verdict") == "partial"
            cls = "pt-part" if partial else "pt-hit"
            mark = "🟡 部分命中" if partial else "✅"
            st.markdown(
                f'<div class="pt {cls}">{mark} {html.escape(pt)}'
                + (f'<div class="pt-ev">你的表述：<b>{html.escape(str(ev))}</b></div>'
                   if ev else "")
                + "</div>", unsafe_allow_html=True)

    with tab2:
        if not miss:
            st.success("要点全覆盖，没有遗漏。")
        for m in miss:
            pt = m.get("point", "") if isinstance(m, dict) else str(m)
            hint = m.get("hint", "") if isinstance(m, dict) else ""
            st.markdown(
                f'<div class="pt pt-miss">❌ {html.escape(pt)}'
                + (f'<div class="pt-ev">💡 {html.escape(str(hint))}</div>' if hint else "")
                + "</div>", unsafe_allow_html=True)

    with tab3:
        if not wrong:
            st.success("没有发现事实性错误。")
        for w in wrong:
            claim = w.get("claim", "") if isinstance(w, dict) else str(w)
            corr = w.get("correction", "") if isinstance(w, dict) else ""
            st.markdown(
                f'<div class="pt pt-wrong">⚠️ {html.escape(str(claim))}'
                + (f'<div class="pt-ev">✔ 正确说法：<b>{html.escape(str(corr))}</b></div>'
                   if corr else "")
                + "</div>", unsafe_allow_html=True)

    # ---- 参考答案 ----
    with st.expander("📖 查看参考答案全文"):
        for i, p in enumerate(q["rubric"], 1):
            st.markdown(f"**{i}.** {p}")
        if q.get("extra_points"):
            st.markdown("---")
            st.caption("补充说明")
            for e in q["extra_points"]:
                st.caption(f"· {e}")


# ------------------------------------------------------------------ 页面：背题

def page_practice() -> None:
    _load_next()
    q = st.session_state["current"]

    if q is None:
        st.success("🎉 当前筛选条件下没有可背的题目了。换个分类或模式试试。")
        return

    ov = store.stats_overview()
    done = st.session_state["session_done"]
    avg = st.session_state["session_scores"]
    session_text = f"本轮 {done} 题" + (f" · 均分 {sum(avg)/len(avg):.0f}" if avg else "")
    st.markdown(
        '<div class="practice-kicker">Focused practice</div>'
        '<div class="practice-title">今天，把一个知识点讲明白</div>'
        f'<span class="session-pill">◉ {session_text}</span> '
        f'<span class="session-pill">总进度 {ov["progress"]:.1f}%</span>',
        unsafe_allow_html=True,
    )
    st.caption("")

    # 题干卡
    st.markdown(
        f'<div class="q-card">'
        f'<div class="q-label">题目</div>'
        f'<div class="q-text">{html.escape(q["question"])}</div>'
        f'<div class="q-meta"><span class="tag">{html.escape(q["category"])}</span>'
        f'<span class="tag gray">{q["date"]}</span>'
        f'<span class="tag gray">要点 {len(q["rubric"])} 条</span></div>'
        f"</div>", unsafe_allow_html=True)

    res = st.session_state["result"]

    # ---- 作答区 ----
    if res is None:
        st.markdown("##### ✍️ 用你自己的话答一遍")
        st.caption("不用背原文，把要点说清楚就行。AI 会按要点覆盖情况判分。")
        answer = st.text_area(
            "你的答案", key=f"answer_input_{st.session_state['answer_nonce']}", height=200,
            placeholder="在这里写下你的回答……\n\n提示：分点写更容易被判定命中，比如「1) …… 2) ……」",
            label_visibility="collapsed")
        # 同步到稳定状态字段，供判分与重答使用
        st.session_state["answer_text"] = answer

        c1, c2, _ = st.columns([1, 1, 3])
        submit = c1.button("提交判分", type="primary", width='stretch')
        giveup = c2.button("不会，看答案", width='stretch')

        if giveup:
            st.session_state["show_answer"] = True

        if submit:
            if not answer.strip():
                st.warning("先写点东西再提交吧，哪怕只记得个大概。")
            else:
                elapsed = int(time.time() - (st.session_state["started_at"] or time.time()))
                with st.spinner("AI 正在逐条对照要点判分…"):
                    try:
                        r = grader.grade(q["question"], q["rubric"], answer)
                    except Exception as e:               # noqa: BLE001
                        st.error(f"判分失败：{e}")
                        r = None
                    if r:
                        store.record_review(q["id"], answer, r, elapsed_sec=elapsed,
                                            model=r.get("model", ""))
                        st.session_state["result"] = r
                        st.session_state["session_done"] += 1
                        st.session_state["session_scores"].append(r["score"])
                        st.rerun()

        if st.session_state["show_answer"]:
            st.divider()
            st.markdown("##### 📖 参考答案")
            for i, p in enumerate(q["rubric"], 1):
                st.markdown(f"**{i}.** {p}")
            if q.get("extra_points"):
                with st.expander("补充说明"):
                    for e in q["extra_points"]:
                        st.caption(f"· {e}")
            if st.button("我记住了，下一题 →", type="primary"):
                # 看了答案才过的题，要落一条记录让它进入复习队列，
                # 否则它的 card_state 永远为空，会被当成"新题"反复取出来。
                #
                # 注意：必须带 skipped=True。按 0 分走 again 的话，
                # FSRS 会把它排到 ~1 分钟后 → 一分钟后它又成了"到期题"，
                # 而 due 分支又总是优先取最早到期的那道，
                # 结果就是每次点下一题都弹回同一道题。
                # skipped 走固定 2 天间隔，且分数记 60 分（不算错题，不进错题集）。
                try:
                    skip_result = {
                        "score": 60.0, "coverage": 0.0,
                        "hit": [], "miss": list(q["rubric"]),
                        "feedback": "看了答案才过，未作答",
                        "model": "", "skipped": True,
                    }
                    store.record_review(
                        q["id"], st.session_state.get("answer_text") or "（看了答案）",
                        skip_result,
                        elapsed_sec=int(time.time() - (st.session_state["started_at"]
                                                       or time.time())),
                    )
                except Exception as e:                     # noqa: BLE001
                    st.caption(f"（记录跳过状态失败，不影响继续背题：{e}）")
                _load_next(force=True)
                st.rerun()

    # ---- 判分结果 ----
    else:
        render_result(res, q)
        st.divider()
        c1, c2, c3 = st.columns([1, 1, 3])
        if c1.button("下一题 →", type="primary", width='stretch'):
            _load_next(force=True)
            st.rerun()
        if c2.button("🔁 重答这道", width='stretch'):
            st.session_state["result"] = None
            _reset_answer_box()
            st.session_state["started_at"] = time.time()
            st.rerun()
        c3.caption("判分不满意？点「重答这道」再来一遍，两次都会被记入统计。")


# ------------------------------------------------------------------ 页面：错题集

def page_wrong() -> None:
    st.markdown("### ❌ 错题集")
    st.caption("按历史最低分排序 —— 最惨的排最前面。点开可以直接看当时错在哪。")

    col1, _ = st.columns([1, 3])
    only_un = col1.checkbox("只看还没攻克的（最低分 < 60）", value=True)
    rows = store.wrong_book(only_unmastered=only_un)

    if not rows:
        st.success("错题集是空的 —— 要么还没背过，要么都答得不错。")
        return

    st.caption(f"共 **{len(rows)}** 道题进过错题集")
    st.caption("")

    for r in rows:
        tag = "🔴" if r["minscore"] < 40 else ("🟠" if r["minscore"] < 60 else "🟡")
        label = (f"{tag} **{r['minscore']:.0f}分** · {r['question'][:52]}"
                 f"{'…' if len(r['question']) > 52 else ''}   "
                 f"`{r['category']}` · 错 {int(r['fail_times'])} 次 / 共 {int(r['times'])} 次")
        with st.expander(label):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("最低分", f"{r['minscore']:.0f}")
            c2.metric("最高分", f"{r['maxscore']:.0f}")
            c3.metric("作答次数", int(r["times"]))
            c4.metric("答错次数", int(r["fail_times"]))

            st.markdown("**题目**  \n" + r["question"])

            if r["last_miss"]:
                st.markdown("**上次漏掉的要点**")
                for m in r["last_miss"]:
                    pt = m.get("point", "") if isinstance(m, dict) else str(m)
                    st.markdown(f"- ❌ {pt}")

            if r["last_feedback"]:
                st.markdown("**上次 AI 评语**")
                st.info(r["last_feedback"])

            q = store.get_question(r["id"])
            if q:
                with st.expander("📖 参考答案全文"):
                    for i, p in enumerate(q["rubric"], 1):
                        st.markdown(f"**{i}.** {p}")

            if st.button("🎯 专项练这道", key=f"practice_{r['id']}"):
                st.session_state["current"] = q
                st.session_state["result"] = None
                st.session_state["show_answer"] = False
                _reset_answer_box()
                st.session_state["started_at"] = time.time()
                st.session_state["_nav"] = "背题"
                st.rerun()


# ------------------------------------------------------------------ 页面：统计

def page_stats() -> None:
    st.markdown("### 📊 学习统计")
    ov = store.stats_overview()

    c = st.columns(5)
    metrics = [
        ("总题量", ov["total"], "#64748B"),
        ("已背", ov["learned"], "#4F46E5"),
        ("累计作答", ov["reviews"], "#0891B2"),
        ("平均分", f'{ov["avg_score"]:.1f}', "#2563EB"),
        ("已掌握(≥85)", ov["mastered"], "#16A34A"),
    ]
    for col, (lbl, val, color) in zip(c, metrics):
        col.markdown(
            f'<div class="stat-card"><div class="stat-num" style="color:{color}">{val}</div>'
            f'<div class="stat-lbl">{lbl}</div></div>', unsafe_allow_html=True)

    st.caption("")
    pc = store.pending_count()
    st.markdown(
        f"**今天要做**：待复习 **{pc['due']}** 题 · 新题 **{pc['new']}** 题 · "
        f"错题 **{pc['wrong']}** 题　　"
        f"🔥 连续打卡 **{ov['streak_days']}** 天")

    st.divider()

    # ---- 分类掌握度 ----
    st.markdown("#### 各分类掌握情况")
    cp = store.category_progress()
    if cp:
        df = pd.DataFrame(cp)
        df = df[df["total"] > 0]
        show = df[["category", "total", "learned", "rate", "avg_score", "good"]].copy()
        show.columns = ["分类", "总题数", "已背", "背诵进度%", "平均分", "≥85分次数"]
        st.dataframe(
            show, width='stretch', hide_index=True,
            column_config={
                "背诵进度%": st.column_config.ProgressColumn(
                    "背诵进度", min_value=0, max_value=100, format="%.1f%%"),
                "平均分": st.column_config.NumberColumn(format="%.1f"),
            })

        st.caption("")
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**背诵进度**")
            bar = df.set_index("category")[["learned", "total"]].copy()
            bar["未背"] = bar["total"] - bar["learned"]
            st.bar_chart(bar[["learned", "未背"]], color=["#4F46E5", "#E2E8F0"],
                         horizontal=True, height=340)
        with cc2:
            st.markdown("**平均分**")
            sc = df[df["avg_score"] > 0].set_index("category")["avg_score"].sort_values()
            if len(sc):
                st.bar_chart(sc, color="#0891B2", horizontal=True, height=340)
            else:
                st.info("还没有作答记录。")
    else:
        st.info("题库为空。")

    st.divider()

    # ---- 趋势 ----
    st.markdown("#### 最近 30 天作答趋势")
    trend = store.score_trend(30)
    if trend:
        tdf = pd.DataFrame(trend)
        tdf["d"] = pd.to_datetime(tdf["d"])
        tdf = tdf.set_index("d")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("每日作答量")
            st.bar_chart(tdf[["n"]], color="#4F46E5", height=260)
        with c2:
            st.caption("每日平均分")
            if tdf["avg_score"].notna().any():
                st.line_chart(tdf[["avg_score"]], color="#16A34A", height=260)
            else:
                st.info("暂无数据")
    else:
        st.info("最近 30 天还没有作答记录。")

    # ---- 评级分布 ----
    st.divider()
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("#### 记忆状态分布")
        gd = store.grade_distribution()
        if gd:
            names = {"easy": "Easy（熟练）", "good": "Good（掌握）",
                     "hard": "Hard（生疏）", "again": "Again（未掌握）"}
            gdf = pd.DataFrame(
                [{"状态": names.get(k, k), "次数": v} for k, v in gd.items()]
            ).set_index("状态")
            st.dataframe(gdf, width='stretch')
        else:
            st.info("还没有作答记录。")
    with c2:
        st.markdown("#### 最近作答记录")
        rec = store.recent_reviews(20)
        if rec:
            rdf = pd.DataFrame(rec)[
                ["created_at", "category", "question", "score", "grade"]]
            rdf.columns = ["时间", "分类", "题目", "分数", "评级"]
            rdf["题目"] = rdf["题目"].str.slice(0, 46) + "…"
            st.dataframe(rdf, width='stretch', hide_index=True, height=380)
        else:
            st.info("还没有作答记录。")


# ------------------------------------------------------------------ 主入口

def main() -> None:
    render_sidebar()

    nav = st.radio(
        "导航", ["背题", "错题集", "统计"],
        horizontal=True, label_visibility="collapsed",
        index=["背题", "错题集", "统计"].index(st.session_state.get("_nav", "背题")),
    )
    st.session_state["_nav"] = nav
    st.caption("")

    if nav == "背题":
        page_practice()
    elif nav == "错题集":
        page_wrong()
    else:
        page_stats()


if __name__ == "__main__":
    main()
