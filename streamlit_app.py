"""
Autonomous Continuous Bug Hunter Dashboard — Multi-Repo Edition
Audit repositori GitHub secara terus-menerus dan catat bug ke file Markdown (.md).
Penyimpanan terisolasi per-repositori dengan Auto-Sync ke GitHub Branch 'audit-reports'.
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
from ui.components import render_node_cards, render_terminal

from src.worker import (
    get_pool, get_stats, get_logs,
    get_bug_report_markdown, get_available_repos_with_reports, clear_bug_reports,
    start_bug_hunter, stop_bug_hunter, is_bug_hunter_running,
)
from src.github_scanner import GitHubRepoReader, list_accessible_repos
from src.github_sync import get_safe_report_path
from src.client import GeminiClient, GroqClient

# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Bug Hunter — Multi-Repo Code Auditor",
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
    curr_target = wstats.get("current_repo") or (", ".join(wstats.get("target_repos", [])) if wstats.get("target_repos") else "Belum ada target")
    st.markdown(f"### 🛡️ Bug Hunter: `{curr_target[:35]}`")
with col_h2:
    st.metric("Status Auditor", daemon_st)
with col_h3:
    st.metric("File Diperiksa", wstats.get("total_files_scanned", 0))
with col_h4:
    st.metric("🚨 Total Bug Unik", wstats.get("total_bugs_found", 0))

st.markdown("---")

tab_ctrl, tab_report, tab_console, tab_vault = st.tabs(
    ["🎯 MULTI-REPO CONTROLLER", "📋 BUG REPORT PER REPO (.MD)", "🖥️ CONSOLE LOG", "🔑 AI & SECRETS"]
)

# ══════════════════════════════════════════════════════════════
# TAB 1: AUDIT CONTROLLER
# ══════════════════════════════════════════════════════════════
with tab_ctrl:
    st.markdown("#### 🎯 Konfigurasi Target Repositori GitHub")

    sec = getattr(st, "secrets", {})
    default_target_pat = sec.get("TARGET_GITHUB_PAT", sec.get("GITHUB_PAT", ""))

    col_pat1, col_pat2 = st.columns([3, 1])
    with col_pat1:
        target_pat = st.text_input(
            "GitHub Personal Access Token (Read-Only)",
            value=default_target_pat,
            type="password",
            placeholder="github_pat_...",
            key="hunter_target_pat",
        )
    with col_pat2:
        st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        detect_clicked = st.button("🔍 Deteksi Repo dari PAT", use_container_width=True)

    # Deteksi repo yang bisa diakses
    detected_repo_names = []
    if target_pat and (detect_clicked or "detected_repos" in st.session_state):
        if detect_clicked or "detected_repos" not in st.session_state:
            with st.spinner("Mengambil daftar repositori dari token PAT..."):
                repos = list_accessible_repos(target_pat)
                st.session_state.detected_repos = [r["full_name"] for r in repos]
        detected_repo_names = st.session_state.get("detected_repos", [])

    if detected_repo_names:
        selected_from_dropdown = st.multiselect(
            "Pilih Repositori Target (bisa pilih 1 atau beberapa repo sekaligus):",
            options=detected_repo_names,
            default=detected_repo_names[:3] if len(detected_repo_names) >= 3 else detected_repo_names,
            key="multi_repo_dropdown"
        )
        target_repos_input = ", ".join(selected_from_dropdown)
    else:
        default_target_repo = sec.get("TARGET_REPO", "aprianto199304012025041002-wq/tapir, aprianto199304012025041002-wq/kasper, aprianto199304012025041002-wq/gudeg")
        target_repos_input = st.text_input(
            "Target Repositories (pisahkan koma untuk multi-repo)",
            value=default_target_repo,
            placeholder="owner/repo1, owner/repo2, owner/repo3",
            key="hunter_target_repo",
        )

    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    with col_btn1:
        if st.button("🔌 Uji Akses Target", use_container_width=True):
            rlist = [r.strip() for r in target_repos_input.split(",") if r.strip()]
            if not rlist:
                st.warning("Masukkan minimal 1 repositori target.")
            else:
                for r in rlist:
                    reader = GitHubRepoReader(r, target_pat)
                    ok, msg = reader.test_access()
                    st.success(msg) if ok else st.error(msg)

    with col_btn2:
        interval_val = st.number_input(
            "Jeda Per-File (detik)", min_value=5, max_value=300, value=15, step=5,
            help="Waktu jeda antar pemeriksaan berkas."
        )

    with col_btn3:
        st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        if is_bug_hunter_running():
            if st.button("⏹ STOP CONTINUOUS AUDIT", type="secondary", use_container_width=True):
                stop_bug_hunter()
                st.rerun()
        else:
            if st.button("▶ START CONTINUOUS BUG HUNTER", type="primary", use_container_width=True):
                if not target_repos_input.strip():
                    st.error("Isi minimal 1 repositori target.")
                else:
                    start_bug_hunter(target_repos_input, target_pat, interval_sec=interval_val)
                    st.rerun()

    st.markdown("---")
    st.markdown("#### ⚡ AI Engine Status & Persistence")
    render_node_cards(status["nodes"])
    
    col_inf1, col_inf2 = st.columns(2)
    with col_inf1:
        if wstats.get("current_file"):
            st.caption(f"📂 Mengaudit: `[{wstats.get('current_repo')}] {wstats.get('current_file')}`")
    with col_inf2:
        st.caption(f"☁️ **GitHub Cloud Auto-Sync:** Aktif (branch `audit-reports`) | Last Sync: `{wstats.get('last_github_sync')}`")

# ══════════════════════════════════════════════════════════════
# TAB 2: BUG REPORT PER REPO (.MD)
# ══════════════════════════════════════════════════════════════
with tab_report:
    st.markdown("### 📋 Laporan Bug Terisolasi Per-Repositori")

    # Daftar repositori yang memiliki laporan
    active_repos_list = get_available_repos_with_reports()
    # Tambahkan repo yang saat ini ada di input jika belum ada di list
    input_repos = [r.strip() for r in target_repos_input.split(",") if r.strip()]
    all_known_repos = sorted(list(set(active_repos_list + input_repos)))

    if not all_known_repos:
        st.info("Belum ada repositori yang dipilih atau diaudit.")
    else:
        selected_report_repo = st.selectbox(
            "Pilih Repositori untuk Menampilkan / Mengunduh Laporan:",
            options=all_known_repos,
            key="selected_report_repo"
        )

        report_md = get_bug_report_markdown(selected_report_repo)
        safe_fname = selected_report_repo.replace("/", "_") + "_bug_report.md"

        col_r1, col_r2, col_r3 = st.columns([2, 1, 1])
        with col_r1:
            st.caption(f"📁 Laporan untuk: **{selected_report_repo}**")
        with col_r2:
            st.download_button(
                f"📥 Unduh {safe_fname}",
                data=report_md,
                file_name=safe_fname,
                mime="text/markdown",
                use_container_width=True,
            )
        with col_r3:
            if st.button("🧹 Reset Laporan Repo Ini", use_container_width=True):
                clear_bug_reports(selected_report_repo)
                st.rerun()

        st.info(f"☁️ Laporan repositori ini tersimpan secara mandiri di GitHub branch `audit-reports` pada jalur: `{get_safe_report_path(selected_report_repo)}`.")
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

# ── Auto-refresh saat daemon aktif ───────────────────────────
if is_bug_hunter_running():
    time.sleep(5)
    st.rerun()
