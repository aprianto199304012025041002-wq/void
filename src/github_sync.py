"""
GitHub Cloud Storage Sync — Multi-Repo Isolated Storage.
Menyimpan dan memulihkan laporan bug per repositori secara terpisah
ke branch 'audit-reports' di repository GitHub.
Zero external dependency (urllib).
"""

import json
import base64
import urllib.request
import urllib.error
from typing import Optional, Tuple, List

DEFAULT_STORAGE_OWNER = "aprianto199304012025041002-wq"
DEFAULT_STORAGE_REPO  = "void"
DEFAULT_BRANCH        = "audit-reports"


def get_safe_report_path(repo_full_name: str) -> str:
    """Mengubah 'owner/repo' menjadi 'reports/owner_repo_bug_report.md'."""
    clean = repo_full_name.strip().strip("/").replace("/", "_").replace(" ", "_")
    return f"reports/{clean}_bug_report.md"


class GitHubReportSyncer:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str, storage_owner: str = DEFAULT_STORAGE_OWNER, storage_repo: str = DEFAULT_STORAGE_REPO):
        self.token = token.strip() if token else ""
        self.owner = storage_owner
        self.repo = storage_repo
        self.branch = DEFAULT_BRANCH

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AntigravitySync/2.0",
            "Content-Type": "application/json"
        }
        if self.token:
            h["Authorization"] = f"token {self.token}"
        return h

    def fetch_report(self, target_repo_full_name: str) -> Optional[str]:
        """Mengambil isi file bug report khusus untuk target repo tertentu dari branch audit-reports."""
        if not self.token:
            return None
        file_path = get_safe_report_path(target_repo_full_name)
        url = f"{self.BASE_URL}/repos/{self.owner}/{self.repo}/contents/{file_path}?ref={self.branch}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content_b64 = data.get("content", "")
                if content_b64:
                    return base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            pass
        return None

    def push_report(self, target_repo_full_name: str, markdown_content: str) -> Tuple[bool, str]:
        """Commit dan push file laporan khusus target repo ke branch audit-reports."""
        if not self.token:
            return False, "Token GitHub PAT tidak tersedia untuk auto-sync."

        file_path = get_safe_report_path(target_repo_full_name)
        url = f"{self.BASE_URL}/repos/{self.owner}/{self.repo}/contents/{file_path}?ref={self.branch}"

        # 1. Ambil SHA jika file sudah ada
        sha = None
        req_get = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req_get, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sha = data.get("sha")
        except Exception:
            sha = None

        # 2. Siapkan payload PUT
        b64_content = base64.b64encode(markdown_content.encode("utf-8")).decode("ascii")
        commit_msg = f"📝 Update {file_path} [skip ci]"
        payload = {
            "message": commit_msg,
            "content": b64_content,
            "branch": self.branch
        }
        if sha:
            payload["sha"] = sha

        data_bytes = json.dumps(payload).encode("utf-8")
        req_put = urllib.request.Request(url, data=data_bytes, headers=self._headers(), method="PUT")

        try:
            with urllib.request.urlopen(req_put, timeout=20) as resp:
                if resp.status in (200, 201):
                    return True, f"✅ Laporan untuk {target_repo_full_name} berhasil disimpan di branch 'audit-reports' ({file_path})."
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            return False, f"HTTP {e.code}: {err}"
        except Exception as e:
            return False, f"Sync error: {e}"

        return False, "Gagal melakukan sync."

    def list_saved_reports(self) -> List[dict]:
        """Melihat daftar semua file laporan yang tersimpan di folder reports/."""
        if not self.token:
            return []
        url = f"{self.BASE_URL}/repos/{self.owner}/{self.repo}/contents/reports?ref={self.branch}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                items = json.loads(resp.read().decode("utf-8"))
                return [
                    {"name": item["name"], "path": item["path"], "download_url": item.get("download_url")}
                    for item in items if item.get("type") == "file" and item.get("name", "").endswith(".md")
                ]
        except Exception:
            return []
