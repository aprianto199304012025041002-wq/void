"""
⚡ CLAUDE POOL ORCHESTRATOR — DEV CONSOLE EDITION
Professional Full-Stack DevOps & Orchestration Dashboard.
Cloud-Native • No PC Backend Required • 24/7 Resilient.
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
        self.start_timestamp = None
        self.auto_stop_event = threading.Event()

    def log_task(self, tag: str, text: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.task_logs.append((ts, tag, text))

    def log_auto(self, tag: str, text: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.auto_logs.append((ts, tag, text))

if "global_state" not in st.session_state:
    st.session_state.global_state = GlobalWorkerState()

GSTATE = st.session_state.global_state
acc_mgr = AccountManager(BASE_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# ULTRA-MODERN FULL-STACK DEV THEME (CSS)
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CLAUDE CLUSTER CONSOLE",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<style>
/* Base Reset & Fonts */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #E2E8F0;
}
code, pre, .terminal-text {
    font-family: 'Fira Code', 'JetBrains Mono', monospace !important;
}

/* Background gradient styling */
.stApp {
    background-color: #080B11;
    background-image: 
        radial-gradient(at 0% 0%, rgba(14, 165, 233, 0.08) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(99, 102, 241, 0.08) 0px, transparent 50%);
}

/* Top Telemetry Header */
.dev-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 24px;
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    backdrop-filter: blur(16px);
    margin-bottom: 24px;
}
.dev-header .title-area h2 {
    font-size: 1.25rem;
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.025em;
    background: linear-gradient(135deg, #38BDF8 0%, #818CF8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.dev-header .status-tag {
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    padding: 4px 10px;
    border-radius: 20px;
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid rgba(16, 185, 129, 0.3);
    color: #34D399;
}

/* Node Cluster Cards */
.node-card {
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 18px 20px;
    position: relative;
    transition: all 0.25s ease;
    backdrop-filter: blur(12px);
    margin-bottom: 12px;
}
.node-card:hover {
    border-color: rgba(56, 189, 248, 0.4);
    transform: translateY(-2px);
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(56, 189, 248, 0.1);
}
.node-card .node-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}
.node-card .node-id {
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    color: #64748B;
    background: rgba(255, 255, 255, 0.04);
    padding: 2px 8px;
    border-radius: 6px;
}
.node-card .node-name {
    font-size: 0.95rem;
    font-weight: 600;
    color: #F8FAFC;
}
.node-card .node-metric {
    font-family: 'Fira Code', monospace;
    font-size: 0.8rem;
    color: #94A3B8;
    margin-top: 8px;
}

/* Pulsing Status Badges */
.pulse-green {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #10B981;
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
    animation: pulse 2s infinite;
    margin-right: 6px;
}
.pulse-red {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #F43F5E;
    box-shadow: 0 0 0 0 rgba(244, 63, 94, 0.7);
    animation: pulse 2s infinite;
    margin-right: 6px;
}
.pulse-amber {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #F59E0B;
    margin-right: 6px;
}

@keyframes pulse {
    0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
    70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
    100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

/* DevOps Terminal Console */
.terminal-window {
    background: #090D16;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    margin-top: 14px;
}
.terminal-bar {
    background: #111827;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.terminal-dots {
    display: flex;
    gap: 6px;
    margin-right: 14px;
}
.terminal-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}
.dot-red { background: #EF4444; }
.dot-yellow { background: #F59E0B; }
.dot-green { background: #10B981; }
.terminal-title {
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    color: #94A3B8;
}

.terminal-body {
    padding: 16px 20px;
    max-height: 480px;
    overflow-y: auto;
    font-family: 'Fira Code', monospace;
    font-size: 0.8rem;
    line-height: 1.7;
    color: #CBD5E1;
    background: #080B11;
}
.log-row {
    display: flex;
    gap: 12px;
    margin-bottom: 4px;
}
.log-ts {
    color: #64748B;
    flex-shrink: 0;
}
.tag-info { color: #38BDF8; font-weight: 600; }
.tag-success { color: #34D399; font-weight: 600; }
.tag-warn { color: #FBBF24; font-weight: 600; }
.tag-error { color: #F87171; font-weight: 600; }
.tag-loop { color: #818CF8; font-weight: 600; }

/* Custom Metric Tiles */
.stat-box {
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 16px 20px;
    backdrop-filter: blur(10px);
}
.stat-box .stat-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #94A3B8;
}
.stat-box .stat-val {
    font-family: 'Fira Code', monospace;
    font-size: 1.6rem;
    font-weight: 700;
    color: #F8FAFC;
    margin-top: 4px;
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# WORKER THREADS
# ──────────────────────────────────────────────────────────────────────────────
def _thread_single_task(prompt_text: str):
    GSTATE.task_running = True
    GSTATE.task_logs = []
    GSTATE.task_result = None
    GSTATE.task_error = None
    GSTATE.task_account = None

    GSTATE.log_task("INFO", f"Dispatched task: '{prompt_text[:50]}...'")
    
    max_attempts = len(acc_mgr.config.get("accounts", []))
    attempts = 0
    success = False

    while attempts < max_attempts:
        account = acc_mgr.get_available_account()
        if not account:
            GSTATE.log_task("WARN", "Pool exhausted: All worker nodes are either in cooldown or unconfigured.")
            GSTATE.task_error = "All accounts in 5-hour cooldown or missing sessionKey."
            break

        GSTATE.log_task("INFO", f"Routing request to Node #{account['id']} [{account['name']}]...")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            GSTATE.log_task("SUCCESS", f"Execution successful ({len(resp):,} bytes received from node #{account['id']}).")
            
            GSTATE.task_result = resp
            GSTATE.task_account = account["name"]
            success = True
            break

        except ClaudeRateLimitError as e:
            GSTATE.log_task("WARN", f"Quota limit reached on Node #{account['id']}: {e}. Initiating auto-failover...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            attempts += 1
        except ClaudeAuthError as e:
            GSTATE.log_task("ERROR", f"Authentication failure on Node #{account['id']}: {e}")
            attempts += 1
        except Exception as e:
            GSTATE.log_task("ERROR", f"Unhandled exception on Node #{account['id']}: {e}")
            attempts += 1

    if not success and not GSTATE.task_error:
        GSTATE.task_error = "Execution failed across all pool nodes."

    GSTATE.task_running = False

def _thread_auto_runner(max_iter: int, prompt_text: str, infinite: bool):
    mode_tag = "INFINITE (24/7 Resilient)" if infinite else f"BOUNDED ({max_iter} iter)"
    GSTATE.log_auto("LOOP", f"Auto-Runner daemon spawned. Mode: {mode_tag} | Payload: '{prompt_text}'")
    GSTATE.infinite_mode = infinite
    GSTATE.start_timestamp = time.time()
    
    i = 0
    while True:
        if GSTATE.auto_stop_event.is_set():
            GSTATE.log_auto("WARN", "Termination signal received (SIGINT). Graceful shutdown initiated.")
            break

        i += 1
        if not infinite and i > max_iter:
            GSTATE.log_auto("SUCCESS", f"Target threshold of {max_iter} iterations satisfied. Daemon stopping.")
            break

        GSTATE.auto_iteration = i
        iter_display = f"#{i}" if infinite else f"#{i}/{max_iter}"
        GSTATE.log_auto("INFO", f"Dispatching cycle {iter_display}...")

        account = acc_mgr.get_available_account()

        if not account:
            now = time.time()
            cooldown_list = []
            for a_id, a_data in acc_mgr.state.get("accounts", {}).items():
                avail_at = a_data.get("available_at", 0)
                if avail_at > now:
                    cooldown_list.append((avail_at - now, a_data.get("name", f"Node #{a_id}")))

            if cooldown_list:
                cooldown_list.sort(key=lambda x: x[0])
                shortest_wait, next_acc_name = cooldown_list[0]
                wait_min = max(1, int(shortest_wait // 60))
                wake_time = (datetime.now() + timedelta(seconds=shortest_wait)).strftime("%H:%M:%S")
                GSTATE.sleeping_until_str = wake_time
                
                GSTATE.log_auto("WARN", f"ALL CLUSTER NODES RATE-LIMITED. Next available: {next_acc_name} in ~{wait_min}m ({wake_time}).")
                GSTATE.log_auto("LOOP", f"Entering low-power sleep state until {wake_time}. Auto-wake daemon armed...")
                
                sleep_deadline = time.time() + shortest_wait
                while time.time() < sleep_deadline:
                    if GSTATE.auto_stop_event.is_set():
                        break
                    time.sleep(10)
                
                if GSTATE.auto_stop_event.is_set():
                    break
                
                GSTATE.sleeping_until_str = ""
                GSTATE.log_auto("INFO", f"WAKE SIGNAL RECEIVED! Re-evaluating node cluster health...")
                acc_mgr.refresh_statuses()
                continue
            else:
                GSTATE.log_auto("ERROR", "No configured nodes found with valid credentials. Halting loop.")
                break

        GSTATE.log_auto("INFO", f"Transmitting payload to Node #{account['id']} [{account['name']}]...")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            GSTATE.log_auto("SUCCESS", f"Node #{account['id']} completed cycle ({len(resp):,} bytes).")

            resp_lower = resp.lower()
            if any(sig in resp_lower for sig in ["seluruh audit selesai", "pekerjaan sudah selesai", "tidak ada lagi"]):
                GSTATE.log_auto("SUCCESS", "Job completion pattern matched in model output. Stopping auto-runner.")
                break

        except ClaudeRateLimitError as e:
            GSTATE.log_auto("WARN", f"Rate-limit trip on Node #{account['id']}. Switching to next healthy node...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            i -= 1
            time.sleep(1)
            continue
        except Exception as e:
            GSTATE.log_auto("ERROR", f"Cycle failed on Node #{account['id']}: {e}")

        if not GSTATE.auto_stop_event.is_set():
            time.sleep(5)

    GSTATE.log_auto("INFO", "Auto-runner process exited.")
    GSTATE.auto_running = False
    GSTATE.sleeping_until_str = ""

# ──────────────────────────────────────────────────────────────────────────────
# LOG TERMINAL RENDERER
# ──────────────────────────────────────────────────────────────────────────────
def render_terminal(logs: list, title: str = "console.stdout"):
    rows_html = []
    for ts, tag, msg in logs[-100:]:
        tag_class = {
            "INFO": "tag-info",
            "SUCCESS": "tag-success",
            "WARN": "tag-warn",
            "ERROR": "tag-error",
            "LOOP": "tag-loop"
        }.get(tag, "tag-info")
        
        safe_msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows_html.append(f"""
        <div class="log-row">
            <span class="log-ts">[{ts}]</span>
            <span class="{tag_class}">[{tag:<7}]</span>
            <span>{safe_msg}</span>
        </div>
        """)
        
    body_content = "".join(rows_html) if rows_html else '<div style="color: #64748B;">// Idle. Waiting for daemon trigger...</div>'
    
    st.markdown(f"""
    <div class="terminal-window">
        <div class="terminal-bar">
            <div class="terminal-dots">
                <div class="terminal-dot dot-red"></div>
                <div class="terminal-dot dot-yellow"></div>
                <div class="terminal-dot dot-green"></div>
            </div>
            <div class="terminal-title">~/claude-cluster/{title}</div>
        </div>
        <div class="terminal-body">
            {body_content}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR NAVIGATION
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding: 10px 0 16px 0;">
        <div style="font-size: 0.75rem; font-weight: 700; letter-spacing: 0.1em; color: #38BDF8; text-transform: uppercase;">Infrastructure</div>
        <div style="font-size: 1.25rem; font-weight: 800; color: #F8FAFC;">CLAUDE CLUSTER</div>
    </div>
    """, unsafe_allow_html=True)

    nav = st.radio(
        "CLUSTER NAVIGATION",
        ["CLUSTER NODES", "TASK DISPATCHER", "AUTO RUNNER DAEMON", "CREDENTIAL VAULT", "CLUSTER CONFIG"],
        label_visibility="collapsed"
    )

    st.markdown("<hr style='border-color: rgba(255,255,255,0.06); margin: 20px 0;'>", unsafe_allow_html=True)

    summary = acc_mgr.get_status_summary()
    ready_count = sum(1 for s in summary if s["status"] == "READY")
    
    st.markdown(f"""
    <div style="font-size: 0.75rem; color: #94A3B8; font-family: 'Fira Code', monospace; line-height: 1.8;">
        <div>POOL HEALTH: <span style="color: {'#34D399' if ready_count > 0 else '#F87171'}; font-weight: 700;">{ready_count}/{len(summary)} ONLINE</span></div>
        <div>DAEMON STATE: <span style="color: {'#FBBF24' if GSTATE.auto_running else '#64748B'}; font-weight: 700;">{'RUNNING' if GSTATE.auto_running else 'IDLE'}</span></div>
        <div>REGION: <span style="color: #E2E8F0;">aws-us-east-1</span></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    if st.button("🔃 Sync Cluster State", use_container_width=True):
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# VIEW: CLUSTER NODES (DASHBOARD)
# ══════════════════════════════════════════════════════════════════════════════
if nav == "CLUSTER NODES":
    # Top Telemetry Header
    st.markdown("""
    <div class="dev-header">
        <div class="title-area">
            <h2>Cluster Telemetry & Health Dashboard</h2>
            <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 2px;">Multi-Account Round-Robin Pool • Continuous Load Balancing</div>
        </div>
        <div class="status-tag">STATUS: OPTIMAL</div>
    </div>
    """, unsafe_allow_html=True)

    summary = acc_mgr.get_status_summary()
    ready_n = sum(1 for s in summary if s["status"] == "READY")
    limit_n = sum(1 for s in summary if s["status"] == "RATE_LIMITED")
    nokey_n = sum(1 for s in summary if s["status"] == "NO_KEY")
    total_t = sum(s.get("total_tasks", 0) for s in summary)

    # Top Metric Box Grid
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Active Worker Nodes</div>
            <div class="stat-val" style="color: #34D399;">{ready_n} <span style="font-size: 0.9rem; color: #64748B;">/ {len(summary)}</span></div>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Rate-Limited Nodes</div>
            <div class="stat-val" style="color: {'#F43F5E' if limit_n > 0 else '#94A3B8'};">{limit_n}</div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Unauthenticated</div>
            <div class="stat-val" style="color: {'#F59E0B' if nokey_n > 0 else '#94A3B8'};">{nokey_n}</div>
        </div>
        """, unsafe_allow_html=True)
    with m4:
        st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Processed Invocations</div>
            <div class="stat-val" style="color: #38BDF8;">{total_t:,}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

    if GSTATE.auto_running:
        if GSTATE.sleeping_until_str:
            st.info(f"🛌 **Cluster Daemon Sleeping**: Quota exhausted across all nodes. Auto-resume timer set for **{GSTATE.sleeping_until_str}**.")
        else:
            mode_badge = "Infinite 24/7" if GSTATE.infinite_mode else f"Step #{GSTATE.auto_iteration}"
            st.success(f"⚡ **Active Daemon Execution**: Running in {mode_badge} mode.")

    # Nodes Grid
    st.markdown("<h4 style='font-size: 0.95rem; font-weight: 600; color: #94A3B8; margin-bottom: 12px; letter-spacing: 0.05em; text-transform: uppercase;'>Worker Node Pool</h4>", unsafe_allow_html=True)
    
    node_cols = st.columns(len(summary))
    for col, s in zip(node_cols, summary):
        with col:
            if s["status"] == "READY":
                status_html = '<span class="pulse-green"></span><span style="color: #34D399; font-weight: 600; font-size: 0.8rem;">READY</span>'
                metric_info = '<span style="color: #34D399;">● Online & Listening</span>'
            elif s["status"] == "RATE_LIMITED":
                status_html = '<span class="pulse-red"></span><span style="color: #F87171; font-weight: 600; font-size: 0.8rem;">RATE LIMIT</span>'
                metric_info = f'<span style="color: #F87171;">⏱ {s["cooldown"]}</span>'
            else:
                status_html = '<span class="pulse-amber"></span><span style="color: #FBBF24; font-weight: 600; font-size: 0.8rem;">NO SECRET</span>'
                metric_info = '<span style="color: #FBBF24;">Needs sessionKey</span>'

            st.markdown(f"""
            <div class="node-card">
                <div class="node-top">
                    <span class="node-id">NODE_0{s['id']}</span>
                    <div>{status_html}</div>
                </div>
                <div class="node-name">{s['name']}</div>
                <div class="node-metric">{metric_info}</div>
                <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 0.75rem; color: #64748B; font-family: 'Fira Code', monospace;">
                    <div>TASKS: <span style="color: #E2E8F0;">{s['total_tasks']}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# VIEW: TASK DISPATCHER (SINGLE RUN)
# ══════════════════════════════════════════════════════════════════════════════
elif nav == "TASK DISPATCHER":
    st.markdown("""
    <div class="dev-header">
        <div class="title-area">
            <h2>Manual Task Dispatcher</h2>
            <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 2px;">Submit targeted payload across available pool workers</div>
        </div>
        <div class="status-tag">MODE: DIRECT_EXEC</div>
    </div>
    """, unsafe_allow_html=True)

    task_input = st.text_area(
        "Payload / Prompt Instruction",
        placeholder="Enter raw instructions (e.g., 'Perform AST refactor of authentication middleware and check for memory leaks')...",
        height=140
    )

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        if st.button("🚀 Dispatch to Cluster", type="primary", disabled=GSTATE.task_running, use_container_width=True):
            if task_input.strip():
                t = threading.Thread(target=_thread_single_task, args=(task_input,), daemon=True)
                t.start()
                st.rerun()

    if GSTATE.task_running or GSTATE.task_logs:
        render_terminal(GSTATE.task_logs, title="task_dispatcher.log")
        if GSTATE.task_running:
            time.sleep(2)
            st.rerun()

    if GSTATE.task_result:
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        st.success(f"✔ Task fulfilled by node: {GSTATE.task_account}")
        with st.expander("📄 View Model Response", expanded=True):
            st.markdown(GSTATE.task_result)

    if GSTATE.task_error:
        st.error(f"❌ {GSTATE.task_error}")

# ══════════════════════════════════════════════════════════════════════════════
# VIEW: AUTO RUNNER DAEMON (INFINITE LOOP)
# ══════════════════════════════════════════════════════════════════════════════
elif nav == "AUTO RUNNER DAEMON":
    st.markdown("""
    <div class="dev-header">
        <div class="title-area">
            <h2>Auto-Runner Resilient Daemon</h2>
            <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 2px;">Continuous execution pipeline with autonomous 5h failover and smart sleep</div>
        </div>
        <div class="status-tag">AUTO-PILOT: {'ACTIVE' if GSTATE.auto_running else 'ARMED'}</div>
    </div>
    """, unsafe_allow_html=True)

    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            infinite_check = st.checkbox("♾️ **Infinite Pipeline (24/7 Continuous Autonomous Loop)**", value=True, disabled=GSTATE.auto_running)
            max_i = st.number_input("Max Iteration Ceiling (Active if Infinite is unchecked)", 1, 10000, 100, disabled=GSTATE.auto_running or infinite_check)
        with c2:
            prompt_auto = st.text_input("Payload Message per Cycle", value="lanjut", disabled=GSTATE.auto_running)

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("▶️ Launch Pipeline Daemon", type="primary", disabled=GSTATE.auto_running, use_container_width=True):
                GSTATE.auto_stop_event.clear()
                GSTATE.auto_running = True
                GSTATE.auto_logs = []
                GSTATE.auto_iteration = 0
                GSTATE.auto_max = max_i
                t = threading.Thread(target=_thread_auto_runner, args=(max_i, prompt_auto, infinite_check), daemon=True)
                t.start()
                st.rerun()

        with b2:
            if st.button("⏹️ Signal SIGINT (Halt Daemon)", disabled=not GSTATE.auto_running, use_container_width=True):
                GSTATE.auto_stop_event.set()
                GSTATE.auto_running = False
                st.warning("Sent SIGINT interrupt signal. Finishing current cycle before exit...")
                st.rerun()

    if GSTATE.auto_running or GSTATE.auto_logs:
        render_terminal(GSTATE.auto_logs, title="pipeline_runner.log")
        if GSTATE.auto_running:
            time.sleep(3)
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# VIEW: CREDENTIAL VAULT (COOKIES / SECRETS)
# ══════════════════════════════════════════════════════════════════════════════
elif nav == "CREDENTIAL VAULT":
    st.markdown("""
    <div class="dev-header">
        <div class="title-area">
            <h2>Cluster Credential Vault</h2>
            <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 2px;">Manage sessionKey cookies for worker nodes</div>
        </div>
        <div class="status-tag">VAULT: AES-AUTHENTICATED</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="background: rgba(15, 23, 42, 0.5); border: 1px solid rgba(255,255,255,0.06); padding: 14px 18px; border-radius: 10px; font-size: 0.85rem; color: #94A3B8; margin-bottom: 20px;">
        <strong style="color: #38BDF8;">Extraction Protocol:</strong> Inspect <code>https://claude.ai</code> in browser (<code>F12 -> Application -> Storage -> Cookies</code>), extract <code>sessionKey</code> value starting with <code>sk-ant-sid01-...</code> and bind it to a worker node below.
    </div>
    """, unsafe_allow_html=True)

    accounts = acc_mgr.config.get("accounts", [])
    updated = False

    for acc in accounts:
        with st.expander(f"⚙️ Node #{acc['id']} — {acc['name']}", expanded=not bool(acc.get("session_key"))):
            current_key = acc.get("session_key", "")
            
            c_input, c_test = st.columns([4, 1])
            with c_input:
                new_key = st.text_input(
                    f"sessionKey for Node #{acc['id']}",
                    value=current_key,
                    type="password",
                    placeholder="sk-ant-sid01-xxxx-xxxx...",
                    key=f"vault_key_{acc['id']}"
                )
            with c_test:
                st.write("")
                st.write("")
                if st.button("🔍 Ping Node", key=f"vault_ping_{acc['id']}"):
                    if new_key.strip():
                        test_cli = ClaudeWebClient(new_key.strip())
                        ok, msg = test_cli.test_connection()
                        if ok:
                            st.success(f"✔ {msg}")
                        else:
                            st.error(f"✖ {msg}")
                    else:
                        st.warning("Provide sessionKey first.")

            chat_url = st.text_input(
                f"Thread UUID / Path (Optional continuous conversation):",
                value=acc.get("tapir_chat_url", ""),
                key=f"vault_url_{acc['id']}"
            )
            
            if new_key != current_key or chat_url != acc.get("tapir_chat_url"):
                acc["session_key"] = new_key.strip()
                acc["tapir_chat_url"] = chat_url.strip()
                updated = True

    if updated or st.button("💾 Persist Vault Credentials", type="primary", use_container_width=True):
        acc_mgr.save_config()
        st.success("✔ Configuration written to state cluster.")
        st.rerun()

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    with st.expander("🛡️ Production Recommendation: Streamlit Secrets"):
        st.code("""# .streamlit/secrets.toml
[[accounts]]
id = 1
name = "Claude Account 1"
session_key = "sk-ant-sid01-..."

[[accounts]]
id = 2
name = "Claude Account 2"
session_key = "sk-ant-sid01-..."
""", language="toml")

# ══════════════════════════════════════════════════════════════════════════════
# VIEW: CLUSTER CONFIG
# ══════════════════════════════════════════════════════════════════════════════
elif nav == "CLUSTER CONFIG":
    st.markdown("""
    <div class="dev-header">
        <div class="title-area">
            <h2>Cluster Global Configuration</h2>
            <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 2px;">Tune timeout parameters, cooldown thresholds and cluster state</div>
        </div>
        <div class="status-tag">ENV: PRODUCTION</div>
    </div>
    """, unsafe_allow_html=True)

    cd_hours = st.number_input(
        "Default Cooldown Rate-Limit Duration (Hours)",
        min_value=1.0,
        max_value=12.0,
        value=float(acc_mgr.config.get("cooldown_hours", 5.0)),
        step=0.5
    )
    
    if st.button("💾 Commit Configuration Changes", type="primary"):
        acc_mgr.config["cooldown_hours"] = cd_hours
        acc_mgr.save_config()
        st.success("✔ Configuration committed to cluster.")

    st.markdown("<hr style='border-color: rgba(255,255,255,0.06); margin: 24px 0;'>", unsafe_allow_html=True)
    st.subheader("Cluster State Reset")
    st.caption("Clear all node lockout timestamps and reset pool state to healthy.")
    if st.button("🗑️ Reset All Node Lockouts"):
        for acc in acc_mgr.state["accounts"].values():
            acc["status"] = "ready"
            acc["available_at"] = 0
            acc["cooldown_until_str"] = ""
        acc_mgr.save_state()
        st.success("✔ All nodes reset to READY state.")
        st.rerun()
