"""Qwen, through the hackathon gateway.

The desk's language layer is provider-shaped, not vendor-shaped: a model turns text
into structure and structure into English, and never produces a number that reaches a
decision. That makes the provider swappable, and this is the second one.

The gateway speaks the OpenAI chat-completions shape, so this is a small client rather
than a dependency. Two details it does not share with the OpenAI SDK:

* The model reasons before answering and returns that separately as
  ``reasoning_content``. Only ``content`` is the answer; reading the wrong one gets you
  the model talking to itself.
* ``response_format={"type": "json_object"}`` is honoured but not guaranteed - a
  reasoning model occasionally wraps the object in a fenced block. The parser handles
  both rather than failing on a formatting difference.

Every call is a plain POST with its own retry. The shared ``HttpClient`` is deliberately
GET-only, and bending it to carry a body would make it worse at the job it has.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://hackathon.bitgetops.com/v1"
MODEL = "qwen3.8-max"
KEY_ENV = "BITGET_QWEN_API_KEY"

RETRYABLE = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class QwenError(RuntimeError):
    """The gateway refused, or answered with something that is not an answer."""


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class Answer:
    text: str
    usage: Usage
    model: str


def credentials_present() -> bool:
    return bool(os.environ.get(KEY_ENV, "").strip())


def _strip_fence(text: str) -> str:
    m = _FENCE.match(text)
    return m.group(1) if m else text


class QwenClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = MODEL,
        timeout: float = 120.0,
        max_attempts: int = 4,
        rate_per_sec: float = 2.0,
    ):
        key = api_key or os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise QwenError(f"{KEY_ENV} is not set")
        self.model = model
        self._max_attempts = max_attempts
        self._min_gap = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._last_call = 0.0
        self._client = httpx.Client(
            base_url=(base_url or os.environ.get("BITGET_QWEN_BASE_URL") or BASE_URL).rstrip("/"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> QwenClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        max_tokens: int = 1200,
        temperature: float | None = None,
        json_object: bool = False,
    ) -> Answer:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if json_object:
            body["response_format"] = {"type": "json_object"}

        last: Exception | None = None
        for attempt in range(self._max_attempts):
            gap = self._min_gap - (time.monotonic() - self._last_call)
            if gap > 0:
                time.sleep(gap)
            try:
                resp = self._client.post("/chat/completions", json=body)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
                self._backoff(attempt)
                continue
            finally:
                self._last_call = time.monotonic()

            if resp.status_code in RETRYABLE:
                last = QwenError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code >= 400:
                raise QwenError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return _answer(resp.json())
        raise QwenError(f"gave up after {self._max_attempts} attempts: {last}")

    def chat_json(self, messages: list[dict[str, str]], *, system: str | None = None, max_tokens: int = 1200) -> tuple[dict[str, Any], Usage]:
        """A chat turn whose answer must be one JSON object.

        Raises rather than returning a half-parsed dict: a caller that wanted structure
        and got prose should hear about it, not silently act on empty fields.
        """
        answer = self.chat(messages, system=system, max_tokens=max_tokens, json_object=True)
        raw = _strip_fence(answer.text)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QwenError(f"expected one JSON object, got {answer.text[:200]!r}") from exc
        if not isinstance(parsed, dict):
            raise QwenError(f"expected a JSON object, got {type(parsed).__name__}")
        return parsed, answer.usage

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                time.sleep(min(30.0, float(retry_after)))
                return
            except ValueError:
                pass
        time.sleep(min(20.0, (2**attempt) * random.uniform(0.5, 1.5)))


def _answer(payload: dict[str, Any]) -> Answer:
    choices = payload.get("choices") or []
    if not choices:
        raise QwenError(f"no choices in the response: {str(payload)[:200]}")
    message = choices[0].get("message") or {}
    # `reasoning_content` is the model thinking out loud and is not the answer.
    text = (message.get("content") or "").strip()
    if not text:
        raise QwenError("the model returned an empty answer")
    u = payload.get("usage") or {}
    details = u.get("completion_tokens_details") or {}
    return Answer(
        text=text,
        usage=Usage(
            prompt_tokens=int(u.get("prompt_tokens") or 0),
            completion_tokens=int(u.get("completion_tokens") or 0),
            reasoning_tokens=int(details.get("reasoning_tokens") or 0),
        ),
        model=str(payload.get("model") or ""),
    )
