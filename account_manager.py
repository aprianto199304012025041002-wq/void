import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

STATE_FILE = "state.json"
CONFIG_FILE = "config.json"


class AccountManager:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.config_path = os.path.join(base_dir, CONFIG_FILE)
        self.state_path = os.path.join(base_dir, STATE_FILE)
        self.config = self._load_config()
        self.state = self._load_state()

    def _load_config(self) -> dict:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"accounts": [], "cooldown_hours": 5.0}

    def _load_state(self) -> dict:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # Initialize default state
        default_state = {
            "accounts": {},
            "current_account_id": 1,
        }
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
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def refresh_statuses(self):
        """Check all accounts and reset those whose 5-hour cooldown has expired."""
        now = time.time()
        for acc_id, acc in self.state["accounts"].items():
            if acc["status"] == "rate_limited":
                if now >= acc["available_at"]:
                    acc["status"] = "ready"
                    acc["available_at"] = 0
                    acc["cooldown_until_str"] = ""
                    print(f"[Account Pool] Cooldown expired for {acc['name']}. Status is now READY.")
        self.save_state()

    def get_available_account(self) -> Optional[dict]:
        """Get the next ready account in round-robin sequence."""
        self.refresh_statuses()
        accounts = self.config.get("accounts", [])
        if not accounts:
            return None

        # Start search from current_account_id
        start_id = self.state.get("current_account_id", 1)
        acc_ids = [acc["id"] for acc in accounts]

        # Order candidates starting from start_id
        if start_id in acc_ids:
            idx = acc_ids.index(start_id)
            ordered_ids = acc_ids[idx:] + acc_ids[:idx]
        else:
            ordered_ids = acc_ids

        for aid in ordered_ids:
            acc_state = self.state["accounts"].get(str(aid))
            if acc_state and acc_state.get("status") == "ready":
                self.state["current_account_id"] = aid
                self.save_state()
                # Return combined config + state
                conf = next(a for a in accounts if a["id"] == aid)
                return {**conf, **acc_state}

        return None

    def mark_rate_limited(self, account_id: int, reset_seconds: Optional[int] = None):
        """Mark account as rate-limited and set cooldown timer."""
        now = time.time()
        duration = reset_seconds if reset_seconds else int(self.config.get("cooldown_hours", 5.0) * 3600)
        cooldown_until = now + duration
        cooldown_str = (datetime.now() + timedelta(seconds=duration)).strftime("%Y-%m-%d %H:%M:%S")

        acc_id_str = str(account_id)
        if acc_id_str in self.state["accounts"]:
            acc = self.state["accounts"][acc_id_str]
            acc["status"] = "rate_limited"
            acc["available_at"] = cooldown_until
            acc["cooldown_until_str"] = cooldown_str
            print(f"[Account Pool] {acc['name']} rate-limited. Cooldown until {cooldown_str} (~{duration // 60} mins).")

        # Advance current_account_id to next account
        accounts = self.config.get("accounts", [])
        acc_ids = [a["id"] for a in accounts]
        if account_id in acc_ids:
            idx = acc_ids.index(account_id)
            next_idx = (idx + 1) % len(acc_ids)
            self.state["current_account_id"] = acc_ids[next_idx]

        self.save_state()

    def record_task_success(self, account_id: int):
        acc_id_str = str(account_id)
        if acc_id_str in self.state["accounts"]:
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
            s = self.state["accounts"].get(aid, {})
            status = s.get("status", "unknown")
            wait_str = "-"
            if status == "rate_limited":
                remaining = max(0, int(s.get("available_at", 0) - now))
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                wait_str = f"{hours}h {minutes}m remaining (until {s.get('cooldown_until_str', '')})"

            summary.append({
                "id": acc_conf["id"],
                "name": acc_conf.get("name"),
                "status": status.upper(),
                "cooldown": wait_str,
                "total_tasks": s.get("total_tasks", 0),
            })
        return summary
