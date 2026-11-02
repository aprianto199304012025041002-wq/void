"""
Modular UI Components: Telemetry Header, Node Micro-Cards, Terminal & History Feed.
Optimized for Mobile Portrait & Desktop.
"""

import streamlit as st

def render_telemetry_header(summary: list, daemon_running: bool, iteration: int):
    ready_n = sum(1 for s in summary if s["status"] == "READY")
    limit_n = sum(1 for s in summary if s["status"] == "RATE_LIMITED")
    nokey_n = sum(1 for s in summary if s["status"] == "NO_KEY")
    total_t = sum(s.get("total_tasks", 0) for s in summary)

    daemon_badge = f'<span style="color: #38BDF8;">● AUTO (#{iteration})</span>' if daemon_running else '<span style="color: #64748B;">○ IDLE</span>'

    st.markdown(f"""
    <div class="compact-header">
        <div class="title-badge">
            <span>⚡ CLAUDE POOL</span>
            <span style="font-size: 0.65rem; background: rgba(56,189,248,0.1); border: 1px solid rgba(56,189,248,0.3); padding: 1px 5px; border-radius: 4px;">PROD</span>
            {daemon_badge}
        </div>
        <div class="stats-inline">
            <div>READY: <span style="color: #10B981;">{ready_n}/{len(summary)}</span></div>
            <div>COOLDOWN: <span style="color: #F43F5E;">{limit_n}</span></div>
            <div>UNCONFIG: <span style="color: #F59E0B;">{nokey_n}</span></div>
            <div>PROCESSED: <span style="color: #38BDF8;">{total_t:,}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_node_cards(summary: list):
    node_cols = st.columns(len(summary))
    for col, s in zip(node_cols, summary):
        with col:
            if s["status"] == "READY":
                status_cls = "ready"
                dot = '<span class="pulse-dot dot-green"></span>'
                status_text = '<span style="color: #10B981; font-weight:600;">READY</span>'
                sub = f"Tasks: {s['total_tasks']}"
            elif s["status"] == "RATE_LIMITED":
                status_cls = "limit"
                dot = '<span class="pulse-dot dot-red"></span>'
                status_text = '<span style="color: #F43F5E; font-weight:600;">LIMIT</span>'
                sub = f"⏱ {s['cooldown'].split(' ')[0]}"
            else:
                status_cls = "nokey"
                dot = '<span class="pulse-dot dot-amber"></span>'
                status_text = '<span style="color: #F59E0B; font-weight:600;">NO KEY</span>'
                sub = "Needs setup"

            st.markdown(f"""
            <div class="micro-node {status_cls}">
                <div>
                    <span style="color: #64748B; font-weight: 600;">N0{s['id']}</span>
                    <span style="font-weight: 500; margin-left: 3px; color: #E2E8F0;">{s['name'][:10]}</span>
                </div>
                <div style="text-align: right;">
                    <div>{dot}{status_text}</div>
                    <div style="font-size: 0.65rem; color: #64748B;">{sub}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

def render_terminal_stream(logs: list, is_active: bool):
    rows_html = []
    for ts, tag, msg in logs[-60:]:
        tag_cls = {
            "INFO": "c-info", "SUCCESS": "c-succ", "WARN": "c-warn", "ERROR": "c-err", "LOOP": "c-loop"
        }.get(tag, "c-info")
        safe_msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows_html.append(f"""
        <div class="row-log">
            <span class="ts">{ts}</span>
            <span class="{tag_cls}">[{tag}]</span>
            <span>{safe_msg}</span>
        </div>
        """)
    term_content = "".join(rows_html) if rows_html else '<div style="color: #475569;">// Console ready. Waiting for events...</div>'

    st.markdown(f"""
    <div class="term-box">
        <div class="term-head">
            <div>CONSOLE STREAM</div>
            <div>STATUS: {'ACTIVE' if is_active else 'IDLE'}</div>
        </div>
        <div class="term-body">
            {term_content}
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_history_feed(invocations: list):
    """
    Menampilkan daftar perintah yang dikirim & respon lengkap yang diterima dari semua akun.
    """
    if not invocations:
        st.caption("Belum ada riwayat interaksi tersimpan.")
        return

    col_flt, col_dl = st.columns([3, 1])
    with col_flt:
        acc_filter = st.selectbox(
            "Filter Akun", 
            options=["Semua Node"] + sorted(list(set(f"Node #{inv['account_id']} ({inv['account_name']})" for inv in invocations))),
            label_visibility="collapsed"
        )
    with col_dl:
        import json
        st.download_button(
            "⬇️ Export",
            data=json.dumps(invocations, indent=2, ensure_ascii=False),
            file_name="claude_cluster_history.json",
            mime="application/json",
            use_container_width=True
        )

    for item in invocations:
        node_label = f"Node #{item['account_id']} ({item['account_name']})"
        if acc_filter != "Semua Node" and node_label != acc_filter:
            continue

        with st.expander(f"[{item['timestamp']}] N0{item['account_id']} • {item['mode']} • {item['prompt'][:35]}... ({item['length']:,}c)"):
            st.markdown(f"**📤 Prompt Terkirim:**")
            st.code(item["prompt"], language="text")
            st.markdown(f"**📥 Respons dari {item['account_name']}:**")
            st.markdown(item["response"])
