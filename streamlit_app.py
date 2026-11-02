"""
⚡ CLAUDE CLUSTER CONSOLE — ULTRA-COMPACT EDITION
Modular Entry Point
"""

import streamlit as st
import threading
import time
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from src.pool import ClusterPool
from src.worker import GlobalWorkerState, run_single_task, run_auto_daemon
from src.client import ClaudeWebClient
from ui.styles import inject_styles
from ui.auth import require_auth
from ui.components import render_telemetry_header, render_node_cards, render_terminal_stream

# Page Config
st.set_page_config(
    page_title="CLAUDE CONSOLE",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Injeksi CSS
inject_styles()

# Gatekeeper Password Auth
if not require_auth():
    st.stop()

# State & Pool Init
if "global_state" not in st.session_state:
    st.session_state.global_state = GlobalWorkerState()

GSTATE = st.session_state.global_state
pool = ClusterPool(BASE_DIR)
summary = pool.get_status_summary()

# Render Top Telemetry & Micro Node Cards
render_telemetry_header(summary, GSTATE.auto_running, GSTATE.auto_iteration)
render_node_cards(summary)

# Main Split-Screen Layout
col_ctrl, col_term = st.columns([5, 7])

with col_ctrl:
    tabs = st.tabs(["🚀 CONTROLLER", "🔑 VAULT (KEYS)", "⚙️ CONFIG"])
    
    with tabs[0]:
        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        prompt_val = st.text_input("Payload / Command", value="lanjut", label_visibility="collapsed", placeholder="Type instruction or 'lanjut'...")
        
        b1, b2, b3 = st.columns([3, 3, 2])
        with b1:
            if st.button("⚡ Run Once", type="primary", disabled=GSTATE.task_running or GSTATE.auto_running, use_container_width=True):
                if prompt_val.strip():
                    t = threading.Thread(target=run_single_task, args=(GSTATE, pool, prompt_val), daemon=True)
                    t.start()
                    st.rerun()
        with b2:
            if not GSTATE.auto_running:
                if st.button("▶ Start 24/7 Loop", disabled=GSTATE.task_running, use_container_width=True):
                    GSTATE.auto_stop_event.clear()
                    GSTATE.auto_running = True
                    GSTATE.auto_iteration = 0
                    t = threading.Thread(target=run_auto_daemon, args=(GSTATE, pool, 100, prompt_val, True), daemon=True)
                    t.start()
                    st.rerun()
            else:
                if st.button("⏹ Stop Daemon", type="secondary", use_container_width=True):
                    GSTATE.auto_stop_event.set()
                    GSTATE.auto_running = False
                    st.rerun()
        with b3:
            if st.button("🔃 Sync", use_container_width=True):
                st.rerun()

        if GSTATE.auto_running and GSTATE.sleeping_until_str:
            st.info(f"🛌 **Cluster Sleeping**: Resuming automatically at **{GSTATE.sleeping_until_str}**")

        if GSTATE.task_result:
            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            with st.expander(f"📄 Response ({GSTATE.task_account})", expanded=True):
                st.markdown(GSTATE.task_result)

    with tabs[1]:
        st.caption("Inspect `claude.ai` -> F12 -> Cookies -> `sessionKey`")
        v_updated = False
        for acc in pool.config.get("accounts", []):
            c_k, c_p = st.columns([3, 1])
            with c_k:
                n_key = st.text_input(f"N0{acc['id']} key", value=acc.get("session_key", ""), type="password", key=f"k_{acc['id']}")
            with c_p:
                st.write("")
                if st.button("Ping", key=f"p_{acc['id']}", use_container_width=True):
                    if n_key.strip():
                        test_cli = ClaudeWebClient(n_key.strip())
                        ok, msg = test_cli.test_connection()
                        if ok: st.success("OK")
                        else: st.error("ERR")
            if n_key != acc.get("session_key"):
                acc["session_key"] = n_key.strip()
                v_updated = True
        if v_updated or st.button("Save Keys", type="primary", use_container_width=True):
            pool.save_config()
            st.success("Keys saved!")
            st.rerun()

    with tabs[2]:
        cd_h = st.number_input("Cooldown (Hours)", 1.0, 12.0, float(pool.config.get("cooldown_hours", 5.0)), 0.5)
        if st.button("Save Config", use_container_width=True):
            pool.config["cooldown_hours"] = cd_h
            pool.save_config()
            st.success("Saved")
        if st.button("Reset Cooldown Lockouts", use_container_width=True):
            for acc in pool.state["accounts"].values():
                acc["status"] = "ready"
                acc["available_at"] = 0
            pool.save_state()
            st.success("Reset OK")
            st.rerun()

with col_term:
    render_terminal_stream(GSTATE.task_logs, is_active=(GSTATE.auto_running or GSTATE.task_running))

# Realtime polling
if GSTATE.auto_running or GSTATE.task_running:
    time.sleep(3)
    st.rerun()
