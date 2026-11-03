"""
Main Streamlit App — AI Cluster Orchestrator (Gemini & Groq)
Cyberpunk Dashboard | Multi-Key Pooling | 24/7 Auto-Looping
"""

import time
import streamlit as st

from ui.auth import check_auth
from ui.styles import inject_css
from ui.components import render_telemetry_header, render_node_cards, render_terminal, render_feed

from src.worker import (
    get_pool, get_stats, get_logs, get_chat_history, clear_chat_history,
    run_single_task, start_daemon, stop_daemon, daemon_is_running,
)
from src.client import GeminiClient, GroqClient

# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Cluster Orchestrator",
    page_icon="⚡",
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
    ["⚡ CONTROLLER", "📡 CHAT & FEED", "🔑 VAULT", "⚙️ CONFIG"]
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
            "Prompt Loop", value="lanjut", key="prompt_input",
            help="Perintah yang dikirimkan ke model AI secara berkala"
        )

    with col_b:
        interval = st.number_input(
            "Interval (detik)", min_value=15, max_value=3600,
            value=60, step=5, key="interval_input",
            help="Jeda waktu antar eksekusi sukses"
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
    col_send, col_stats = st.columns([1, 2])
    with col_send:
        if st.button("📤 Kirim Sekali (Manual)", use_container_width=True):
            with st.spinner(f"Mengirim ke {status['provider'].upper()}..."):
                result = run_single_task(prompt=prompt_text)
            if result["success"]:
                st.success(f"✅ [{result['node_id']}] Berhasil!")
            else:
                st.error(f"❌ {result['error']}")

        if st.button("🧹 Reset Thread Memory", use_container_width=True, help="Bersihkan riwayat percakapan untuk memulai sesi baru"):
            clear_chat_history()
            st.info("Riwayat chat di-reset!")
            st.rerun()

    with col_stats:
        d_badge = "🟢 BERJALAN (24/7)" if daemon_is_running() else "🔴 IDLE"
        st.metric("Status Daemon", d_badge)
        st.metric("Total Terkirim", wstats.get("total_sent", 0))
        st.metric("Sukses / Gagal", f"{wstats.get('total_success', 0)} / {wstats.get('total_failed', 0)}")
        st.caption(f"Aktif di: **{status['provider'].upper()}** | Model: `{status['model']}` | Turn Memory: {wstats.get('history_count', 0)}")

# ══════════════════════════════════════════════════════════════
# TAB 2: CHAT & FEED
# ══════════════════════════════════════════════════════════════
with tab_feed:
    col_feed1, col_feed2 = st.columns([1, 1])

    with col_feed1:
        st.markdown("### 🖥️ Terminal Log")
        logs = get_logs(max_lines=120)
        render_terminal(logs)
        if st.button("🔄 Refresh Terminal"):
            st.rerun()

    with col_feed2:
        st.markdown("### 💬 Active Conversation History")
        history = get_chat_history()
        if not history:
            st.info("Belum ada riwayat percakapan aktif. Kirim pesan untuk memulai.")
        else:
            # Tampilkan 10 pesan terakhir
            for msg in history[-10:]:
                role = "🧑 User" if msg["role"] == "user" else "🤖 AI"
                with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                    st.markdown(f"**{role}:**")
                    st.markdown(msg["content"])

# ══════════════════════════════════════════════════════════════
# TAB 3: VAULT — Diagnostic & Key Test
# ══════════════════════════════════════════════════════════════
with tab_vault:
    st.markdown("### 🔑 Quick Diagnostic & Key Test")
    st.info(
        "Anda dapat mengetes API Key secara langsung dari sini, "
        "atau simpan secara permanen di **Streamlit Cloud Settings → Secrets**.",
        icon="ℹ️"
    )

    t_gemini, t_groq = st.tabs(["Google Gemini", "Groq Cloud"])

    with t_gemini:
        gemini_test_key = st.text_input("Gemini API Key", type="password", key="vault_gemini_key",
                                        placeholder="AIzaSy... atau AQ...")
        gemini_test_model = st.selectbox("Model", ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"], key="vault_gemini_model")
        if st.button("🔌 Ping Test Gemini"):
            if not gemini_test_key:
                st.warning("Masukkan Gemini API Key terlebih dahulu.")
            else:
                with st.spinner("Menguji koneksi ke Google Gemini API..."):
                    c = GeminiClient(api_key=gemini_test_key, model=gemini_test_model)
                    ok, msg = c.test_connection()
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with t_groq:
        groq_test_key = st.text_input("Groq API Key", type="password", key="vault_groq_key",
                                      placeholder="gsk_...")
        groq_test_model = st.selectbox("Model", ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"], key="vault_groq_model")
        if st.button("🔌 Ping Test Groq"):
            if not groq_test_key:
                st.warning("Masukkan Groq API Key terlebih dahulu.")
            else:
                with st.spinner("Menguji koneksi ke Groq Cloud API..."):
                    c = GroqClient(api_key=groq_test_key, model=groq_test_model)
                    ok, msg = c.test_connection()
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    st.markdown("---")
    st.markdown("#### 📋 Format `st.secrets` di Streamlit Cloud")
    st.markdown("Salin contoh template berikut ke **Streamlit Cloud Dashboard → Settings → Secrets**:")

    st.code("""pw = "zxcvbnm3142"

# Pilih provider: "gemini" atau "groq"
MODEL_PROVIDER = "groq"

# ── Konfigurasi GROQ (Llama 3.3 70B gratis) ──
GROQ_MODEL = "llama-3.3-70b-versatile"
# Single key:
GROQ_API_KEY = "gsk_xxxxxxx"
# Atau Multi-key pooling (jika punya beberapa key):
# GROQ_API_KEY_1 = "gsk_xxxxxxx1"
# GROQ_API_KEY_2 = "gsk_xxxxxxx2"

# ── Konfigurasi Google GEMINI ──
GEMINI_MODEL = "gemini-2.0-flash"
# Single key:
GEMINI_API_KEY = "AQ.xxxxxxx"
# Atau Multi-key pooling:
# GEMINI_API_KEY_1 = "AQ.xxxxxxx1"
# GEMINI_API_KEY_2 = "AQ.xxxxxxx2"
""", language="toml")

# ══════════════════════════════════════════════════════════════
# TAB 4: CONFIG
# ══════════════════════════════════════════════════════════════
with tab_cfg:
    st.markdown("### ⚙️ Cluster Settings")

    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        sel_prov = st.selectbox(
            "Ganti Provider Aktif",
            ["gemini", "groq"],
            index=0 if status["provider"] == "gemini" else 1,
            key="cfg_provider_sel"
        )
    with col_cfg2:
        if sel_prov == "gemini":
            models_avail = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        else:
            models_avail = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]

        sel_model = st.selectbox("Pilih Model", models_avail, key="cfg_model_sel")

    if st.button("💾 Terapkan Provider & Model"):
        pool.set_provider_and_model(sel_prov, sel_model)
        st.success(f"Aktif: {sel_prov.upper()} — {sel_model}")
        st.rerun()

    st.markdown("---")
    if st.button("🔄 Reload Secrets dari Cloud"):
        pool.reload()
        st.success("Config dan secrets berhasil dimuat ulang!")
        st.rerun()

# ── Auto-refresh saat daemon aktif ───────────────────────────
if daemon_is_running():
    time.sleep(5)
    st.rerun()
