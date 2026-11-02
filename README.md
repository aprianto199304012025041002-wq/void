# ⚡ Claude Cluster Orchestrator (Cloud-Native Edition)

Ultra-compact, resilient multi-account orchestrator for `claude.ai` free accounts, designed to run 24/7 on **Streamlit Cloud** without requiring local PC background processes or browser automation.

---

## 🏗️ Architecture

```
void/
├── src/                          # Core Orchestration Engine
│   ├── __init__.py
│   ├── client.py                 # Direct Claude API Client (curl_cffi)
│   ├── pool.py                   # Cluster Account Pool & Cooldown Tracker
│   └── worker.py                 # Thread-Safe Workers & 24/7 Auto-Runner Daemon
│
├── ui/                           # Modular UI Components
│   ├── __init__.py
│   ├── styles.py                 # Cyberpunk High-Density Stylesheet
│   ├── auth.py                   # Security Gatekeeper (st.secrets["pw"])
│   └── components.py             # Telemetry Bar, Node Micro-Cards & Terminal Stream
│
├── streamlit_app.py              # Single-View Main Entry Point
├── config.json                   # Pool accounts & configuration
├── requirements.txt              # Production dependencies
└── README.md
```

---

## 🚀 Key Features

- **Cloud-Native & Serverless**: 100% runs on Streamlit Cloud using `curl_cffi` TLS impersonation (bypasses Cloudflare without Chromium/Playwright).
- **Infinite Auto-Runner (24/7)**: Continuous autonomous loop with automatic 5-hour failover between accounts.
- **Smart Sleep & Auto-Wakeup**: When all cluster nodes are in cooldown, the system calculates the shortest wait time, enters low-power sleep, and wakes up automatically.
- **High-Density Cyberpunk UI**: Zero-scroll split-screen view with micro-node status cards and live console log stream.
- **Security Gatekeeper**: Protected with cluster access password via `st.secrets["pw"]`.
