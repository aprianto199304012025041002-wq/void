"""
Account Pool Manager & Cooldown State Tracker.
Mendukung pembacaan st.secrets (Cloud) dan config.json (lokal).
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta
from typing import List, Optional

STATE_FILE = "state.json"
CONFIG_FILE = "config.json"

class ClusterPool:
    _lock = threading.Lock()

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.config_path = os.path.join(base_dir, CONFIG_FILE)
        self.state_path = os.path.join(base_dir, STATE_FILE)
        self.config = self._load_config()
        self.state = self._load_state()

    def _load_config(self) -> dict:
        cfg = {"accounts": [], "cooldown_hours": 5.0}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass

        # Injeksi dari st.secrets jika di deploy ke Streamlit Cloud
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "accounts" in st.secrets:
                for idx, s_acc in enumerate(st.secrets["accounts"]):
                    acc_id = s_acc.get("id", idx + 1)
                    matched = next((a for a in cfg["accounts"] if a["id"] == acc_id), None)
                    if matched:
                        if s_acc.get("session_key"):
                            matched["session_key"] = s_acc["session_key"]
                    else:
                        cfg["accounts"].append(dict(s_acc))
        except Exception:
            pass

        return cfg

    def _load_state(self) -> dict:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        default_state = {"accounts": {}, "current_account_id": 1}
        for acc in self.config.get("accounts", []):
            acc_id = str(acc["id"])
            default_state["accounts"][acc_id] = {
                "id": acc["id"],
                "name": acc.get("name", f"Account {acc['id']}"),
                "status": "ready",
                "available_at": 0,
                "cooldown_until_str": "",
                "last_used": 0,
                "total_tasks": 0,
            }
        return default_state

    def save_state(self):
        with self._lock:
            try:
                with open(self.state_path, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, indent=2)
            except Exception:
                pass

    def save_config(self):
        with self._lock:
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
            except Exception:
                pass

    def refresh_statuses(self):
        now = time.time()
        with self._lock:
            for acc_id, acc in self.state.get("accounts", {}).items():
                if acc.get("status") == "rate_limited":
                    if now >= acc.get("available_at", 0):
                        acc["status"] = "ready"
                        acc["available_at"] = 0
                        acc["cooldown_until_str"] = ""
        self.save_state()

    def get_available_account(self) -> Optional[dict]:
        self.refresh_statuses()
        accounts = self.config.get("accounts", [])
        if not accounts:
            return None

        start_id = self.state.get("current_account_id", 1)
        acc_ids = [acc["id"] for acc in accounts]

        if start_id in acc_ids:
            idx = acc_ids.index(start_id)
            ordered_ids = acc_ids[idx:] + acc_ids[:idx]
        else:
            ordered_ids = acc_ids

        for aid in ordered_ids:
            acc_state = self.state.get("accounts", {}).get(str(aid), {})
            if acc_state.get("status") == "ready":
                conf = next((a for a in accounts if a["id"] == aid), None)
                if conf and conf.get("session_key"):
                    self.state["current_account_id"] = aid
                    self.save_state()
                    return {**conf, **acc_state}

        return None

    def mark_rate_limited(self, account_id: int, reset_seconds: Optional[int] = None):
        now = time.time()
        duration = reset_seconds if reset_seconds else int(self.config.get("cooldown_hours", 5.0) * 3600)
        cooldown_until = now + duration
        cooldown_str = (datetime.now() + timedelta(seconds=duration)).strftime("%Y-%m-%d %H:%M:%S")

        acc_id_str = str(account_id)
        with self._lock:
            if acc_id_str in self.state.get("accounts", {}):
                acc = self.state["accounts"][acc_id_str]
                acc["status"] = "rate_limited"
                acc["available_at"] = cooldown_until
                acc["cooldown_until_str"] = cooldown_str

            accounts = self.config.get("accounts", [])
            acc_ids = [a["id"] for a in accounts]
            if account_id in acc_ids:
                idx = acc_ids.index(account_id)
                next_idx = (idx + 1) % len(acc_ids)
                self.state["current_account_id"] = acc_ids[next_idx]

        self.save_state()

    def record_task_success(self, account_id: int):
        acc_id_str = str(account_id)
        with self._lock:
            if acc_id_str in self.state.get("accounts", {}):
                acc = self.state["accounts"][acc_id_str]
                acc["last_used"] = time.time()
                acc["total_tasks"] = acc.get("total_tasks", 0) + 1
        self.save_state()

    def get_status_summary(self) -> List[dict]:
        self.refresh_statuses()
        summary = []
        now = time.time()
        for acc_conf in self.config.get("accounts", []):
            aid = str(acc_conf["id"])
            s = self.state.get("accounts", {}).get(aid, {})
            status = s.get("status", "ready")
            wait_str = "-"
            has_key = bool(acc_conf.get("session_key"))

            if not has_key:
                display_status = "NO_KEY"
            elif status == "rate_limited":
                display_status = "RATE_LIMITED"
                remaining = max(0, int(s.get("available_at", 0) - now))
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                wait_str = f"{hours}h {minutes}m"
            else:
                display_status = "READY"

            summary.append({
                "id": acc_conf["id"],
                "name": acc_conf.get("name"),
                "has_key": has_key,
                "status": display_status,
                "cooldown": wait_str,
                "total_tasks": s.get("total_tasks", 0),
            })
        return summary
