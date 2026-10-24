"""Synchronous client for the Devin API v3 (organization-scoped sessions).

Docs: https://docs.devin.ai — bearer auth uses ``cog_`` credentials
(Personal Access Tokens or service-user keys). Legacy ``apk_`` keys do not
work against v3.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger("coldplate.devin")

DEFAULT_V3_BASE_URL = "https://api.devin.ai/v3"
DEFAULT_V1_BASE_URL = "https://api.devin.ai/v1"

# status_detail values that mean "Devin's turn is over" (non-exhaustive of API
# values; anything else on a live status keeps us polling).
FINISHED_DETAILS = {"finished", "waiting_for_user"}

# status_detail values that indicate a billing/quota/contract stop.
QUOTA_STATUS_DETAILS = {
    "usage_limit_exceeded",
    "out_of_credits",
    "out_of_quota",
    "no_quota_allocation",
    "payment_declined",
    "org_usage_limit_exceeded",
    "user_usage_limit_exceeded",
    "total_session_limit_exceeded",
    "contract_expired",
}

# Idempotent methods (GET/DELETE) may be retried on these statuses.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_MAX_MESSAGE_EXCERPT = 500


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class DevinError(Exception):
    """Base error for Devin API failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        detail: Optional[str] = None,
        session_id: Optional[str] = None,
        session_url: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.session_id = session_id
        self.session_url = session_url


class DevinConfigError(DevinError):
    """Missing or invalid local configuration (env vars / .env)."""


class DevinAuthError(DevinError):
    """HTTP 401 — bad or expired credential."""


class DevinPermissionError(DevinError):
    """HTTP 403 — credential lacks permission or plan disallows API sessions."""


class DevinNotFoundError(DevinError):
    """HTTP 404 — wrong org id or unknown session."""


class DevinRateLimitError(DevinError):
    """HTTP 429 after exhausting retries."""


class DevinQuotaError(DevinError):
    """Session suspended for a usage/quota/payment/contract reason."""


class DevinSessionFailed(DevinError):
    """Session errored, needs approval, or ended without structured output."""


class DevinTimeoutError(DevinError):
    """Session did not reach a terminal state within the allotted time."""


# --------------------------------------------------------------------------
# Settings / results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DevinSettings:
    api_key: str
    org_id: Optional[str] = None
    base_url: Optional[str] = None
    devin_mode: Optional[str] = None
    max_acu_limit: Optional[int] = None
    request_timeout_s: float = 30.0
    poll_interval_s: float = 8.0
    session_timeout_s: float = 900.0
    stale_grace_s: float = 90.0
    max_retries: int = 3

    @property
    def api_version(self) -> str:
        """v3 for 'cog_' credentials, v1 for legacy 'apk_' keys."""
        if self.api_key.startswith("cog_"):
            return "v3"
        if self.api_key.startswith("apk_"):
            return "v1"
        raise DevinConfigError(
            "DEVIN_API_KEY must start with 'cog_' (v3 Personal Access Token / "
            "service-user key) or 'apk_' (deprecated v1 legacy key)."
        )

    @property
    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url
        return DEFAULT_V3_BASE_URL if self.api_version == "v3" else DEFAULT_V1_BASE_URL

    def __repr__(self) -> str:  # never leak the token
        try:
            version = self.api_version
        except DevinConfigError:
            version = "invalid"
        return (
            "DevinSettings(api_key='***redacted***', "
            f"api_version={version!r}, org_id={self.org_id!r}, "
            f"base_url={self.base_url!r}, "
            f"devin_mode={self.devin_mode!r}, max_acu_limit={self.max_acu_limit!r}, "
            f"request_timeout_s={self.request_timeout_s!r}, "
            f"poll_interval_s={self.poll_interval_s!r}, "
            f"session_timeout_s={self.session_timeout_s!r}, "
            f"stale_grace_s={self.stale_grace_s!r}, "
            f"max_retries={self.max_retries!r})"
        )

    @classmethod
    def from_env(cls, dotenv_path: Optional[str] = None) -> "DevinSettings":
        """Load settings from environment / .env (python-dotenv, override=False).

        Raises DevinConfigError with actionable text when required values are
        missing or malformed. Empty strings are treated as unset.
        """
        from dotenv import load_dotenv

        load_dotenv(dotenv_path, override=False)

        def env(name: str) -> Optional[str]:
            v = os.environ.get(name)
            if v is None or not v.strip():
                return None
            return v.strip()

        api_key = env("DEVIN_API_KEY")
        if api_key is None:
            raise DevinConfigError(
                "DEVIN_API_KEY is not set. Create a Personal Access Token at "
                "app.devin.ai -> Settings -> Devin API -> 'PATs' (starts with 'cog_') "
                "and put it in .env."
            )
        if not (api_key.startswith("cog_") or api_key.startswith("apk_")):
            raise DevinConfigError(
                "DEVIN_API_KEY must start with 'cog_' (v3 Personal Access Token or "
                "service-user key) or 'apk_' (deprecated v1 legacy key)."
            )
        org_id = env("DEVIN_ORG_ID")
        version = "v3" if api_key.startswith("cog_") else "v1"
        if version == "v1":
            logger.warning(
                "Using deprecated Devin API v1 with a legacy API key; create a "
                "v3 Personal Access Token (cog_) for ACU reporting."
            )
        if version == "v3" and org_id is None:
            raise DevinConfigError(
                "DEVIN_ORG_ID is not set. Copy the organization id shown at the top of "
                "app.devin.ai -> Settings -> Devin API (starts with 'org-') into .env."
            )

        base_url = env("DEVIN_API_BASE_URL") or (
            DEFAULT_V3_BASE_URL if version == "v3" else DEFAULT_V1_BASE_URL
        )
        devin_mode = env("DEVIN_MODE")

        def _parse(name: str, cast: Callable[[str], Any]) -> Any:
            raw = env(name)
            if raw is None:
                return None
            try:
                return cast(raw)
            except (TypeError, ValueError):
                raise DevinConfigError(
                    f"{name}={raw!r} is not a valid value; fix or remove it from .env."
                )

        max_acu_limit = _parse("DEVIN_MAX_ACU_LIMIT", int)
        poll_interval_s = _parse("DEVIN_POLL_INTERVAL_S", float)
        session_timeout_s = _parse("DEVIN_SESSION_TIMEOUT_S", float)

        return cls(
            api_key=api_key,
            org_id=org_id,
            base_url=base_url,
            devin_mode=devin_mode,
            max_acu_limit=max_acu_limit,
            poll_interval_s=poll_interval_s if poll_interval_s is not None else 8.0,
            session_timeout_s=session_timeout_s if session_timeout_s is not None else 900.0,
        )


@dataclass
class SessionResult:
    session_id: str
    url: Optional[str]
    status: Optional[str]
    status_detail: Optional[str]
    structured_output: Optional[dict]
    acus_consumed: Optional[float]
    on_demand_usage: Optional[float]
    elapsed_s: float
    polls: int
    last_devin_message: Optional[str]
    raw: dict
    api_version: str = "v3"


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class DevinClient:
    def __init__(
        self,
        settings: DevinSettings,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.api_version = settings.api_version
        if self.api_version == "v3" and not settings.org_id:
            raise DevinConfigError(
                "DEVIN_ORG_ID is required for Devin API v3 (organization-scoped "
                "sessions); get it from app.devin.ai -> Settings -> Devin API."
            )
        self._sleep = sleep
        self._clock = clock
        self._session_urls: dict[str, str] = {}
        self._client = httpx.Client(
            base_url=settings.resolved_base_url,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(settings.request_timeout_s),
            transport=transport,
        )

    # -- low-level request with bounded retries -----------------------------

    def _problem(self, resp: httpx.Response) -> tuple[str, str]:
        try:
            data = resp.json()
        except Exception:
            data = None
        if isinstance(data, dict) and (data.get("title") or data.get("detail")):
            return str(data.get("title") or "Error"), str(data.get("detail") or "")
        body = (resp.text or "").strip()
        return resp.reason_phrase or "HTTP error", body[:300]

    @staticmethod
    def _hint(status: int) -> str:
        if status == 401:
            return (
                " Hint: check DEVIN_API_KEY — v3 requires a 'cog_' Personal Access "
                "Token or service-user key."
            )
        if status == 403:
            return (
                " Hint: the credential is likely missing the UseDevinSessions "
                "permission, or this plan does not allow API sessions."
            )
        if status == 404:
            return " Hint: check DEVIN_ORG_ID and the resource id in the URL."
        if status == 429:
            return " Hint: rate limited — back off or reduce request rate."
        if status >= 500:
            return " Hint: Devin-side error; retry later."
        return ""

    def _raise_for_status(
        self,
        resp: httpx.Response,
        method: str,
        path: str,
        session_id: Optional[str],
    ) -> None:
        title, detail = self._problem(resp)
        status = resp.status_code
        msg = f"Devin API {status} {title} on {method} {path}: {detail}{self._hint(status)}"
        kw = dict(status_code=status, detail=detail or title, session_id=session_id)
        if status == 401:
            raise DevinAuthError(msg, **kw)
        if status == 403:
            raise DevinPermissionError(msg, **kw)
        if status == 404:
            raise DevinNotFoundError(msg, **kw)
        if status == 429:
            raise DevinRateLimitError(msg, **kw)
        raise DevinError(msg, **kw)

    def _retry_delay(self, resp: Optional[httpx.Response], attempt: int) -> float:
        if resp is not None and resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    return min(float(ra), 60.0)
                except ValueError:
                    pass
        return float(2**attempt)  # 1s, 2s, 4s

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
        idempotent: bool = True,
        session_id: Optional[str] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.settings.max_retries + 1):
            resp: Optional[httpx.Response] = None
            try:
                resp = self._client.request(
                    method, path, json=json_body, params=params
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_exc = e
                retryable = True
            except httpx.TransportError as e:
                last_exc = e
                # Never re-issue a non-idempotent request that may have reached
                # the server (avoids duplicate sessions burning quota).
                retryable = idempotent
            else:
                if resp.status_code < 400:
                    return resp
                retryable = (
                    resp.status_code in RETRYABLE_STATUSES
                    if idempotent
                    else resp.status_code == 429
                )

            if not retryable or attempt >= self.settings.max_retries:
                break
            delay = self._retry_delay(resp, attempt)
            logger.warning(
                "Devin API attempt %d failed on %s %s; retrying in %.1fs",
                attempt + 1,
                method,
                path,
                delay,
            )
            self._sleep(delay)

        if resp is not None and resp.status_code >= 400:
            self._raise_for_status(resp, method, path, session_id)
        raise DevinError(
            f"Devin API request failed after {self.settings.max_retries + 1} attempts "
            f"on {method} {path}: {last_exc}"
        )

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        if not resp.content:
            return None
        return resp.json()

    # -- endpoints ----------------------------------------------------------

    _V1_STATUS_MAP = {
        "working": ("running", "working"),
        "blocked": ("running", "waiting_for_user"),
        "finished": ("running", "finished"),
        "expired": ("exit", None),
        "suspend_requested": ("suspended", "inactivity"),
        "suspend_requested_frontend": ("suspended", "inactivity"),
        "resume_requested": ("running", "working"),
        "resume_requested_frontend": ("running", "working"),
        "resumed": ("running", "working"),
    }

    def _normalize_v1_session(self, raw: dict, session_id: str) -> dict:
        enum_ = raw.get("status_enum")
        key = str(enum_ if enum_ else (raw.get("status") or "")).strip().lower()
        status, detail = self._V1_STATUS_MAP.get(key, ("running", "working"))
        return {
            "session_id": raw.get("session_id") or session_id,
            "url": raw.get("url") or self._session_urls.get(session_id),
            "status": status,
            "status_detail": detail,
            "structured_output": raw.get("structured_output"),
            "acus_consumed": None,
            "on_demand_usage": None,
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "tags": raw.get("tags"),
            "_v1_messages": raw.get("messages") or [],
        }

    def whoami(self) -> dict:
        """GET /self (v3) or GET /sessions?limit=1 (v1) -> principal info."""
        if self.api_version == "v1":
            self._request("GET", "/sessions", params={"limit": 1})
            return {"principal_type": "legacy_api_key", "api_version": "v1"}
        return self._json(self._request("GET", "/self"))

    def _sessions_path(self) -> str:
        if self.api_version == "v1":
            return "/sessions"
        return f"/organizations/{self.settings.org_id}/sessions"

    def create_session(
        self,
        prompt: str,
        *,
        structured_output_schema: Optional[dict] = None,
        structured_output_required: Optional[bool] = None,
        title: Optional[str] = None,
        tags: Optional[list] = None,
        devin_mode: Optional[str] = None,
        max_acu_limit: Optional[int] = None,
        resumable: bool = False,
    ) -> dict:
        body: dict[str, Any] = {"prompt": prompt}
        v1 = self.api_version == "v1"
        if not v1:
            body["resumable"] = resumable
        if title is not None:
            body["title"] = title
        if tags is not None:
            body["tags"] = list(tags)
        mode = devin_mode if devin_mode is not None else self.settings.devin_mode
        if mode is not None:
            if v1:
                logger.debug("devin_mode %r ignored: API v1 has no mode field", mode)
            else:
                body["devin_mode"] = mode
        acu = max_acu_limit if max_acu_limit is not None else self.settings.max_acu_limit
        if acu is not None:
            body["max_acu_limit"] = acu
        if structured_output_schema is not None:
            body["structured_output_schema"] = structured_output_schema
        if structured_output_required is not None and not v1:
            body["structured_output_required"] = structured_output_required
        resp = self._request(
            "POST", self._sessions_path(), json_body=body, idempotent=False
        )
        data = self._json(resp) or {}
        sid = data.get("session_id") or data.get("id")
        if sid and data.get("url"):
            self._session_urls[sid] = data["url"]
        logger.info("created Devin session %s (api %s)", sid, self.api_version)
        return data

    def get_session(self, session_id: str) -> dict:
        path = f"{self._sessions_path()}/{session_id}"
        data = self._json(self._request("GET", path, session_id=session_id))
        if self.api_version == "v1":
            return self._normalize_v1_session(data or {}, session_id)
        return data

    def list_messages(
        self, session_id: str, *, first: int = 200, max_pages: int = 50
    ) -> list[dict]:
        """Return all message items (v3 follows cursor pagination; v1 maps the
        messages embedded in the session body)."""
        if self.api_version == "v1":
            sess = self.get_session(session_id)
            out = []
            for m in sess.get("_v1_messages") or []:
                out.append(
                    {
                        "event_id": m.get("event_id"),
                        "source": (
                            "devin" if "devin" in str(m.get("type", "")).lower() else "user"
                        ),
                        "message": m.get("message"),
                        "created_at": m.get("timestamp"),
                    }
                )
            return out
        path = f"{self._sessions_path()}/{session_id}/messages"
        items: list[dict] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"first": first}
            if cursor:
                params["after"] = cursor
            data = self._json(
                self._request("GET", path, params=params, session_id=session_id)
            )
            items.extend(data.get("items") or [])
            if not data.get("has_next_page"):
                break
            cursor = data.get("end_cursor")
            if not cursor:
                break
        return items

    def send_message(self, session_id: str, message: str) -> Any:
        """POST a user message; auto-resumes a suspended session."""
        path = f"{self._sessions_path()}/{session_id}/message" + (
            "" if self.api_version == "v1" else "s"
        )
        data = self._json(
            self._request(
                "POST",
                path,
                json_body={"message": message},
                idempotent=False,
                session_id=session_id,
            )
        )
        if (
            self.api_version == "v1"
            and isinstance(data, dict)
            and data.get("detail")
        ):
            raise DevinSessionFailed(
                f"Devin API v1 rejected the message for session {session_id}: "
                f"{data['detail']}",
                session_id=session_id,
            )
        return data

    def terminate_session(self, session_id: str) -> None:
        """DELETE the session; a missing (or on v1 already-exited) session is fine."""
        path = f"{self._sessions_path()}/{session_id}"
        try:
            self._request("DELETE", path, session_id=session_id)
        except DevinNotFoundError:
            logger.info("session %s already gone", session_id)
        except DevinError as e:
            if (
                self.api_version == "v1"
                and e.status_code is not None
                and 400 <= e.status_code < 500
            ):
                logger.info(
                    "v1 session %s already exited (HTTP %s)", session_id, e.status_code
                )
            else:
                raise

    # -- polling ------------------------------------------------------------

    def _last_devin_message(self, session_id: str) -> Optional[str]:
        try:
            items = self.list_messages(session_id)
        except DevinError:
            return None
        for item in reversed(items):
            if item.get("source") == "devin" and item.get("message"):
                msg = str(item["message"])
                return msg[:_MAX_MESSAGE_EXCERPT]
        return None

    def _check_fatal(
        self, sess: dict, session_id: str, url: Optional[str]
    ) -> None:
        status = sess.get("status")
        detail = sess.get("status_detail")
        if status == "error":
            excerpt = self._last_devin_message(session_id)
            raise DevinSessionFailed(
                f"Devin session {session_id} entered error state"
                + (f"; last Devin message: {excerpt}" if excerpt else "")
                + (f" ({url})" if url else ""),
                session_id=session_id,
                session_url=url,
                detail=detail,
            )
        if detail == "waiting_for_approval":
            raise DevinSessionFailed(
                f"Devin session {session_id} is waiting_for_approval — approve it in "
                f"the Devin web app or relax the session approval policy, then resume "
                f"or recreate it ({url})",
                session_id=session_id,
                session_url=url,
                detail=detail,
            )
        if status in ("suspended", "exit") and detail in QUOTA_STATUS_DETAILS:
            raise DevinQuotaError(
                f"Devin session {session_id} stopped with status_detail={detail} — "
                f"organization ACU quota, billing, or contract limit reached ({url})",
                session_id=session_id,
                session_url=url,
                detail=detail,
            )

    def _wait(
        self,
        session_id: str,
        *,
        timeout_s: float,
        poll_interval_s: float,
        require_structured_output: bool,
        new_turn_gate: Optional[Callable[[dict], bool]] = None,
        on_poll: Optional[Callable[[dict], None]] = None,
    ) -> SessionResult:
        start = self._clock()
        deadline = start + timeout_s
        polls = 0
        new_turn_seen = new_turn_gate is None
        while True:
            sess = self.get_session(session_id)
            polls += 1
            if on_poll is not None:
                on_poll(sess)
            status = sess.get("status")
            detail = sess.get("status_detail")
            output = sess.get("structured_output")
            url = sess.get("url")

            self._check_fatal(sess, session_id, url)

            if not new_turn_seen and new_turn_gate is not None:
                new_turn_seen = bool(new_turn_gate(sess))

            finished = detail in FINISHED_DETAILS or status in ("exit", "suspended")
            if new_turn_seen and finished:
                elapsed = self._clock() - start
                if output is not None or not require_structured_output:
                    return SessionResult(
                        session_id=sess.get("session_id") or session_id,
                        url=url,
                        status=status,
                        status_detail=detail,
                        structured_output=output,
                        acus_consumed=sess.get("acus_consumed"),
                        on_demand_usage=sess.get("on_demand_usage"),
                        elapsed_s=elapsed,
                        polls=polls,
                        last_devin_message=self._last_devin_message(session_id),
                        raw=sess,
                        api_version=self.api_version,
                    )
                excerpt = self._last_devin_message(session_id)
                raise DevinSessionFailed(
                    f"Devin session {session_id} ended (status={status}, "
                    f"status_detail={detail}) without calling "
                    f"provide_structured_output"
                    + (f"; last Devin message: {excerpt}" if excerpt else "")
                    + (f" ({url})" if url else ""),
                    session_id=session_id,
                    session_url=url,
                    detail=detail,
                )

            remaining = deadline - self._clock()
            if remaining <= 0:
                raise DevinTimeoutError(
                    f"Devin session {session_id} did not finish within "
                    f"{timeout_s:.0f}s (status={status}, status_detail={detail}) "
                    f"({url})",
                    session_id=session_id,
                    session_url=url,
                )
            self._sleep(min(poll_interval_s, remaining))

    def wait_for_completion(
        self,
        session_id: str,
        *,
        timeout_s: Optional[float] = None,
        poll_interval_s: Optional[float] = None,
        require_structured_output: bool = True,
        on_poll: Optional[Callable[[dict], None]] = None,
    ) -> SessionResult:
        """Poll until the session's turn is finished.

        Success requires ``structured_output`` to be non-null (unless
        ``require_structured_output`` is False) and the turn finished
        (status_detail finished/waiting_for_user, or status exit/suspended
        with a non-quota detail). ``on_poll`` is invoked with each GET body.
        """
        return self._wait(
            session_id,
            timeout_s=timeout_s if timeout_s is not None else self.settings.session_timeout_s,
            poll_interval_s=(
                poll_interval_s
                if poll_interval_s is not None
                else self.settings.poll_interval_s
            ),
            require_structured_output=require_structured_output,
            on_poll=on_poll,
        )

    def run_structured(
        self,
        prompt: str,
        schema: dict,
        *,
        title: Optional[str] = None,
        tags: Optional[list] = None,
        terminate: bool = False,
        timeout_s: Optional[float] = None,
        resumable: Optional[bool] = None,
        on_poll: Optional[Callable[[dict], None]] = None,
    ) -> SessionResult:
        """Create a session with a structured-output schema and wait for it."""
        sess = self.create_session(
            prompt,
            structured_output_schema=schema,
            structured_output_required=True,
            title=title,
            tags=tags,
            resumable=False if resumable is None else resumable,
        )
        session_id = sess.get("session_id") or sess.get("id")
        try:
            return self.wait_for_completion(
                session_id, timeout_s=timeout_s, on_poll=on_poll
            )
        finally:
            if terminate:
                try:
                    self.terminate_session(session_id)
                except DevinError as e:
                    logger.warning("failed to terminate session %s: %s", session_id, e)

    def continue_structured(
        self,
        session_id: str,
        message: str,
        *,
        timeout_s: Optional[float] = None,
        on_poll: Optional[Callable[[dict], None]] = None,
    ) -> SessionResult:
        """Send a follow-up message and wait for the NEW turn's final output.

        The stale pre-message ``structured_output`` is never returned: the new
        turn must first be observed — (a) status_detail 'working', (b) the
        structured_output changed, or (c) ``stale_grace_s`` elapsed since the
        send while the session reports a finished turn. Case (c) means Devin
        returned no new output; it is returned anyway because the caller
        re-validates.
        """
        baseline = self.get_session(session_id)
        prev_output = baseline.get("structured_output")
        self.send_message(session_id, message)
        sent_at = self._clock()
        grace = self.settings.stale_grace_s

        def gate(sess: dict) -> bool:
            if sess.get("status_detail") == "working":
                return True
            if sess.get("structured_output") != prev_output:
                return True
            finished = sess.get("status_detail") in FINISHED_DETAILS or sess.get(
                "status"
            ) in ("exit", "suspended")
            if finished and (self._clock() - sent_at) >= grace:
                return True
            return False

        return self._wait(
            session_id,
            timeout_s=timeout_s if timeout_s is not None else self.settings.session_timeout_s,
            poll_interval_s=self.settings.poll_interval_s,
            require_structured_output=True,
            new_turn_gate=gate,
            on_poll=on_poll,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DevinClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
