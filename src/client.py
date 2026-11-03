"""
AI Client Engine — Google Gemini & Groq REST APIs
Mendukung multi-turn conversation memory, dynamic model switching,
dan deteksi Rate Limit (429) untuk auto-failover antar akun/key.
"""

import json
import time
from typing import List, Dict, Tuple, Optional
import requests


class AIRateLimitError(Exception):
    """Kena 429 Resource Exhausted / TPM / RPM limit"""
    pass


class AIAuthError(Exception):
    """API Key invalid / unauthorized (401 / 403)"""
    pass


class BaseAIClient:
    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        raise NotImplementedError

    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError


# ────────────────────────────────────────────────────────────────
# Google Gemini Client (Official v1beta REST)
# ────────────────────────────────────────────────────────────────
class GeminiClient(BaseAIClient):
    """
    Client resmi Google Gemini API via REST.
    Tahan banting, ringan, tidak ada masalah versi package.
    """
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model or "gemini-2.0-flash"

    def _convert_history(self, history: List[Dict[str, str]], prompt: str) -> List[dict]:
        """Konversi riwayat format standar [{role, content}] ke format Gemini contents."""
        contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })
        return contents

    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"
        contents = self._convert_history(history, prompt)
        
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096,
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=90)
        except Exception as e:
            raise AIAuthError(f"Gagal koneksi ke Gemini API: {e}")

        if resp.status_code == 429:
            raise AIRateLimitError("Gemini Quota Exceeded (429). Butuh cooldown atau ganti key.")
        if resp.status_code in (400, 401, 403):
            err_msg = resp.text
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise AIAuthError(f"Gemini Auth Error ({resp.status_code}): {err_msg}")
        if resp.status_code != 200:
            raise Exception(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                # Periksa finishReason atau promptFeedback
                fb = data.get("promptFeedback", {})
                return f"[No candidate returned. Feedback: {fb}]"
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            return text
        except Exception as e:
            raise Exception(f"Gagal parsing respons Gemini: {e}")

    def test_connection(self) -> Tuple[bool, str]:
        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "Ping test: balas dengan kata OK"}]}]
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return True, f"✅ Gemini OK ({self.model})"
            elif resp.status_code == 429:
                return False, "⏳ Rate Limited (429)"
            else:
                return False, f"❌ Error {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            return False, f"❌ Connection Error: {e}"


# ────────────────────────────────────────────────────────────────
# Groq Client (Official OpenAI-Compatible REST)
# ────────────────────────────────────────────────────────────────
class GroqClient(BaseAIClient):
    """
    Client resmi Groq Cloud API via OpenAI-compatible endpoint.
    Super cepat (Llama 3.3 70B, Llama 3.1 8B).
    """
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model or "llama-3.3-70b-versatile"

    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        messages = list(history)
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=90)
        except Exception as e:
            raise AIAuthError(f"Gagal koneksi ke Groq API: {e}")

        if resp.status_code == 429:
            raise AIRateLimitError("Groq Rate Limit Reached (429 TPM/RPM). Auto-rotating node...")
        if resp.status_code in (401, 403):
            err_msg = resp.text
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise AIAuthError(f"Groq Auth Error ({resp.status_code}): {err_msg}")
        if resp.status_code != 200:
            raise Exception(f"Groq HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise Exception(f"Gagal parsing respons Groq: {e}")

    def test_connection(self) -> Tuple[bool, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Ping: say PONG"}],
            "max_tokens": 10
        }
        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                return True, f"✅ Groq OK ({self.model})"
            elif resp.status_code == 429:
                return False, "⏳ Groq Rate Limited (429)"
            else:
                return False, f"❌ Groq Error {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            return False, f"❌ Connection Error: {e}"


def get_ai_client(provider: str, api_key: str, model: Optional[str] = None) -> BaseAIClient:
    """Factory helper untuk instansiasi AI client sesuai provider."""
    provider_lower = (provider or "").strip().lower()
    if "groq" in provider_lower:
        default_model = model or "llama-3.3-70b-versatile"
        return GroqClient(api_key=api_key, model=default_model)
    else:
        # Default: Gemini
        default_model = model or "gemini-2.0-flash"
        return GeminiClient(api_key=api_key, model=default_model)
