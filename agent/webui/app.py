"""
Capricorn WebUI

通过 Gateway API 与 agent 对话。
启动方式：python run.py --mode gateway_with_webui
"""

import requests
import streamlit as st
import uuid

# ── 配置 ────────────────────────────────────────────

API_BASE = st.secrets.get("api_base", "http://127.0.0.1:8080")

st.set_page_config(page_title="Capricorn", page_icon="🤖", layout="wide")

# ── 主题感知 CSS ────────────────────────────────────

st.markdown("""
<style>
/* 浅色主题 */
[data-theme="light"] .cap-title { color: #111827; }
[data-theme="light"] .cap-sub { color: #6b7280; }
[data-theme="light"] .cap-cur {
    background: linear-gradient(135deg,#eff6ff,#dbeafe);
    border-left: 3px solid #3b82f6;
    color: #111827;
}
[data-theme="light"] .cap-cur-meta { color: #6b7280; }
/* 深色主题 */
[data-theme="dark"] .cap-title { color: #f3f4f6; }
[data-theme="dark"] .cap-sub { color: #9ca3af; }
[data-theme="dark"] .cap-cur {
    background: rgba(59,130,246,0.12);
    border-left: 3px solid #3b82f6;
    color: #f3f4f6;
}
[data-theme="dark"] .cap-cur-meta { color: #9ca3af; }
/* 公共 */
.cap-cur { padding: 8px 12px; border-radius: 8px; font-size: 0.87em; font-weight: 500; }
.cap-cur-meta { font-size: 0.75em; font-weight: 400; }
</style>
""", unsafe_allow_html=True)

# ── Session State ─────────────────────────────────────

_qp = st.query_params
_qp_thread = _qp.get("t", "default")

for key, val in [
    ("current_thread_id", _qp_thread),
    ("messages", []),
    ("session_loaded", False),
    ("unread_count", 0),
    ("manage_mode", False),
]:
    if key not in st.session_state:
        st.session_state[key] = val


# ── API ───────────────────────────────────────────────

def _get(path, timeout=5):
    try:
        return requests.get(f"{API_BASE}{path}", timeout=timeout)
    except Exception:
        return None


def _post(path, data, timeout=60):
    try:
        return requests.post(f"{API_BASE}{path}", json=data, timeout=timeout)
    except Exception:
        return None


def _delete(path, timeout=5):
    try:
        return requests.delete(f"{API_BASE}{path}", timeout=timeout)
    except Exception:
        return None


def _load_history(tid):
    resp = _get(f"/history/{tid}")
    return resp.json().get("messages", []) if resp and resp.status_code == 200 else []


def _switch(tid):
    st.session_state.current_thread_id = tid
    st.session_state.messages = _load_history(tid)
    st.session_state.session_loaded = True
    st.session_state.manage_mode = False
    st.query_params["t"] = tid


def _remove(tid):
    _delete(f"/sessions/{tid}")
    if st.session_state.current_thread_id == tid:
        st.session_state.current_thread_id = "default"
        st.session_state.messages = []


def _send(prompt):
    resp = _post("/chat", {"prompt": prompt, "thread_id": st.session_state.current_thread_id}, timeout=500)
    if resp and resp.status_code == 200:
        data = resp.json()
        return data.get("response") if not data.get("error") else f"**错误:** {data['error']}"
    elif resp:
        return f"**错误:** {resp.json().get('error', '未知错误')}"
    return "**连接失败:** Gateway 未启动"


if not st.session_state.session_loaded:
    st.session_state.messages = _load_history(st.session_state.current_thread_id)
    st.session_state.session_loaded = True


# ── 侧边栏 ─────────────────────────────────────────

with st.sidebar:
    tab_sess, tab_cron = st.tabs(["会话", "任务"])

    # ── 会话 ────────────────────────────────────────
    with tab_sess:
        col_a, col_b = st.columns([3, 2])
        with col_a:
            if st.button("✚ 新对话", use_container_width=True):
                _switch(uuid.uuid4().hex[:8])
                st.rerun()
        with col_b:
            label = "完成" if st.session_state.manage_mode else "管理"
            if st.button(label, use_container_width=True):
                st.session_state.manage_mode = not st.session_state.manage_mode
                st.rerun()

        st.divider()
        st.caption("历史记录")

        resp = _get("/sessions")
        sessions = resp.json().get("sessions", []) if resp and resp.status_code == 200 else []

        if sessions:
            for s in sessions:
                tid = s["thread_id"]
                cur = tid == st.session_state.current_thread_id
                title = (s["first_message"] or tid)[:36]
                meta = f"{s['message_count']}条 · {s['updated_at']}"

                if st.session_state.manage_mode:
                    col_t, col_d = st.columns([5, 1])
                    with col_t:
                        if st.button(title, key=f"sm_{tid}", use_container_width=True):
                            _remove(tid)
                            st.rerun()
                    with col_d:
                        if st.button("×", key=f"sd_{tid}", use_container_width=True):
                            _remove(tid)
                            st.rerun()
                elif cur:
                    st.markdown(
                        f'<div class="cap-cur">{title}<br>'
                        f'<span class="cap-cur-meta">{meta}</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button(title, key=f"s_{tid}", use_container_width=True):
                        _switch(tid)
                        st.rerun()
        else:
            st.caption("暂无对话")

    # ── 任务 ────────────────────────────────────────
    with tab_cron:
        st.subheader("定时任务")
        resp = _get("/jobs")
        jobs = resp.json().get("jobs", []) if resp and resp.status_code == 200 else []
        if jobs:
            for job in jobs:
                icon = {"active": "🟢", "paused": "⏸️", "queued": "⏳", "running": "🔄"}.get(job.get("status"), "⚪")
                t = "🔄" if job.get("type") == "recurring" else "📌"
                with st.expander(f"{icon} {t} {job.get('name', 'unnamed')}"):
                    st.text(f"调度: {job.get('schedule', '-')}")
                    rs = job.get("last_run_status") or "-"
                    rs_icon = "✅" if rs == "success" else ("❌" if rs == "failed" else "⚪")
                    st.text(f"上次: {rs_icon} {rs}")
                    st.text(f"下次: {job.get('next_run_at', '-')[:19]}")
                    if st.button("删除", key=f"del_{job['id']}"):
                        _post("/chat", {"prompt": f"删除定时任务 {job['id']}"}, timeout=60)
                        st.rerun()
        else:
            st.caption("暂无定时任务")

        st.divider()
        st.subheader("通知")
        resp = _get("/notifications?unread=true&limit=10")
        notifications = resp.json().get("notifications", []) if resp and resp.status_code == 200 else []
        st.session_state.unread_count = len(notifications)
        if notifications:
            for n in reversed(notifications):
                d = n["data"]
                icon = "✅" if d.get("status") == "success" else "❌"
                ts = n["timestamp"][:16]
                with st.expander(f"{icon} {d.get('job_name', '未命名')}"):
                    st.text(d.get("message", "")[:200])
                    if st.button("已读", key=f"r_{n['id']}"):
                        _post("/notifications/read", {"ids": [n["id"]]}, timeout=5)
                        st.rerun()
        else:
            st.caption("暂无未读通知")


# ── 主内容区 ────────────────────────────────────────

prompt = st.chat_input("输入消息...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            response = _send(prompt)
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()

elif st.session_state.messages:
    # 有历史记录 — 显示完整聊天
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

else:
    # 无消息 — 显示欢迎页
    st.markdown("""
    <div style="text-align: center; padding: 80px 20px 20px;">
        <div style="font-size: 2.8em; margin-bottom: 16px;">🤖</div>
        <h1 class="cap-title" style="font-size: 1.6em; font-weight: 600; margin: 0 0 6px;">
            ✨ 你好，欢迎使用 Capricorn
        </h1>
        <p class="cap-sub" style="font-size: 0.9em; margin: 0 0 36px;">
            解答问题 · 编写代码 · 数据分析 · 方案规划
        </p>
    </div>
    """, unsafe_allow_html=True)

    health = _get("/health")
    if not (health and health.status_code == 200):
        st.warning("Gateway 未连接。请先启动：`python run.py --mode gateway_with_webui`")

    cols = st.columns(5)
    for col, (label, prefix) in zip(cols, [
        ("💻 代码编写", "帮我编写一段代码："),
        ("💡 问题解答", "我有一个问题想问你："),
        ("📊 数据分析", "帮我分析一下这份数据："),
        ("🎯 方案规划", "帮我规划一个方案："),
        ("📝 文档生成", "帮我生成一份文档："),
    ]):
        with col:
            if st.button(label, use_container_width=True):
                st.session_state._pending = prefix

    if st.session_state.get("_pending"):
        p = st.session_state.pop("_pending")
        st.session_state.messages.append({"role": "user", "content": p})
        with st.chat_message("user"):
            st.markdown(p)
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                r = _send(p)
            st.markdown(r)
        st.session_state.messages.append({"role": "assistant", "content": r})
        st.rerun()


# ── 通知轮询 ────────────────────────────────────────

try:
    @st.fragment(run_every="10s")
    def _poll():
        try:
            resp = requests.get(f"{API_BASE}/notifications?unread=true&limit=10", timeout=5)
            n = len(resp.json().get("notifications", []))
            if n > st.session_state.unread_count:
                st.toast(f"📬 {n - st.session_state.unread_count} 条新通知")
                st.session_state.unread_count = n
                st.rerun()
            st.session_state.unread_count = n
        except Exception:
            pass
    _poll()
except Exception:
    pass