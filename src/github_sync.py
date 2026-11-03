"""
GitHub Cloud Storage Sync.
Menyimpan dan memulihkan laporan bug (bug_report.md) secara persisten
ke branch 'audit-reports' di repository GitHub menggunakan GitHub API.
Zero external dependency (urllib).
"""

import json
import base64
import urllib.request
import urllib.error
from typing import Optional, Tuple

DEFAULT_REPO_OWNER = "aprianto199304012025041002-wq"
DEFAULT_REPO_NAME  = "void"
DEFAULT_BRANCH     = "audit-reports"
DEFAULT_FILE_PATH  = "bug_report.md"


class GitHubReportSyncer:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str, owner: str = DEFAULT_REPO_OWNER, repo: str = DEFAULT_REPO_NAME):
        self.token = token.strip() if token else ""
        self.owner = owner
        self.repo = repo
        self.branch = DEFAULT_BRANCH

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AntigravitySync/1.0",
            "Content-Type": "application/json"
        }
        if self.token:
            h["Authorization"] = f"token {self.token}"
        return h

    def fetch_latest_report(self) -> Optional[str]:
        """Mengambil isi file bug_report.md terakhir dari GitHub."""
        if not self.token:
            return None
        url = f"{self.BASE_URL}/repos/{self.owner}/{self.repo}/contents/{DEFAULT_FILE_PATH}?ref={self.branch}"
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

    def push_report(self, markdown_content: str, commit_msg: str = "📝 Update bug_report.md [skip ci]") -> Tuple[bool, str]:
        """Commit dan push file bug_report.md ke branch audit-reports."""
        if not self.token:
            return False, "Token GitHub PAT tidak tersedia untuk auto-sync."

        # 1. Ambil SHA file jika sudah ada
        url = f"{self.BASE_URL}/repos/{self.owner}/{self.repo}/contents/{DEFAULT_FILE_PATH}?ref={self.branch}"
        req_get = urllib.request.Request(url, headers=self._headers(), method="GET")
        sha = None
        try:
            with urllib.request.urlopen(req_get, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sha = data.get("sha")
        except Exception:
            sha = None

        # 2. Siapkan payload PUT
        b64_content = base64.b64encode(markdown_content.encode("utf-8")).decode("ascii")
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
                    return True, "✅ Laporan berhasil di-sync ke GitHub branch 'audit-reports'."
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            return False, f"HTTP {e.code}: {err}"
        except Exception as e:
            return False, f"Sync error: {e}"

        return False, "Gagal melakukan sync."
