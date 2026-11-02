"""
⚡ CLAUDE CLUSTER CONSOLE — ULTRA-COMPACT EDITION
High-Density DevOps Interface • Single-View Layout • No Scrolling Required
Cloud-Native • 100% Streamlit Cloud Resilient
"""

import streamlit as st
import threading
import time
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from account_manager import AccountManager
from claude_api_client import ClaudeWebClient, ClaudeRateLimitError, ClaudeAuthError, ClaudeAPIError

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL WORKER STATE (Thread-Safe)
# ──────────────────────────────────────────────────────────────────────────────
class GlobalWorkerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.task_running = False
        self.task_logs = []
        self.task_result = None
        self.task_error = None
        self.task_account = None

        self.auto_running = False
        self.auto_logs = []
        self.auto_iteration = 0
        self.auto_max = 100
        self.infinite_mode = True
        self.sleeping_until_str = ""
        self.auto_stop_event = threading.Event()

    def log(self, tag: str, text: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.task_logs.append((ts, tag, text))

if "global_state" not in st.session_state:
    st.session_state.global_state = GlobalWorkerState()

GSTATE = st.session_state.global_state
acc_mgr = AccountManager(BASE_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# ULTRA-COMPACT HIGH-DENSITY CSS
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CLAUDE CONSOLE",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
/* Reset padding & margin for maximum screen real estate */
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    max-width: 100% !important;
}
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
    color: #CBD5E1;
}
code, pre, .mono {
    font-family: 'Fira Code', monospace !important;
}

/* Background */
.stApp {
    background-color: #06090E;
}

/* Compact Top Header Bar */
.compact-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 16px;
    background: #0B111A;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    margin-bottom: 10px;
}
.compact-header .title-badge {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: 'Fira Code', monospace;
    font-size: 0.85rem;
    font-weight: 700;
    color: #38BDF8;
}
.compact-header .stats-inline {
    display: flex;
    gap: 16px;
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    color: #94A3B8;
}
.compact-header .stats-inline span {
    font-weight: 600;
}

/* Micro Node Cards */
.micro-node {
    background: #0B111A;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 6px;
    padding: 6px 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
}
.micro-node.ready { border-left: 3px solid #10B981; }
.micro-node.limit { border-left: 3px solid #F43F5E; }
.micro-node.nokey { border-left: 3px solid #F59E0B; }

.pulse-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-right: 5px;
}
.dot-green { background: #10B981; box-shadow: 0 0 6px #10B981; }
.dot-red   { background: #F43F5E; box-shadow: 0 0 6px #F43F5E; }
.dot-amber { background: #F59E0B; }

/* Ultra-Compact Terminal */
.term-box {
    background: #04060A;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    height: 520px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.term-head {
    background: #0B111A;
    padding: 6px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: 'Fira Code', monospace;
    font-size: 0.7rem;
    color: #64748B;
}
.term-body {
    padding: 10px 14px;
    overflow-y: auto;
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    line-height: 1.6;
    color: #94A3B8;
    flex-grow: 1;
}
.row-log { display: flex; gap: 8px; margin-bottom: 2px; }
.ts { color: #475569; }
.c-info { color: #38BDF8; font-weight: 600; }
.c-succ { color: #34D399; font-weight: 600; }
.c-warn { color: #FBBF24; font-weight: 600; }
.c-err  { color: #F87171; font-weight: 600; }
.c-loop { color: #818CF8; font-weight: 600; }

/* Tight Controls container */
.ctrl-panel {
    background: #0B111A;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 8px;
    padding: 12px 14px;
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# WORKERS
# ──────────────────────────────────────────────────────────────────────────────
def _thread_single_task(prompt_text: str):
    GSTATE.task_running = True
    GSTATE.task_result = None
    GSTATE.task_error = None
    GSTATE.log("INFO", f"Task queued: '{prompt_text[:45]}...'")
    
    max_attempts = len(acc_mgr.config.get("accounts", []))
    attempts = 0
    success = False

    while attempts < max_attempts:
        account = acc_mgr.get_available_account()
        if not account:
            GSTATE.log("WARN", "Pool lock: All nodes in cooldown or unconfigured.")
            GSTATE.task_error = "All nodes rate-limited or missing sessionKey."
            break

        GSTATE.log("INFO", f"Dispatched -> Node #{account['id']} [{account['name']}]")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            GSTATE.log("SUCCESS", f"Node #{account['id']} finished ({len(resp):,} chars).")
            GSTATE.task_result = resp
            GSTATE.task_account = account["name"]
            success = True
            break
        except ClaudeRateLimitError as e:
            GSTATE.log("WARN", f"Node #{account['id']} 5h limit. Auto-failover...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            attempts += 1
        except Exception as e:
            GSTATE.log("ERROR", f"Node #{account['id']} err: {e}")
            attempts += 1

    if not success and not GSTATE.task_error:
        GSTATE.task_error = "Execution failed across all nodes."
    GSTATE.task_running = False

def _thread_auto_runner(max_iter: int, prompt_text: str, infinite: bool):
    mode_tag = "INFINITE (24/7)" if infinite else f"{max_iter} ITER"
    GSTATE.log("LOOP", f"Daemon active [{mode_tag}]. Payload: '{prompt_text}'")
    GSTATE.infinite_mode = infinite
    
    i = 0
    while True:
        if GSTATE.auto_stop_event.is_set():
            GSTATE.log("WARN", "SIGINT received. Halting daemon loop.")
            break

        i += 1
        if not infinite and i > max_iter:
            GSTATE.log("SUCCESS", f"Target {max_iter} hit. Daemon idle.")
            break

        GSTATE.auto_iteration = i
        iter_display = f"#{i}" if infinite else f"#{i}/{max_iter}"
        GSTATE.log("INFO", f"Cycle {iter_display} starting...")

        account = acc_mgr.get_available_account()

        if not account:
            now = time.time()
            cooldown_list = []
            for a_id, a_data in acc_mgr.state.get("accounts", {}).items():
                avail_at = a_data.get("available_at", 0)
                if avail_at > now:
                    cooldown_list.append((avail_at - now, a_data.get("name", f"N0{a_id}")))

            if cooldown_list:
                cooldown_list.sort(key=lambda x: x[0])
                shortest_wait, next_name = cooldown_list[0]
                wait_min = max(1, int(shortest_wait // 60))
                wake_time = (datetime.now() + timedelta(seconds=shortest_wait)).strftime("%H:%M:%S")
                GSTATE.sleeping_until_str = wake_time
                
                GSTATE.log("WARN", f"ALL NODES COOLDOWN. {next_name} ready in ~{wait_min}m ({wake_time}). Sleeping...")
                
                sleep_deadline = time.time() + shortest_wait
                while time.time() < sleep_deadline:
                    if GSTATE.auto_stop_event.is_set():
                        break
                    time.sleep(10)
                
                if GSTATE.auto_stop_event.is_set():
                    break
                
                GSTATE.sleeping_until_str = ""
                GSTATE.log("INFO", "WAKE SIGNAL. Re-checking nodes...")
                acc_mgr.refresh_statuses()
                continue
            else:
                GSTATE.log("ERROR", "No active credentials in pool. Halting.")
                break

        GSTATE.log("INFO", f"Send -> Node #{account['id']} [{account['name']}]")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            GSTATE.log("SUCCESS", f"Node #{account['id']} answered ({len(resp):,} chars).")

            resp_lower = resp.lower()
            if any(sig in resp_lower for sig in ["seluruh audit selesai", "pekerjaan sudah selesai", "tidak ada lagi"]):
                GSTATE.log("SUCCESS", "Job completion pattern found. Exiting.")
                break
        except ClaudeRateLimitError as e:
            GSTATE.log("WARN", f"Node #{account['id']} 5h trip. Failover...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            i -= 1
            time.sleep(1)
            continue
        except Exception as e:
            GSTATE.log("ERROR", f"Node #{account['id']} error: {e}")

        if not GSTATE.auto_stop_event.is_set():
            time.sleep(5)

    GSTATE.log("INFO", "Daemon loop terminated.")
    GSTATE.auto_running = False
    GSTATE.sleeping_until_str = ""

# ──────────────────────────────────────────────────────────────────────────────
# COMPACT TOP TELEMETRY BAR
# ──────────────────────────────────────────────────────────────────────────────
summary = acc_mgr.get_status_summary()
ready_n = sum(1 for s in summary if s["status"] == "READY")
limit_n = sum(1 for s in summary if s["status"] == "RATE_LIMITED")
nokey_n = sum(1 for s in summary if s["status"] == "NO_KEY")
total_t = sum(s.get("total_tasks", 0) for s in summary)

daemon_badge = f'<span style="color: #38BDF8;">● AUTO-RUNNER (#{GSTATE.auto_iteration})</span>' if GSTATE.auto_running else '<span style="color: #64748B;">○ DAEMON IDLE</span>'

st.markdown(f"""
<div class="compact-header">
    <div class="title-badge">
        <span>⚡ CLAUDE POOL</span>
        <span style="font-size: 0.65rem; background: rgba(56,189,248,0.1); border: 1px solid rgba(56,189,248,0.3); padding: 2px 6px; border-radius: 4px;">PROD</span>
        {daemon_badge}
    </div>
    <div class="stats-inline">
        <div>ONLINE: <span style="color: #10B981;">{ready_n}/{len(summary)}</span></div>
        <div>COOLDOWN: <span style="color: #F43F5E;">{limit_n}</span></div>
        <div>UNCONFIGURED: <span style="color: #F59E0B;">{nokey_n}</span></div>
        <div>PROCESSED: <span style="color: #38BDF8;">{total_t:,}</span></div>
    </div>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# HORIZONTAL COMPACT NODES ROW
# ──────────────────────────────────────────────────────────────────────────────
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
                <span style="font-weight: 500; margin-left: 4px; color: #E2E8F0;">{s['name'][:12]}</span>
            </div>
            <div style="text-align: right;">
                <div>{dot}{status_text}</div>
                <div style="font-size: 0.65rem; color: #64748B;">{sub}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# MAIN SPLIT VIEW: CONTROLS (LEFT) vs TERMINAL (RIGHT)
# ──────────────────────────────────────────────────────────────────────────────
col_left, col_right = st.columns([5, 7])

with col_left:
    tabs = st.tabs(["🚀 CONTROLLER", "🔑 VAULT (KEYS)", "⚙️ CONFIG"])
    
    with tabs[0]:
        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        # Fast input
        prompt_val = st.text_input("Payload / Command", value="lanjut", label_visibility="collapsed", placeholder="Type instruction or 'lanjut'...")
        
        # Action Bar
        b_c1, b_c2, b_c3 = st.columns([3, 3, 2])
        with b_c1:
            if st.button("⚡ Run Once", type="primary", disabled=GSTATE.task_running or GSTATE.auto_running, use_container_width=True):
                if prompt_val.strip():
                    t = threading.Thread(target=_thread_single_task, args=(prompt_val,), daemon=True)
                    t.start()
                    st.rerun()
        with b_c2:
            if not GSTATE.auto_running:
                if st.button("▶ Start 24/7 Loop", disabled=GSTATE.task_running, use_container_width=True):
                    GSTATE.auto_stop_event.clear()
                    GSTATE.auto_running = True
                    GSTATE.auto_iteration = 0
                    t = threading.Thread(target=_thread_auto_runner, args=(100, prompt_val, True), daemon=True)
                    t.start()
                    st.rerun()
            else:
                if st.button("⏹ Stop Daemon", type="secondary", use_container_width=True):
                    GSTATE.auto_stop_event.set()
                    GSTATE.auto_running = False
                    st.rerun()
        with b_c3:
            if st.button("🔃 Sync", use_container_width=True):
                st.rerun()

        if GSTATE.auto_running and GSTATE.sleeping_until_str:
            st.info(f"🛌 **Cluster Sleeping**: Resuming automatically at **{GSTATE.sleeping_until_str}**")

        # Result box if single task finished
        if GSTATE.task_result:
            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            with st.expander(f"📄 Response ({GSTATE.task_account})", expanded=True):
                st.markdown(GSTATE.task_result)

    with tabs[1]:
        st.caption("Inspect `claude.ai` -> F12 -> Cookies -> `sessionKey`")
        accounts = acc_mgr.config.get("accounts", [])
        v_updated = False
        for acc in accounts:
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
            acc_mgr.save_config()
            st.success("Keys saved!")
            st.rerun()

    with tabs[2]:
        cd_h = st.number_input("Cooldown (Hours)", 1.0, 12.0, float(acc_mgr.config.get("cooldown_hours", 5.0)), 0.5)
        if st.button("Save Config", use_container_width=True):
            acc_mgr.config["cooldown_hours"] = cd_h
            acc_mgr.save_config()
            st.success("Saved")
        if st.button("Reset Cooldown Lockouts", use_container_width=True):
            for acc in acc_mgr.state["accounts"].values():
                acc["status"] = "ready"
                acc["available_at"] = 0
            acc_mgr.save_state()
            st.success("Reset OK")
            st.rerun()

with col_right:
    # High-density Terminal Console
    rows_html = []
    for ts, tag, msg in GSTATE.task_logs[-60:]:
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
            <div>CONSOLE OUTPUT STREAM</div>
            <div>STATUS: {'ACTIVE' if GSTATE.auto_running or GSTATE.task_running else 'IDLE'}</div>
        </div>
        <div class="term-body">
            {term_content}
        </div>
    </div>
    """, unsafe_allow_html=True)

# Auto-refresh loop for terminal stream
if GSTATE.auto_running or GSTATE.task_running:
    time.sleep(3)
    st.rerun()
