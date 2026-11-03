"""
Modular UI Components: Telemetry Header, Node Micro-Cards, Terminal & History Feed.
Optimized for Mobile Portrait & Desktop.
"""

import streamlit as st
import json

def render_telemetry_header(status_or_summary, wstats=None, iteration: int = 0):
    if isinstance(status_or_summary, dict):
        total = status_or_summary.get("total", 0)
        ready_n = status_or_summary.get("ready", 0)
        limit_n = status_or_summary.get("cooldown", 0)
        error_n = status_or_summary.get("error", 0)
        provider = status_or_summary.get("provider", "AI").upper()
        model = status_or_summary.get("model", "")
        
        d_active = wstats.get("daemon_active", False) if isinstance(wstats, dict) else False
        total_sent = wstats.get("total_sent", 0) if isinstance(wstats, dict) else 0

        daemon_badge = f'<span style="color: #38BDF8;">● AUTO 24/7</span>' if d_active else '<span style="color: #64748B;">○ IDLE</span>'

        st.markdown(f"""
        <div class="compact-header">
            <div class="title-badge">
                <span>⚡ {provider} CLUSTER</span>
                <span style="font-size: 0.65rem; background: rgba(56,189,248,0.1); border: 1px solid rgba(56,189,248,0.3); padding: 1px 5px; border-radius: 4px;">{model}</span>
                {daemon_badge}
            </div>
            <div class="stats-inline">
                <div>READY: <span style="color: #10B981;">{ready_n}/{total}</span></div>
                <div>COOLDOWN: <span style="color: #F43F5E;">{limit_n}</span></div>
                <div>ERROR: <span style="color: #F59E0B;">{error_n}</span></div>
                <div>SENT: <span style="color: #38BDF8;">{total_sent:,}</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Fallback list format
        summary = status_or_summary or []
        ready_n = sum(1 for s in summary if s.get("status") == "READY")
        limit_n = sum(1 for s in summary if s.get("status") == "RATE_LIMITED")
        st.markdown(f"""
        <div class="compact-header">
            <div class="title-badge"><span>⚡ CLUSTER</span></div>
            <div class="stats-inline">
                <div>READY: <span style="color: #10B981;">{ready_n}/{len(summary)}</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_node_cards(nodes: list):
    if not nodes:
        st.info("Belum ada node yang terkonfigurasi.")
        return

    cols = st.columns(len(nodes))
    for col, node in zip(cols, nodes):
        with col:
            stt = node.get("status", "").lower()
            label = node.get("label", node.get("id", "Node"))
            sent = node.get("total_sent", 0)
            
            if stt == "ready":
                status_cls = "ready"
                dot = '<span class="pulse-dot dot-green"></span>'
                status_text = '<span style="color: #10B981; font-weight:600;">READY</span>'
                sub = f"Sent: {sent}"
            elif stt == "cooldown":
                status_cls = "limit"
                dot = '<span class="pulse-dot dot-red"></span>'
                cd = node.get("cooldown_remaining", 0)
                status_text = '<span style="color: #F43F5E; font-weight:600;">LIMIT</span>'
                sub = f"⏳ {cd}s"
            elif stt == "working":
                status_cls = "ready"
                dot = '<span class="pulse-dot dot-green"></span>'
                status_text = '<span style="color: #38BDF8; font-weight:600;">WORKING</span>'
                sub = "Processing..."
            else:
                status_cls = "nokey"
                dot = '<span class="pulse-dot dot-amber"></span>'
                status_text = '<span style="color: #F59E0B; font-weight:600;">NO KEY</span>'
                sub = "Unconfigured"

            st.markdown(f"""
            <div class="micro-node {status_cls}">
                <div>
                    <span style="font-weight: 600; color: #E2E8F0;">{label}</span>
                </div>
                <div style="text-align: right;">
                    <div>{dot}{status_text}</div>
                    <div style="font-size: 0.65rem; color: #64748B;">{sub}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)


def render_terminal_stream(logs: list, is_active: bool = False):
    rows_html = []
    for item in logs[-60:]:
        if isinstance(item, tuple) and len(item) == 3:
            ts, tag, msg = item
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
        else:
            # String log biasa: [HH:MM:SS] Pesan
            line = str(item)
            safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows_html.append(f"""
            <div class="row-log">
                <span>{safe_line}</span>
            </div>
            """)

    term_content = "".join(rows_html) if rows_html else '<div style="color: #475569;">// Console ready. Waiting for events...</div>'

    st.markdown(f"""
    <div class="term-box">
        <div class="term-head">
            <div>CONSOLE STREAM</div>
            <div>STATUS: {'ACTIVE' if is_active else 'READY'}</div>
        </div>
        <div class="term-body">
            {term_content}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_history_feed(invocations_or_nodes: list):
    if not invocations_or_nodes:
        st.caption("Belum ada riwayat aktivitas.")
        return

    for item in invocations_or_nodes:
        if isinstance(item, dict) and "last_response" in item and item["last_response"]:
            label = item.get("label", item.get("id", "Node"))
            with st.expander(f"📌 {label} — Respons Terakhir"):
                st.markdown(item["last_response"])
        elif isinstance(item, dict) and "response" in item:
            with st.expander(f"[{item.get('timestamp', '')}] {item.get('account_name', 'Node')}"):
                st.markdown(f"**Prompt:** {item.get('prompt', '')}")
                st.markdown(f"**Response:** {item.get('response', '')}")


# Alias backward compatibility
render_terminal = render_terminal_stream
render_feed = render_history_feed
