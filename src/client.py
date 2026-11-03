"""
Claude Web Session Client — menggunakan curl_cffi untuk bypass Cloudflare
Mendukung claude.ai free accounts via sessionKey cookie
"""

import json
import re
import time
from typing import Optional, Tuple

try:
    from curl_cffi import requests as cffi_requests
    CFFI_AVAILABLE = True
except ImportError:
    import requests as cffi_requests
    CFFI_AVAILABLE = False


class ClaudeAuthError(Exception):
    """Session key tidak valid / expired"""
    pass


class ClaudeRateLimitError(Exception):
    """Akun kena 5-jam rate limit"""
    pass


class ClaudeWebSessionClient:
    """
    Client untuk claude.ai web via sessionKey cookie.
    Menggunakan curl_cffi Chrome impersonation untuk bypass Cloudflare.
    """

    BASE_URL = "https://api.claude.ai/api"
    IMPERSONATE = "chrome120"

    RATE_LIMIT_PHRASES = [
        "usage limit",
        "rate limit",
        "too many requests",
        "you've reached",
        "quota",
        "exceeded",
    ]

    def __init__(self, session_key: str, conv_id: str, org_id: Optional[str] = None):
        self.session_key = session_key
        self.conv_id = conv_id
        self._org_id = org_id
        self._session = self._make_session()

    def _make_session(self):
        if CFFI_AVAILABLE:
            s = cffi_requests.Session(impersonate=self.IMPERSONATE)
        else:
            import requests
            s = requests.Session()
        s.headers.update(self._base_headers())
        return s

    def _base_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/event-stream",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "anthropic-client-platform": "web_claude_ai",
            "anthropic-client-version": "2024-03-01",
            "Content-Type": "application/json",
            "Origin": "https://claude.ai",
            "Referer": "https://claude.ai/",
            "Cookie": f"sessionKey={self.session_key}",
        }

    # ------------------------------------------------------------------
    # Org ID
    # ------------------------------------------------------------------

    def get_org_id(self) -> str:
        """Ambil org_id dari API. Di-cache setelah pertama kali."""
        if self._org_id:
            return self._org_id

        url = f"{self.BASE_URL}/organizations"
        try:
            resp = self._session.get(url, timeout=20)
        except Exception as e:
            raise ClaudeAuthError(f"Gagal koneksi ke claude.ai: {e}")

        if resp.status_code == 401:
            raise ClaudeAuthError("Session key tidak valid atau sudah expired (401)")
        if resp.status_code == 403:
            raise ClaudeAuthError("Akses ditolak — mungkin Cloudflare block (403)")
        if resp.status_code != 200:
            raise ClaudeAuthError(f"Unexpected status {resp.status_code}")

        try:
            orgs = resp.json()
            self._org_id = orgs[0]["uuid"]
            return self._org_id
        except (KeyError, IndexError, ValueError) as e:
            raise ClaudeAuthError(f"Gagal parse org_id: {e}")

    # ------------------------------------------------------------------
    # Send message
    # ------------------------------------------------------------------

    def send_message(self, prompt: str) -> str:
        """
        Kirim pesan ke TAPIR conv_id. Return full response text.
        Raise ClaudeRateLimitError jika kena limit.
        Raise ClaudeAuthError jika auth gagal.
        """
        org_id = self.get_org_id()
        url = (
            f"{self.BASE_URL}/organizations/{org_id}"
            f"/chat_conversations/{self.conv_id}/completion"
        )

        payload = {
            "prompt": prompt,
            "timezone": "Asia/Jakarta",
            "attachments": [],
            "files": [],
        }

        try:
            resp = self._session.post(
                url,
                json=payload,
                stream=True,
                timeout=120,
            )
        except Exception as e:
            raise ClaudeAuthError(f"Request error: {e}")

        if resp.status_code == 401:
            raise ClaudeAuthError("Session expired (401)")
        if resp.status_code == 403:
            raise ClaudeAuthError("Cloudflare / auth block (403)")
        if resp.status_code == 429:
            raise ClaudeRateLimitError("Rate limited (429)")

        if resp.status_code != 200:
            raise ClaudeAuthError(f"Unexpected HTTP {resp.status_code}")

        # Parse SSE stream
        return self._parse_sse(resp)

    def _parse_sse(self, resp) -> str:
        """Parse Server-Sent Events dan kumpulkan teks."""
        collected = []
        try:
            for raw_line in resp.iter_lines():
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace")
                else:
                    line = raw_line

                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if data_str in ("", "[DONE]"):
                    continue

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Claude SSE event types
                etype = data.get("type", "")

                if etype == "content_block_delta":
                    delta = data.get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        collected.append(text)

                elif etype == "message_delta":
                    # Check stop reason
                    stop = data.get("delta", {}).get("stop_reason", "")
                    if stop == "end_turn":
                        break

                elif etype == "error":
                    err_msg = data.get("error", {}).get("message", "")
                    err_lower = err_msg.lower()
                    if any(p in err_lower for p in self.RATE_LIMIT_PHRASES):
                        raise ClaudeRateLimitError(f"Rate limit: {err_msg}")
                    raise ClaudeAuthError(f"SSE error: {err_msg}")

        except (ClaudeRateLimitError, ClaudeAuthError):
            raise
        except Exception as e:
            if collected:
                pass  # partial response still usable
            else:
                raise ClaudeAuthError(f"Stream parse error: {e}")

        full_text = "".join(collected)

        # Cek rate limit dalam teks response
        lower = full_text.lower()
        if any(p in lower for p in self.RATE_LIMIT_PHRASES) and len(full_text) < 300:
            raise ClaudeRateLimitError(f"Rate limit detected in response text")

        return full_text

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------

    def test_connection(self) -> Tuple[bool, str]:
        """Ping test untuk Vault tab. Return (success, message)."""
        try:
            org_id = self.get_org_id()
            return True, f"✅ OK — org_id: {org_id[:8]}..."
        except ClaudeAuthError as e:
            return False, f"❌ Auth Error: {e}"
        except Exception as e:
            return False, f"❌ Error: {e}"


# ------------------------------------------------------------------
# Legacy client (Anthropic official API — kept for backward compat)
# ------------------------------------------------------------------

class ClaudeWebClient:
    """Legacy official API client — tidak dipakai di mode claude_web."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key
        self.model = model

    def send_message(self, messages: list, system: str = "", max_tokens: int = 8096) -> str:
        raise NotImplementedError(
            "ClaudeWebClient (official API) tidak dipakai di mode claude_web. "
            "Gunakan ClaudeWebSessionClient."
        )

    def test_connection(self) -> Tuple[bool, str]:
        return False, "Official API client tidak aktif di mode claude_web"
