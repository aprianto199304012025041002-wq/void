"""
AI Client Engine — Google Gemini & Groq REST APIs
Mendukung multi-turn conversation memory, auto-model fallback (503/404 handling),
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
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    FALLBACK_MODELS = [
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-flash-latest"
    ]

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview"):
        self.api_key = api_key
        # Jika model default adalah gemini-3.8-flash atau gemini-2.0, map ke model aktif
        self.model = model or "gemini-3-flash-preview"

    def _convert_history(self, history: List[Dict[str, str]], prompt: str) -> List[dict]:
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
        contents = self._convert_history(history, prompt)
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096,
            }
        }

        # Coba model utama, jika 503 / 404 coba fallback
        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]

        last_error = ""
        for m in models_to_try:
            url = f"{self.BASE_URL}/{m}:generateContent?key={self.api_key}"
            try:
                resp = requests.post(url, json=payload, timeout=60)
            except Exception as e:
                raise AIAuthError(f"Koneksi gagal ke Gemini: {e}")

            if resp.status_code == 200:
                self.model = m  # Simpan model yang sukses
                data = resp.json()
                try:
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        return "".join(p.get("text", "") for p in parts)
                    fb = data.get("promptFeedback", {})
                    return f"[Feedback: {fb}]"
                except Exception as e:
                    raise Exception(f"Gagal parse JSON Gemini: {e}")

            elif resp.status_code == 429:
                raise AIRateLimitError("Gemini Quota Exceeded (429).")
            elif resp.status_code in (401, 403):
                raise AIAuthError(f"Gemini Auth Gagal ({resp.status_code}): {resp.text[:200]}")
            elif resp.status_code in (404, 503):
                last_error = f"Model {m} status {resp.status_code}"
                continue
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                break

        raise Exception(f"Semua model Gemini gagal: {last_error}")

    def test_connection(self) -> Tuple[bool, str]:
        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}]
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return True, f"✅ Gemini OK ({self.model})"
            elif resp.status_code == 429:
                return False, "⏳ Rate Limited (429)"
            else:
                # Coba fallback
                for fb in self.FALLBACK_MODELS:
                    u2 = f"{self.BASE_URL}/{fb}:generateContent?key={self.api_key}"
                    r2 = requests.post(u2, json=payload, timeout=10)
                    if r2.status_code == 200:
                        self.model = fb
                        return True, f"✅ Gemini OK ({fb})"
                return False, f"❌ Error {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            return False, f"❌ Koneksi Error: {e}"


# ────────────────────────────────────────────────────────────────
# Groq Client (Official OpenAI-Compatible REST)
# ────────────────────────────────────────────────────────────────
class GroqClient(BaseAIClient):
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
            raise AIAuthError(f"Gagal koneksi ke Groq: {e}")

        if resp.status_code == 429:
            raise AIRateLimitError("Groq Rate Limit Reached (429 TPM/RPM).")
        if resp.status_code in (401, 403):
            raise AIAuthError(f"Groq Auth Error ({resp.status_code}): {resp.text[:200]}")
        if resp.status_code != 200:
            raise Exception(f"Groq HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise Exception(f"Gagal parse respons Groq: {e}")

    def test_connection(self) -> Tuple[bool, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5
        }
        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                return True, f"✅ Groq OK ({self.model})"
            elif resp.status_code == 429:
                return False, "⏳ Groq Rate Limited (429)"
            else:
                return False, f"❌ Groq Error {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            return False, f"❌ Koneksi Error: {e}"


def get_ai_client(provider: str, api_key: str, model: Optional[str] = None) -> BaseAIClient:
    provider_lower = (provider or "").strip().lower()
    if "groq" in provider_lower:
        return GroqClient(api_key=api_key, model=model or "llama-3.3-70b-versatile")
    else:
        return GeminiClient(api_key=api_key, model=model or "gemini-3-flash-preview")
