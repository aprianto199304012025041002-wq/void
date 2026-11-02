"""
Cluster Thread Workers & Global State Manager.
Mengeksekusi task & menyimpan riwayat lengkap (Command Sent & Full Responses).
"""

import threading
import time
import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from src.client import ClaudeWebClient, ClaudeRateLimitError, ClaudeAuthError
from src.pool import ClusterPool

HISTORY_FILE = "history.json"

class GlobalWorkerState:
    def __init__(self, base_dir: str = "."):
        self.lock = threading.Lock()
        self.base_dir = base_dir
        self.history_path = os.path.join(base_dir, HISTORY_FILE)

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

        # Riwayat interaksi (prompt + respon lengkap dari semua akun)
        self.invocations: List[Dict[str, Any]] = self._load_history()

    def _load_history(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_history(self):
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.invocations[-100:], f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def log(self, tag: str, text: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.task_logs.append((ts, tag, text))

    def record_invocation(self, account_id: int, account_name: str, prompt: str, response: str, mode: str = "SINGLE"):
        with self.lock:
            entry = {
                "id": len(self.invocations) + 1,
                "timestamp": datetime.now().strftime("%d/%m %H:%M:%S"),
                "account_id": account_id,
                "account_name": account_name,
                "mode": mode,
                "prompt": prompt,
                "response": response,
                "length": len(response)
            }
            self.invocations.insert(0, entry)  # Terbaru di urutan atas
            self._save_history()

def run_single_task(state: GlobalWorkerState, pool: ClusterPool, prompt_text: str):
    state.task_running = True
    state.task_result = None
    state.task_error = None
    state.log("INFO", f"Task queued: '{prompt_text[:45]}...'")

    max_attempts = len(pool.config.get("accounts", []))
    attempts = 0
    success = False

    while attempts < max_attempts:
        account = pool.get_available_account()
        if not account:
            state.log("WARN", "Pool lock: Semua node dalam cooldown.")
            state.task_error = "Semua akun dalam masa jeda 5 jam atau sessionKey kosong."
            break

        state.log("INFO", f"Dispatch -> Node #{account['id']} [{account['name']}]")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            pool.record_task_success(account["id"])
            state.log("SUCCESS", f"Node #{account['id']} selesai ({len(resp):,} karakter).")
            state.task_result = resp
            state.task_account = account["name"]
            
            # Catat ke riwayat
            state.record_invocation(account["id"], account["name"], prompt_text, resp, mode="MANUAL")
            success = True
            break
        except ClaudeRateLimitError as e:
            state.log("WARN", f"Node #{account['id']} limit 5 jam. Auto-failover...")
            pool.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            attempts += 1
        except Exception as e:
            state.log("ERROR", f"Node #{account['id']} error: {e}")
            attempts += 1

    if not success and not state.task_error:
        state.task_error = "Eksekusi gagal di semua node."
    state.task_running = False

def run_auto_daemon(state: GlobalWorkerState, pool: ClusterPool, max_iter: int, prompt_text: str, infinite: bool):
    mode_tag = "INFINITE (24/7)" if infinite else f"{max_iter} ITER"
    state.log("LOOP", f"Daemon aktif [{mode_tag}]. Payload: '{prompt_text}'")
    state.infinite_mode = infinite

    i = 0
    while True:
        if state.auto_stop_event.is_set():
            state.log("WARN", "SIGINT diterima. Menghentikan loop daemon.")
            break

        i += 1
        if not infinite and i > max_iter:
            state.log("SUCCESS", f"Target {max_iter} tercapai. Daemon selesai.")
            break

        state.auto_iteration = i
        iter_display = f"#{i}" if infinite else f"#{i}/{max_iter}"
        state.log("INFO", f"Siklus {iter_display} mulai...")

        account = pool.get_available_account()

        if not account:
            now = time.time()
            cooldown_list = []
            for a_id, a_data in pool.state.get("accounts", {}).items():
                avail_at = a_data.get("available_at", 0)
                if avail_at > now:
                    cooldown_list.append((avail_at - now, a_data.get("name", f"N0{a_id}")))

            if cooldown_list:
                cooldown_list.sort(key=lambda x: x[0])
                shortest_wait, next_name = cooldown_list[0]
                wait_min = max(1, int(shortest_wait // 60))
                wake_time = (datetime.now() + timedelta(seconds=shortest_wait)).strftime("%H:%M:%S")
                state.sleeping_until_str = wake_time

                state.log("WARN", f"SEMUA NODE COOLDOWN. {next_name} siap dalam ~{wait_min}m ({wake_time}). Tidur otomatis...")

                sleep_deadline = time.time() + shortest_wait
                while time.time() < sleep_deadline:
                    if state.auto_stop_event.is_set():
                        break
                    time.sleep(10)

                if state.auto_stop_event.is_set():
                    break

                state.sleeping_until_str = ""
                state.log("INFO", "WAKE SIGNAL. Memeriksa ulang node...")
                pool.refresh_statuses()
                continue
            else:
                state.log("ERROR", "Tidak ada akun dengan sessionKey valid.")
                break

        state.log("INFO", f"Kirim -> Node #{account['id']} [{account['name']}]")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            pool.record_task_success(account["id"])
            state.log("SUCCESS", f"Node #{account['id']} menjawab ({len(resp):,} karakter).")

            # Catat ke riwayat
            state.record_invocation(account["id"], account["name"], prompt_text, resp, mode=f"AUTO #{i}")

            resp_lower = resp.lower()
            if any(sig in resp_lower for sig in ["seluruh audit selesai", "pekerjaan sudah selesai", "tidak ada lagi"]):
                state.log("SUCCESS", "Pola tugas selesai terdeteksi. Selesai.")
                break
        except ClaudeRateLimitError as e:
            state.log("WARN", f"Node #{account['id']} 5h limit. Failover...")
            pool.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            i -= 1
            time.sleep(1)
            continue
        except Exception as e:
            state.log("ERROR", f"Node #{account['id']} error: {e}")

        if not state.auto_stop_event.is_set():
            time.sleep(5)

    state.log("INFO", "Daemon loop dihentikan.")
    state.auto_running = False
    state.sleeping_until_str = ""
