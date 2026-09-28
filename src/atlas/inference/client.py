"""Async TypeSafe Jev client: one POST per attempt, every attempt observable.

The client runs its own retry loop (the TypeSafe SDK retries silently) so each
network attempt lands in the ledger exactly once. The API key is stored in a
private attribute and never appears in reprs, exceptions, or events.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import Any, Self

import httpx

from atlas.inference.validate import validate_answers

PRODUCTION_BASE = "https://api.typesafe.ai"
CANARY_PREFIX = "apikey_" + "0" * 36 + "_"
PINNED_MODEL = re.compile(r".+-\d+\.\d+\.\d+")
ENDPOINT = "/v1/systemone"


class ModelMismatch(RuntimeError):
    pass


class UnsafeEndpoint(RuntimeError):
    pass


def is_canary_key(key: str) -> bool:
    return key.startswith(CANARY_PREFIX)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    backoff_initial: float = 1.0
    backoff_max: float = 16.0
    retry_statuses: frozenset = field(
        default_factory=lambda: frozenset({408, 429, 500, 502, 503, 504, 529})
    )
    timeout_s: float = 30.0


DEFAULT_POLICY = RetryPolicy()


@dataclass
class Attempt:
    attempt: int
    started_at: str
    ended_at: str
    request_ms: float
    backoff_ms: float
    http_status: int | None
    request_id: str | None
    error_type: str | None
    validation: str
    input_tokens: int | None
    output_tokens: int | None
    model_returned: str | None
    charge_known: bool


@dataclass
class AttemptEvent:
    phase: str  # "before_send" | "after_response"
    attempt_no: int
    attempt: Attempt | None


@dataclass
class CallResult:
    ok: bool
    answers: dict | None
    attempts: list
    model_returned: str | None


@dataclass
class _Outcome:
    attempt: Attempt
    kind: str  # "ok" | "retry" | "fail" | "model_mismatch"
    answers: dict | None
    retry_after_s: float | None


class JevClient:
    def __init__(
        self,
        api_key: str,
        base: str,
        transport=None,
        policy: RetryPolicy = DEFAULT_POLICY,
    ):
        base = base.rstrip("/")
        on_production = base == PRODUCTION_BASE or base.startswith(
            PRODUCTION_BASE + "/"
        )
        if not on_production and not is_canary_key(api_key):
            raise UnsafeEndpoint(
                "refusing to send a non-canary key to a non-TypeSafe endpoint"
            )
        self._api_key = api_key
        self.base = base
        self.policy = policy
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        return f"JevClient(base={self.base!r})"

    @property
    def is_open(self) -> bool:
        return self._client is not None

    async def __aenter__(self) -> Self:
        await self._ensure_client()
        return self

    async def __aexit__(self, *exc) -> bool:
        await self.aclose()
        return False

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport, timeout=self.policy.timeout_s
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def evaluate(
        self, state: dict, questions: dict, model: str, on_attempt=None
    ) -> CallResult:
        client = await self._ensure_client()
        body = {"state": state, "model": model, "questions": questions}
        attempts: list[Attempt] = []
        schema_failures = 0
        backoff_ms = 0.0
        model_returned = None
        for n in range(1, self.policy.max_attempts + 1):
            if on_attempt is not None:
                await on_attempt(AttemptEvent("before_send", n, None))
            outcome = await self._one_attempt(client, body, model, questions, n, backoff_ms)
            attempt = outcome.attempt
            attempts.append(attempt)
            model_returned = attempt.model_returned or model_returned
            if on_attempt is not None:
                await on_attempt(AttemptEvent("after_response", n, attempt))
            if outcome.kind == "model_mismatch":
                raise ModelMismatch(
                    f"requested {model} but endpoint returned {attempt.model_returned}"
                )
            if outcome.kind == "ok":
                return CallResult(True, outcome.answers, attempts, model_returned)
            if outcome.kind == "schema":
                schema_failures += 1
            retryable = outcome.kind == "retry" or (
                outcome.kind == "schema" and schema_failures < 2
            )
            if not retryable or n == self.policy.max_attempts:
                return CallResult(False, None, attempts, model_returned)
            delay = (
                outcome.retry_after_s
                if outcome.retry_after_s is not None
                else min(
                    self.policy.backoff_max,
                    self.policy.backoff_initial * 2 ** (n - 1),
                )
            )
            if delay > 0:
                await asyncio.sleep(delay)
            backoff_ms = delay * 1000.0
        return CallResult(False, None, attempts, model_returned)

    async def _one_attempt(
        self, client, body, model, questions, n: int, backoff_ms: float
    ) -> _Outcome:
        started_at = _utcnow()
        t0 = time.monotonic()
        try:
            response = await client.post(
                f"{self.base}{ENDPOINT}",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self.policy.timeout_s,
            )
        except httpx.ConnectError:
            return _Outcome(
                self._net_attempt(n, started_at, t0, backoff_ms, "connection", True, 0),
                "retry",
                None,
                None,
            )
        except (httpx.ConnectTimeout, httpx.PoolTimeout):
            return _Outcome(
                self._net_attempt(n, started_at, t0, backoff_ms, "timeout", True, 0),
                "retry",
                None,
                None,
            )
        except httpx.TimeoutException:
            return _Outcome(
                self._net_attempt(n, started_at, t0, backoff_ms, "timeout", False, None),
                "retry",
                None,
                None,
            )
        except httpx.TransportError:
            return _Outcome(
                self._net_attempt(n, started_at, t0, backoff_ms, "connection", False, None),
                "retry",
                None,
                None,
            )
        request_ms = (time.monotonic() - t0) * 1000.0
        retry_after = _retry_after_seconds(response)
        if response.status_code != 200:
            error_type, charge_known, tokens = _classify_status(response.status_code)
            attempt = Attempt(
                n,
                started_at,
                _utcnow(),
                request_ms,
                backoff_ms,
                response.status_code,
                response.headers.get("x-typesafe-request-id"),
                error_type,
                "not_attempted",
                tokens,
                tokens,
                None,
                charge_known,
            )
            kind = (
                "retry"
                if response.status_code in self.policy.retry_statuses
                else "fail"
            )
            return _Outcome(attempt, kind, None, retry_after)
        try:
            parsed = response.json()
        except JSONDecodeError:
            return _Outcome(
                Attempt(
                    n,
                    started_at,
                    _utcnow(),
                    request_ms,
                    backoff_ms,
                    200,
                    response.headers.get("x-typesafe-request-id"),
                    "invalid_json",
                    "invalid_json",
                    None,
                    None,
                    None,
                    False,
                ),
                "retry",
                None,
                retry_after,
            )
        model_returned = parsed.get("model") if isinstance(parsed, dict) else None
        usage = parsed.get("usage") if isinstance(parsed, dict) else None
        charge_known = isinstance(usage, dict) and _is_int(usage.get("input_tokens"))
        input_tokens = usage["input_tokens"] if charge_known else None
        output_tokens = (
            usage.get("output_tokens")
            if charge_known and _is_int(usage.get("output_tokens"))
            else None
        )
        mismatch = (
            bool(model_returned)
            and PINNED_MODEL.fullmatch(model) is not None
            and model_returned != model
        )
        if not isinstance(parsed, dict) or not validate_answers(questions, parsed) or mismatch:
            return _Outcome(
                Attempt(
                    n,
                    started_at,
                    _utcnow(),
                    request_ms,
                    backoff_ms,
                    200,
                    response.headers.get("x-typesafe-request-id"),
                    "schema",
                    "schema",
                    input_tokens,
                    output_tokens,
                    model_returned,
                    charge_known,
                ),
                "model_mismatch" if mismatch else "schema",
                None,
                retry_after,
            )
        return _Outcome(
            Attempt(
                n,
                started_at,
                _utcnow(),
                request_ms,
                backoff_ms,
                200,
                response.headers.get("x-typesafe-request-id"),
                None,
                "ok",
                input_tokens,
                output_tokens,
                model_returned,
                charge_known,
            ),
            "ok",
            parsed["answers"],
            None,
        )

    def _net_attempt(
        self, n, started_at, t0, backoff_ms, error_type, charge_known, tokens
    ) -> Attempt:
        return Attempt(
            n,
            started_at,
            _utcnow(),
            (time.monotonic() - t0) * 1000.0,
            backoff_ms,
            None,
            None,
            error_type,
            "not_attempted",
            tokens,
            tokens,
            None,
            charge_known,
        )


def _classify_status(status: int) -> tuple[str, bool, int | None]:
    """(error_type, charge_known, tokens) for a non-200 status. Every 4xx is a
    known zero-token charge; 5xx charges are unknown."""
    if status == 429:
        return "rate_limited", True, 0
    if status in (401, 403):
        return "auth", True, 0
    if status == 408:
        return "timeout", True, 0
    if 400 <= status < 500:
        return "invalid_request", True, 0
    if status == 529:
        return "overloaded", False, None
    return "server_error", False, None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None
