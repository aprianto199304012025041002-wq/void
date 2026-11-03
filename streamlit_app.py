"""
Autonomous Continuous Bug Hunter Dashboard
Audit repositori GitHub secara terus-menerus dan catat bug ke file Markdown (.md).
"""

import sys
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import time
import streamlit as st

from ui.auth import check_auth
from ui.styles import inject_css
from ui.components import render_telemetry_header, render_node_cards, render_terminal

from src.worker import (
    get_pool, get_stats, get_logs,
    get_bug_report_markdown, clear_bug_reports,
    start_bug_hunter, stop_bug_hunter, is_bug_hunter_running,
)
from src.github_scanner import GitHubRepoReader
from src.client import GeminiClient, GroqClient

# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Bug Hunter — Continuous Code Auditor",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

if not check_auth():
    st.stop()

pool = get_pool()
status = pool.get_status()
wstats = get_stats()

# Header status
col_h1, col_h2, col_h3, col_h4 = st.columns([2, 1, 1, 1])
with col_h1:
    daemon_st = "🟢 SCANNING 24/7" if is_bug_hunter_running() else "⚪ IDLE"
    st.markdown(f"### 🛡️ Bug Hunter: `{wstats.get('target_repo') or 'Belum ada target'}`")
with col_h2:
    st.metric("Status Auditor", daemon_st)
with col_h3:
    st.metric("File Diperiksa", wstats.get("total_files_scanned", 0))
with col_h4:
    st.metric("🚨 Bug Ditemukan", wstats.get("total_bugs_found", 0))

st.markdown("---")

tab_ctrl, tab_report, tab_console, tab_vault = st.tabs(
    ["🎯 AUDIT CONTROLLER", "📋 BUG REPORT (.MD)", "🖥️ CONSOLE LOG", "🔑 AI & SECRETS"]
)

# ══════════════════════════════════════════════════════════════
# TAB 1: AUDIT CONTROLLER
# ══════════════════════════════════════════════════════════════
with tab_ctrl:
    st.markdown("#### 🎯 Konfigurasi Target Repositori GitHub")

    # Auto-load target dari st.secrets jika ada
    sec = getattr(st, "secrets", {})
    default_target_repo = sec.get("TARGET_REPO", "aprianto199304012025041002-wq/void")
    default_target_pat = sec.get("TARGET_GITHUB_PAT", sec.get("GITHUB_PAT", ""))

    col_t1, col_t2 = st.columns([2, 2])
    with col_t1:
        target_repo = st.text_input(
            "Target Repository (owner/repo)",
            value=default_target_repo,
            placeholder="contoh: torvalds/linux atau username/my-project",
            key="hunter_target_repo",
        )
    with col_t2:
        target_pat = st.text_input(
            "GitHub Personal Access Token (Read-Only)",
            value=default_target_pat,
            type="password",
            placeholder="github_pat_... (opsional jika repo publik)",
            key="hunter_target_pat",
        )

    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    with col_btn1:
        if st.button("🔌 Uji Akses Repo", use_container_width=True):
            if not target_repo:
                st.warning("Masukkan format owner/repo terlebih dahulu.")
            else:
                with st.spinner("Menguji akses GitHub API..."):
                    reader = GitHubRepoReader(target_repo, target_pat)
                    ok, msg = reader.test_access()
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with col_btn2:
        interval_val = st.number_input(
            "Jeda Per-File (detik)", min_value=5, max_value=300, value=15, step=5,
            help="Waktu jeda antar pemeriksaan file untuk menghemat kuota RPM AI."
        )

    with col_btn3:
        st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        if is_bug_hunter_running():
            if st.button("⏹ STOP CONTINUOUS AUDIT", type="secondary", use_container_width=True):
                stop_bug_hunter()
                st.rerun()
        else:
            if st.button("▶ START CONTINUOUS BUG HUNTER", type="primary", use_container_width=True):
                if not target_repo:
                    st.error("Isi nama target repositori terlebih dahulu.")
                else:
                    start_bug_hunter(target_repo, target_pat, interval_sec=interval_val)
                    st.rerun()

    st.markdown("---")
    st.markdown("#### ⚡ AI Engine Status")
    render_node_cards(status["nodes"])
    if wstats.get("current_file"):
        st.caption(f"📂 File saat ini: `{wstats.get('current_file')}` | AI Provider: **{status['provider'].upper()}** (`{status['model']}`)")

# ══════════════════════════════════════════════════════════════
# TAB 2: BUG REPORT (.MD)
# ══════════════════════════════════════════════════════════════
with tab_report:
    report_md = get_bug_report_markdown()
    
    col_r1, col_r2 = st.columns([3, 1])
    with col_r1:
        st.markdown("### 📋 Laporan Bug Terdeteksi (Markdown)")
    with col_r2:
        st.download_button(
            "📥 Unduh Laporan (bug_report.md)",
            data=report_md,
            file_name="bug_report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        if st.button("🧹 Reset Laporan", use_container_width=True):
            clear_bug_reports()
            st.rerun()

    st.markdown(report_md)

# ══════════════════════════════════════════════════════════════
# TAB 3: CONSOLE LOG
# ══════════════════════════════════════════════════════════════
with tab_console:
    st.markdown("### 🖥️ Real-Time Audit Console")
    logs = get_logs(max_lines=150)
    render_terminal(logs, is_active=is_bug_hunter_running())
    if st.button("🔄 Refresh Console"):
        st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4: AI & SECRETS
# ══════════════════════════════════════════════════════════════
with tab_vault:
    st.markdown("### 🔑 Diagnostic AI Engine & Secrets")

    t_groq, t_gemini = st.tabs(["⚡ Groq Cloud", "🌐 Google Gemini"])

    with t_groq:
        stored_groq_key = pool.get_api_key_for("groq")
        groq_test_key = st.text_input("Groq API Key", value=stored_groq_key, type="password", key="v_groq_k")
        groq_test_model = st.selectbox("Model Groq", ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"], key="v_groq_m")
        if st.button("🔌 Ping Test Groq"):
            if groq_test_key:
                c = GroqClient(api_key=groq_test_key, model=groq_test_model)
                ok, msg = c.test_connection()
                st.success(msg) if ok else st.error(msg)

    with t_gemini:
        stored_gemini_key = pool.get_api_key_for("gemini")
        gemini_test_key = st.text_input("Gemini API Key", value=stored_gemini_key, type="password", key="v_gem_k")
        gemini_test_model = st.selectbox("Model Gemini", ["gemini-3-flash-preview", "gemini-3.8-flash"], key="v_gem_m")
        if st.button("🔌 Ping Test Gemini"):
            if gemini_test_key:
                c = GeminiClient(api_key=gemini_test_key, model=gemini_test_model)
                ok, msg = c.test_connection()
                st.success(msg) if ok else st.error(msg)

    st.markdown("---")
    st.markdown("#### 📋 Konfigurasi Streamlit Secrets untuk Bug Hunter")
    st.code("""pw = "zxcvbnm3142"

MODEL_PROVIDER = "groq"
GROQ_API_KEY = "gsk_..."
GROQ_MODEL = "qwen/qwen3.8-27b"

# (Opsional) Target Repo default & Read-only GitHub PAT
TARGET_REPO = "owner/repo"
TARGET_GITHUB_PAT = "github_pat_read_only_anda"
""", language="toml")

# ── Auto-refresh saat daemon aktif ───────────────────────────
if is_bug_hunter_running():
    time.sleep(5)
    st.rerun()
