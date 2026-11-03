"""
Main Streamlit App — Claude Cluster Orchestrator
Cyberpunk UI | Claude Free Web Account Pool | TAPIR 24/7
"""

import time
import streamlit as st

from ui.auth import check_auth
from ui.styles import inject_css
from ui.components import render_telemetry_header, render_node_cards, render_terminal, render_feed

from src.worker import (
    get_pool, get_stats, get_logs,
    run_single_task, start_daemon, stop_daemon, daemon_is_running,
)
from src.client import ClaudeWebSessionClient

# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="TAPIR Cluster",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ── Auth gate ─────────────────────────────────────────────────
if not check_auth():
    st.stop()

# ── Pool ──────────────────────────────────────────────────────
pool = get_pool()

# ── Telemetry header ──────────────────────────────────────────
status = pool.get_status()
wstats = get_stats()
render_telemetry_header(status, wstats)

# ── Tabs ──────────────────────────────────────────────────────
tab_ctrl, tab_feed, tab_vault, tab_cfg = st.tabs(
    ["⚡ CONTROLLER", "📡 FEED", "🔑 VAULT", "⚙️ CONFIG"]
)

# ══════════════════════════════════════════════════════════════
# TAB 1: CONTROLLER
# ══════════════════════════════════════════════════════════════
with tab_ctrl:
    render_node_cards(status["nodes"])

    st.markdown("---")
    col_a, col_b, col_c = st.columns([2, 1, 1])

    with col_a:
        prompt_text = st.text_input(
            "Prompt", value="lanjut", key="prompt_input",
            help="Teks yang dikirim ke TAPIR conversation"
        )

    with col_b:
        interval = st.number_input(
            "Interval (detik)", min_value=30, max_value=3600,
            value=90, step=10, key="interval_input"
        )

    with col_c:
        st.markdown("<br>", unsafe_allow_html=True)
        if daemon_is_running():
            if st.button("⏹ STOP DAEMON", type="secondary", use_container_width=True):
                stop_daemon()
                st.rerun()
        else:
            if st.button("▶ START DAEMON", type="primary", use_container_width=True):
                start_daemon(prompt=prompt_text, interval_ok=interval)
                st.rerun()

    st.markdown("---")
    col_send, col_status = st.columns([1, 2])
    with col_send:
        if st.button("📤 Kirim Sekali", use_container_width=True):
            with st.spinner("Mengirim..."):
                result = run_single_task(prompt=prompt_text)
            if result["success"]:
                st.success(f"✅ [{result['node_id']}] Berhasil")
                st.text_area("Respon", value=result["response"], height=200, key="one_resp")
            else:
                st.error(f"❌ {result['error']}")

    with col_status:
        daemon_badge = "🟢 AKTIF" if daemon_is_running() else "🔴 IDLE"
        st.metric("Daemon Status", daemon_badge)
        st.metric("Total Terkirim", wstats.get("total_sent", 0))
        st.metric("Sukses / Gagal",
                  f"{wstats.get('total_success', 0)} / {wstats.get('total_failed', 0)}")

# ══════════════════════════════════════════════════════════════
# TAB 2: FEED
# ══════════════════════════════════════════════════════════════
with tab_feed:
    logs = get_logs(max_lines=150)
    render_terminal(logs)
    render_feed(status["nodes"])

    if st.button("🔄 Refresh Feed"):
        st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3: VAULT — Session Keys
# ══════════════════════════════════════════════════════════════
with tab_vault:
    st.markdown("### 🔑 Session Key & Koneksi")
    st.info(
        "Masukkan `sessionKey` cookie dari claude.ai untuk masing-masing akun. "
        "Format: `sk-ant-sid01-...`\n\n"
        "**Cara ambil:** Claude.ai → F12 → Application → Cookies → `sessionKey`",
        icon="ℹ️"
    )

    nodes = status["nodes"]
    for i, node in enumerate(nodes, start=1):
        with st.expander(f"🤖 {node['label']} (Akun {i})", expanded=(i == 1)):
            col1, col2 = st.columns([3, 1])
            with col1:
                key_val = st.text_input(
                    f"Session Key #{i}",
                    value=node.get("session_key", ""),
                    type="password",
                    placeholder="sk-ant-sid01-...",
                    key=f"sk_input_{i}",
                )
                conv_val = st.text_input(
                    f"TAPIR Conv ID #{i}",
                    value=node.get("tapir_conv_id", ""),
                    placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                    key=f"conv_input_{i}",
                )
            with col2:
                st.markdown("<br><br>", unsafe_allow_html=True)
                if st.button(f"🔌 Ping #{i}", key=f"ping_{i}"):
                    if key_val:
                        with st.spinner("Testing..."):
                            client = ClaudeWebSessionClient(
                                session_key=key_val,
                                conv_id=conv_val or "test",
                            )
                            ok, msg = client.test_connection()
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                    else:
                        st.warning("Session key kosong")

                status_badge = {
                    "ready":    "🟢 Ready",
                    "working":  "🔵 Working",
                    "cooldown": f"⏳ CD {node.get('cooldown_remaining', 0)}s",
                    "error":    "🔴 Error",
                }.get(node.get("status", "error"), "❓")
                st.markdown(f"**Status:** {status_badge}")

    st.markdown("---")
    st.markdown("#### 📋 Format Streamlit Secrets")
    st.markdown("Salin format ini ke **Streamlit Cloud → Settings → Secrets**:")
    st.code(
        """pw = "zxcvbnm3142"
MODEL_PROVIDER = "claude_web"

SESSION_KEY_1 = "sk-ant-sid01-XXXX"
SESSION_KEY_2 = "sk-ant-sid01-XXXX"
SESSION_KEY_3 = "sk-ant-sid01-XXXX"
SESSION_KEY_4 = "sk-ant-sid01-XXXX"

TAPIR_CONV_1 = "f51cbb3c-8d7e-455e-8598-236271016a47"
TAPIR_CONV_2 = "930c7ed1-62a8-475d-9a87-f22df858cde2"
TAPIR_CONV_3 = "03c28d45-23fe-4a5c-a08c-58d5511c268a"
TAPIR_CONV_4 = "f898f5a0-427c-4c3e-bad6-0c2955b986b5"
""",
        language="toml",
    )

# ══════════════════════════════════════════════════════════════
# TAB 4: CONFIG
# ══════════════════════════════════════════════════════════════
with tab_cfg:
    st.markdown("### ⚙️ Konfigurasi")

    st.markdown("**Provider aktif:**")
    provider = pool.model_provider
    st.success(f"🤖 `{provider}` — Claude Free Web (curl_cffi Chrome impersonation)")

    st.markdown("---")
    st.markdown("**Node Summary:**")
    for node in status["nodes"]:
        conv_short = node.get("tapir_conv_id", "")[:8] + "..." if node.get("tapir_conv_id") else "—"
        has_key = "✅" if node.get("session_key") else "❌"
        st.markdown(
            f"- **{node['label']}** | Key: {has_key} | Conv: `{conv_short}` | "
            f"Sent: {node.get('total_sent', 0)}"
        )

    st.markdown("---")
    if st.button("🔄 Reload Config dari Secrets"):
        pool.reload()
        st.success("Config direload!")
        st.rerun()

# ── Auto-refresh saat daemon aktif ───────────────────────────
if daemon_is_running():
    time.sleep(5)
    st.rerun()
