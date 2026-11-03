"""
GitHub Scanner — Membaca file dan repositori via GitHub REST API (Read-Only).
Zero external dependency (urllib).
"""

import json
import base64
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Tuple

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".json", ".yaml", ".yml", ".sql", ".sh", ".bash",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".php", ".rb", ".toml", ".env.example"
}

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".next", ".nuxt", "vendor"
}


class GitHubRepoReader:
    BASE_URL = "https://api.github.com"

    def __init__(self, repo_full_name: str, pat_token: Optional[str] = None):
        """
        repo_full_name: format 'owner/repo'
        pat_token: read-only GitHub Personal Access Token
        """
        self.repo = repo_full_name.strip().strip("/")
        self.token = pat_token.strip() if pat_token else ""

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Antigravity-BugHunter/1.0"
        }
        if self.token:
            h["Authorization"] = f"token {self.token}"
        return h

    def test_access(self) -> Tuple[bool, str]:
        """Uji apakah repo bisa diakses dengan token ini."""
        url = f"{self.BASE_URL}/repos/{self.repo}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                default_branch = data.get("default_branch", "main")
                visibility = "Private" if data.get("private") else "Public"
                return True, f"✅ Akses OK: {self.repo} ({visibility}, branch: {default_branch})"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, f"❌ Repo tidak ditemukan (404). Periksa nama repo atau izin token."
            if e.code == 401:
                return False, f"❌ Token tidak valid (401 Unauthorized)."
            return False, f"❌ HTTP Error {e.code}: {e.reason}"
        except Exception as e:
            return False, f"❌ Error koneksi: {e}"

    def get_repo_files(self) -> List[dict]:
        """
        Mengambil semua file source code yang relevan dari repo.
        Return: list of {'path': str, 'size': int, 'sha': str}
        """
        # 1. Dapatkan default branch
        url_repo = f"{self.BASE_URL}/repos/{self.repo}"
        req_repo = urllib.request.Request(url_repo, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req_repo, timeout=15) as resp:
                rdata = json.loads(resp.read().decode("utf-8"))
                branch = rdata.get("default_branch", "main")
        except Exception:
            branch = "main"

        # 2. Ambil recursive tree
        url_tree = f"{self.BASE_URL}/repos/{self.repo}/git/trees/{branch}?recursive=1"
        req_tree = urllib.request.Request(url_tree, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req_tree, timeout=25) as resp:
                tdata = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise Exception(f"Gagal mengambil daftar file: {e}")

        tree = tdata.get("tree", [])
        code_files = []

        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item.get("path", "")
            size = item.get("size", 0)

            # Skip file terlalu besar (> 100 KB) agar context window hemat
            if size > 100_000:
                continue

            # Cek direktori yang diabaikan
            parts = path.split("/")
            if any(p in IGNORE_DIRS for p in parts[:-1]):
                continue

            # Cek ekstensi
            ext = "." + path.split(".")[-1].lower() if "." in path else ""
            if ext in CODE_EXTENSIONS:
                code_files.append({
                    "path": path,
                    "size": size,
                    "sha": item.get("sha", "")
                })

        return code_files

    def get_file_content(self, file_path: str) -> Optional[str]:
        """Mengambil isi teks dari sebuah file."""
        url = f"{self.BASE_URL}/repos/{self.repo}/contents/{file_path}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content_b64 = data.get("content", "")
                encoding = data.get("encoding", "")
                if encoding == "base64":
                    return base64.b64decode(content_b64).decode("utf-8", errors="replace")
                return content_b64
        except Exception as e:
            return None
