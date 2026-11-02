"""
FastAPI backend — berjalan di PC lokal.
Streamlit Cloud memanggil endpoint ini melalui Cloudflare Tunnel.
"""

import os
import sys
import threading
import contextlib
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from account_manager import AccountManager
from claude_worker import ClaudeWorker, ClaudeRateLimitError, ClaudeAuthError
from git_integration import GitManager

app = FastAPI(title="Claude Orchestrator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared state (in-memory) ───────────────────────────────────────────────────
_state = {
    "task": {
        "running": False,
        "logs": [],
        "result": None,
        "error": None,
        "account": None,
        "file": None,
        "started_at": None,
    },
    "auto": {
        "running": False,
        "logs": [],
        "iteration": 0,
        "max": 0,
        "stop_event": threading.Event(),
        "thread": None,
        "started_at": None,
    },
}


# ── Logger util ────────────────────────────────────────────────────────────────
class _ListWriter:
    def __init__(self, log_list):
        self._list = log_list

    def write(self, text):
        stripped = text.rstrip()
        if stripped:
            ts = datetime.now().strftime("%H:%M:%S")
            self._list.append(f"[{ts}] {stripped}")

    def flush(self):
        pass


# ── Background workers ─────────────────────────────────────────────────────────
def _run_single_task(task_text: str, include_git: bool, headless: bool):
    s = _state["task"]
    s["running"] = True
    s["logs"] = []
    s["result"] = None
    s["error"] = None
    s["account"] = None
    s["file"] = None
    s["started_at"] = datetime.now().isoformat()

    writer = _ListWriter(s["logs"])
    with contextlib.redirect_stdout(writer):
        try:
            acc_mgr = AccountManager(BASE_DIR)
            config = acc_mgr.config.copy()
            config["headless"] = headless

            prompt = task_text
            if include_git:
                git = GitManager(config.get("repo_path", ""), config.get("github_pat", ""))
                if git.is_valid_repo():
                    tree = git.get_repo_structure()
                    prompt = (
                        "Berikut adalah struktur file dalam repository GitHub saat ini:\n"
                        f"```\n{tree}\n```\n\n"
                        f"Instruksi tugas pengembangan aplikasi:\n{task_text}"
                    )

            max_attempts = len(config.get("accounts", []))
            attempts = 0

            while attempts < max_attempts:
                account = acc_mgr.get_available_account()
                if not account:
                    s["error"] = "Semua akun cooldown"
                    print("⚠️  Semua akun cooldown!")
                    break

                print(f"🚀  Kirim ke: {account['name']} ...")
                worker = ClaudeWorker(
                    account_config=account,
                    base_dir=BASE_DIR,
                    headless=headless,
                )
                try:
                    response = worker.send_prompt(prompt)
                    acc_mgr.record_task_success(account["id"])

                    out_dir = Path(BASE_DIR) / "outputs"
                    out_dir.mkdir(exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out_file = out_dir / f"task_{ts}.md"
                    out_file.write_text(
                        f"# Task Prompt:\n{task_text}\n\n---\n"
                        f"# Claude Response ({account['name']}):\n{response}\n",
                        encoding="utf-8",
                    )
                    print(f"✅  Selesai ({len(response):,} karakter)")
                    s["result"]  = response
                    s["account"] = account["name"]
                    s["file"]    = str(out_file)
                    break

                except ClaudeRateLimitError as e:
                    print(f"⏳  {account['name']} rate-limited. Failover ...")
                    acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
                    attempts += 1
                except ClaudeAuthError as e:
                    print(f"🔐  Auth error: {e}")
                    attempts += 1
                except Exception as e:
                    print(f"❌  Error: {e}")
                    attempts += 1
            else:
                s["error"] = "Semua akun gagal"

        except Exception as exc:
            s["error"] = str(exc)
            print(f"❌  Fatal: {exc}")
        finally:
            s["running"] = False


def _run_auto_loop(max_iter: int, prompt_text: str, headless: bool):
    s = _state["auto"]
    s["running"]    = True
    s["logs"]       = []
    s["iteration"]  = 0
    s["max"]        = max_iter
    s["started_at"] = datetime.now().isoformat()
    stop_event = s["stop_event"]

    writer = _ListWriter(s["logs"])
    with contextlib.redirect_stdout(writer):
        try:
            acc_mgr = AccountManager(BASE_DIR)
            config = acc_mgr.config.copy()
            config["headless"] = headless
            print(f"🔄  Auto-runner dimulai. Max: {max_iter} iterasi")
            print(f"📝  Prompt: '{prompt_text}'")
            print("─" * 50)

            for i in range(1, max_iter + 1):
                if stop_event.is_set():
                    print("🛑  Dihentikan user.")
                    break

                s["iteration"] = i
                print(f"\n>>> ITERASI #{i}/{max_iter}  ({datetime.now().strftime('%H:%M:%S')})")

                account = acc_mgr.get_available_account()
                if not account:
                    now = time.time()
                    avails = [
                        v.get("available_at", now)
                        for v in acc_mgr.state["accounts"].values()
                        if v.get("available_at", 0) > now
                    ]
                    wait_min = max(1, int((min(avails) - now) // 60)) if avails else 60
                    print(f"💤  Semua cooldown. ~{wait_min} menit lagi. Tidur 60 detik ...")
                    for _ in range(60):
                        if stop_event.is_set():
                            break
                        time.sleep(1)
                    continue

                print(f"    Akun: {account['name']}")
                worker = ClaudeWorker(
                    account_config=account,
                    base_dir=BASE_DIR,
                    headless=headless,
                )
                try:
                    response = worker.send_prompt(prompt_text)
                    acc_mgr.record_task_success(account["id"])

                    out_dir = Path(BASE_DIR) / "outputs"
                    out_dir.mkdir(exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out_file = out_dir / f"auto_{ts}.md"
                    out_file.write_text(
                        f"# Auto-Run #{i}\nPrompt: `{prompt_text}`\n\n---\n"
                        f"# Response ({account['name']}):\n{response}\n",
                        encoding="utf-8",
                    )
                    print(f"✅  Selesai ({len(response):,} karakter)")

                    done_signals = [
                        "seluruh audit selesai", "semua perbandingan selesai",
                        "pekerjaan sudah selesai", "tidak ada lagi perbedaan",
                    ]
                    if any(sig in response.lower() for sig in done_signals):
                        print("🎉  Claude: pekerjaan selesai!")
                        break

                except ClaudeRateLimitError as e:
                    print(f"⏳  Rate limit. Failover ...")
                    acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
                except ClaudeAuthError as e:
                    print(f"🔐  Auth error: {e}")
                except Exception as e:
                    print(f"❌  Error: {e}")

                if not stop_event.is_set():
                    for _ in range(5):
                        if stop_event.is_set():
                            break
                        time.sleep(1)

            print("\n🏁  Auto-runner selesai.")
        except Exception as exc:
            print(f"❌  Fatal: {exc}")
        finally:
            s["running"] = False


# ── Pydantic models ────────────────────────────────────────────────────────────
class TaskRequest(BaseModel):
    task: str
    include_git: bool = True
    headless: bool = True


class AutoRequest(BaseModel):
    max_iter: int = 100
    prompt: str = "lanjut"
    headless: bool = True


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Claude Orchestrator API"}


@app.get("/status")
def get_status():
    """Status semua akun + running state."""
    acc_mgr = AccountManager(BASE_DIR)
    summary = acc_mgr.get_status_summary()
    return {
        "accounts": summary,
        "task":     {k: v for k, v in _state["task"].items() if k != "result"},
        "auto":     {k: v for k, v in _state["auto"].items()
                     if k not in ("stop_event", "thread")},
    }


@app.post("/task/run")
def run_task(req: TaskRequest, background_tasks: BackgroundTasks):
    if _state["task"]["running"]:
        raise HTTPException(status_code=409, detail="Task sudah berjalan")
    background_tasks.add_task(_run_single_task, req.task, req.include_git, req.headless)
    return {"message": "Task dimulai"}


@app.get("/task/result")
def get_task_result():
    s = _state["task"]
    return {
        "running": s["running"],
        "logs":    s["logs"][-80:],
        "result":  s["result"],
        "error":   s["error"],
        "account": s["account"],
        "file":    s["file"],
    }


@app.post("/auto/start")
def start_auto(req: AutoRequest, background_tasks: BackgroundTasks):
    if _state["auto"]["running"]:
        raise HTTPException(status_code=409, detail="Auto runner sudah berjalan")
    _state["auto"]["stop_event"] = threading.Event()
    background_tasks.add_task(_run_auto_loop, req.max_iter, req.prompt, req.headless)
    return {"message": "Auto runner dimulai"}


@app.post("/auto/stop")
def stop_auto():
    _state["auto"]["stop_event"].set()
    return {"message": "Stop signal terkirim"}


@app.get("/auto/logs")
def get_auto_logs():
    s = _state["auto"]
    return {
        "running":   s["running"],
        "iteration": s["iteration"],
        "max":       s["max"],
        "logs":      s["logs"][-100:],
    }


@app.get("/outputs")
def list_outputs():
    out_dir = Path(BASE_DIR) / "outputs"
    out_dir.mkdir(exist_ok=True)
    files = sorted(out_dir.glob("*.md"), reverse=True)
    return [
        {
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
        }
        for f in files[:50]
    ]


@app.get("/outputs/{filename}")
def get_output(filename: str):
    out_dir = Path(BASE_DIR) / "outputs"
    path = out_dir / filename
    if not path.exists() or not path.is_relative_to(out_dir):
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    return {"content": path.read_text(encoding="utf-8")}


@app.get("/config")
def get_config():
    cfg = (Path(BASE_DIR) / "config.json").read_text(encoding="utf-8")
    import json
    c = json.loads(cfg)
    c["github_pat"] = "***" if c.get("github_pat") else ""
    return c


@app.put("/config")
def update_config(body: dict):
    import json
    cfg_path = Path(BASE_DIR) / "config.json"
    current = json.loads(cfg_path.read_text(encoding="utf-8"))
    # Preserve PAT if not sent
    if body.get("github_pat") in ("", "***", None):
        body["github_pat"] = current.get("github_pat", "")
    cfg_path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"message": "Config disimpan"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
