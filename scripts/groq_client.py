"""Shared Groq API client with rate-limit retries."""

import json
import os
import re
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_RETRY_AFTER_MESSAGE = re.compile(r"try again in ([\d.]+)\s*s", re.IGNORECASE)


def parse_rate_limit_wait_seconds(response: requests.Response) -> float:
    """Seconds to wait before retrying a rate-limited Groq request."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass

    message = response.text
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message", message)
    except (json.JSONDecodeError, AttributeError):
        pass

    match = _RETRY_AFTER_MESSAGE.search(message)
    if match:
        return max(float(match.group(1)), 1.0)

    return 30.0


def parse_groq_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def groq_chat_json(
    messages: list,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    max_retries: int = 8,
    timeout: int = 120,
) -> dict:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GROQ_API_KEY. Add it to .env for Groq script generation.")

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(1, max_retries + 1):
        response = requests.post(
            GROQ_URL, headers=headers, json=payload, timeout=timeout
        )

        if response.status_code == 429:
            wait = parse_rate_limit_wait_seconds(response) + 2.0
            print(
                f"  Groq rate limit (TPM) — waiting {wait:.0f}s "
                f"(retry {attempt}/{max_retries})..."
            )
            time.sleep(wait)
            last_error = response.text
            continue

        if response.status_code >= 500:
            wait = min(10 * attempt, 60)
            print(
                f"  Groq server error {response.status_code} — "
                f"waiting {wait}s (retry {attempt}/{max_retries})..."
            )
            time.sleep(wait)
            last_error = response.text
            continue

        if response.status_code != 200:
            raise RuntimeError(
                f"Groq API error {response.status_code}: {response.text}"
            )

        raw = response.json()["choices"][0]["message"]["content"]
        return parse_groq_json(raw)

    raise RuntimeError(
        f"Groq API rate limit persisted after {max_retries} retries: {last_error}"
    )


def groq_part_cooldown(label: str = "next part") -> None:
    """Pause between back-to-back Groq calls to avoid TPM bursts."""
    secs = float(os.getenv("GROQ_PART_COOLDOWN_SEC", "25"))
    if secs <= 0:
        return
    print(f"  Pausing {secs:.0f}s before {label} (Groq TPM limit)...")
    time.sleep(secs)
