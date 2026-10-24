"""Unit tests for coldplate.devin_client — no network (httpx.MockTransport)."""

from __future__ import annotations

import os

import httpx
import pytest

from coldplate.devin_client import (
    DevinAuthError,
    DevinClient,
    DevinConfigError,
    DevinError,
    DevinNotFoundError,
    DevinPermissionError,
    DevinQuotaError,
    DevinSessionFailed,
    DevinSettings,
    DevinTimeoutError,
)

ORG = "org-1234"
SETTINGS = DevinSettings(
    api_key="cog_testkey",
    org_id=ORG,
    poll_interval_s=8.0,
    session_timeout_s=30.0,
)

ENV_NAMES = [
    "DEVIN_API_KEY",
    "DEVIN_ORG_ID",
    "DEVIN_API_BASE_URL",
    "DEVIN_MODE",
    "DEVIN_MAX_ACU_LIMIT",
    "DEVIN_POLL_INTERVAL_S",
    "DEVIN_SESSION_TIMEOUT_S",
]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeSleep:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


class Router:
    """Exact-path mock router; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._routes: dict[tuple[str, str], object] = {}

    def add(self, method: str, path: str, fn) -> None:
        self._routes[(method, path)] = fn

    def add_queue(self, method: str, path: str, responses: list) -> None:
        """Pop the next response on each call; repeats the last one."""
        state = {"responses": list(responses)}

        def fn(request: httpx.Request) -> httpx.Response:
            if len(state["responses"]) > 1:
                item = state["responses"].pop(0)
            else:
                item = state["responses"][0]
            if isinstance(item, Exception):
                raise item
            return item

        self.add(method, path, fn)

    @staticmethod
    def _norm(path: str) -> str:
        # base_url ends in /v3 or /v1, so request paths carry that prefix
        if path.startswith("/v3") or path.startswith("/v1"):
            return path[3:]
        return path

    def count(self, method: str, path: str) -> int:
        return sum(
            1
            for r in self.requests
            if r.method == method and self._norm(r.url.path) == path
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = self._norm(request.url.path)
        fn = self._routes.get((request.method, path))
        if fn is None:
            return httpx.Response(
                404,
                json={
                    "title": "Not Found",
                    "status": 404,
                    "detail": f"no mock for {request.method} {path}",
                },
            )
        return fn(request)


def problem(status: int, title: str = "Error", detail: str = "boom") -> httpx.Response:
    return httpx.Response(
        status, json={"title": title, "status": status, "detail": detail}
    )


def session(
    session_id: str = "sess-1",
    status: str = "running",
    detail: str = "working",
    output=None,
    **kw,
) -> dict:
    body = {
        "session_id": session_id,
        "url": f"https://app.devin.ai/sessions/{session_id}",
        "status": status,
        "status_detail": detail,
        "structured_output": output,
        "acus_consumed": 1.5,
        "on_demand_usage": None,
        "created_at": 1700000000,
        "updated_at": 1700000100,
        "tags": ["t"],
        "org_id": ORG,
    }
    body.update(kw)
    return body


def messages(*msgs: str, has_next: bool = False, cursor=None) -> httpx.Response:
    items = [
        {"event_id": f"e{i}", "source": "devin", "message": m, "created_at": 1}
        for i, m in enumerate(msgs)
    ]
    return httpx.Response(
        200,
        json={"items": items, "end_cursor": cursor, "has_next_page": has_next},
    )


def make_client(router: Router, settings: DevinSettings = SETTINGS):
    clock = FakeClock()
    sleep = FakeSleep(clock)
    transport = httpx.MockTransport(router)
    client = DevinClient(settings, transport=transport, sleep=sleep, clock=clock)
    return client, clock, sleep


SESSIONS = f"/organizations/{ORG}/sessions"
SESS = f"{SESSIONS}/sess-1"
MSGS = f"{SESS}/messages"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_structured_success_path():
    router = Router()
    created = session(status="new", detail=None, output=None)

    def create(request):
        return httpx.Response(200, json=created)

    router.add("POST", SESSIONS, create)
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(200, json=session(status="running", detail="working")),
            httpx.Response(
                200,
                json=session(
                    status="exit", detail="finished", output={"ok": True}
                ),
            ),
        ],
    )
    router.add("GET", MSGS, lambda r: messages("all done"))

    client, clock, sleep = make_client(router)
    result = client.run_structured(
        "do the thing",
        {"type": "object"},
        title="t",
        tags=["a"],
    )

    assert result.structured_output == {"ok": True}
    assert result.session_id == "sess-1"
    assert result.url == "https://app.devin.ai/sessions/sess-1"
    assert result.status == "exit"
    assert result.status_detail == "finished"
    assert result.polls == 2
    assert result.last_devin_message == "all done"
    assert result.raw["acus_consumed"] == 1.5

    # create body sent schema + resumable=false
    import json as _json

    body = _json.loads(router.requests[0].content)
    assert body["prompt"] == "do the thing"
    assert body["resumable"] is False
    assert body["structured_output_schema"] == {"type": "object"}
    assert body["structured_output_required"] is True
    assert body["title"] == "t"
    assert body["tags"] == ["a"]


def test_create_session_omits_null_fields_and_applies_settings_defaults():
    router = Router()
    router.add("POST", SESSIONS, lambda r: httpx.Response(200, json=session()))
    settings = DevinSettings(
        api_key="cog_testkey", org_id=ORG, devin_mode="lite", max_acu_limit=7
    )
    client, _, _ = make_client(router, settings)
    client.create_session("hello")

    import json as _json

    body = _json.loads(router.requests[0].content)
    assert body == {
        "prompt": "hello",
        "resumable": False,
        "devin_mode": "lite",
        "max_acu_limit": 7,
    }
    for absent in (
        "title",
        "tags",
        "structured_output_schema",
        "structured_output_required",
    ):
        assert absent not in body


def test_get_retries_on_429_retry_after_and_503():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(
                429,
                json={"title": "Too Many Requests", "detail": "slow down"},
                headers={"Retry-After": "2"},
            ),
            problem(503, "Service Unavailable", "try later"),
            httpx.Response(200, json=session(status="exit", detail="finished")),
        ],
    )
    client, _, sleep = make_client(router)
    sess = client.get_session("sess-1")

    assert sess["status"] == "exit"
    assert router.count("GET", SESS) == 3
    # 429 honored Retry-After=2; 503 used exponential backoff attempt 1 -> 2s
    assert sleep.calls == [2.0, 2.0]


def test_post_not_retried_on_500():
    router = Router()
    router.add_queue(
        "POST", SESSIONS, [problem(500, "Internal Server Error", "kaboom")]
    )
    client, _, _ = make_client(router)
    with pytest.raises(DevinError) as ei:
        client.create_session("x")
    assert "500" in str(ei.value)
    assert router.count("POST", SESSIONS) == 1


def test_post_retried_on_connect_error_but_not_read_timeout():
    router = Router()
    router.add_queue(
        "POST",
        SESSIONS,
        [
            httpx.ConnectError("conn refused"),
            httpx.Response(200, json=session()),
        ],
    )
    client, _, _ = make_client(router)
    data = client.create_session("x")
    assert data["session_id"] == "sess-1"
    assert router.count("POST", SESSIONS) == 2

    router2 = Router()
    router2.add_queue(
        "POST", SESSIONS, [httpx.ReadTimeout("peer went quiet")]
    )
    client2, _, _ = make_client(router2)
    with pytest.raises(DevinError):
        client2.create_session("x")
    assert router2.count("POST", SESSIONS) == 1


def test_401_and_403_mapping():
    for status, exc, needle in (
        (401, DevinAuthError, "cog_"),
        (403, DevinPermissionError, "UseDevinSessions"),
    ):
        router = Router()
        router.add("GET", "/self", lambda r, s=status: problem(s))
        client, _, _ = make_client(router)
        with pytest.raises(exc) as ei:
            client.whoami()
        assert ei.value.status_code == status
        assert needle in str(ei.value)
        assert "cog_testkey" not in str(ei.value)


def test_quota_suspension_raises_quota_error():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(200, json=session(status="running", detail="working")),
            httpx.Response(
                200,
                json=session(status="suspended", detail="out_of_quota"),
            ),
        ],
    )
    client, _, _ = make_client(router)
    with pytest.raises(DevinQuotaError) as ei:
        client.wait_for_completion("sess-1")
    assert "out_of_quota" in str(ei.value)
    assert ei.value.session_id == "sess-1"


def test_error_status_raises_session_failed():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [httpx.Response(200, json=session(status="error", detail="error"))],
    )
    router.add("GET", MSGS, lambda r: messages("something broke"))
    client, _, _ = make_client(router)
    with pytest.raises(DevinSessionFailed) as ei:
        client.wait_for_completion("sess-1")
    assert "something broke" in str(ei.value)


def test_waiting_for_approval_fails_immediately():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(
                200,
                json=session(status="running", detail="waiting_for_approval"),
            )
        ],
    )
    client, _, sleep = make_client(router)
    with pytest.raises(DevinSessionFailed) as ei:
        client.wait_for_completion("sess-1")
    assert "approval" in str(ei.value)
    assert router.count("GET", SESS) == 1  # no extra polls
    assert sleep.calls == []


def test_ended_without_output_includes_last_devin_message():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(
                200, json=session(status="exit", detail="finished", output=None)
            )
        ],
    )
    router.add(
        "GET",
        MSGS,
        lambda r: messages("I looked around", "I could not produce the output"),
    )
    client, _, _ = make_client(router)
    with pytest.raises(DevinSessionFailed) as ei:
        client.wait_for_completion("sess-1")
    assert "I could not produce the output" in str(ei.value)
    assert "I looked around" not in str(ei.value)  # only the last message


def test_wait_timeout_raises_devin_timeout():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [httpx.Response(200, json=session(status="running", detail="working"))],
    )
    client, _, _ = make_client(router)
    with pytest.raises(DevinTimeoutError) as ei:
        client.wait_for_completion("sess-1", timeout_s=30)
    assert "app.devin.ai/sessions/sess-1" in str(ei.value)
    assert ei.value.session_url == "https://app.devin.ai/sessions/sess-1"


def test_continue_structured_ignores_stale_output():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            # baseline snapshot before sending the message
            httpx.Response(
                200,
                json=session(
                    status="exit",
                    detail="finished",
                    output={"v": 1},
                    updated_at=100,
                ),
            ),
            # stale read: turn not yet started
            httpx.Response(
                200,
                json=session(
                    status="exit",
                    detail="finished",
                    output={"v": 1},
                    updated_at=100,
                ),
            ),
            # new turn observed
            httpx.Response(
                200,
                json=session(
                    status="running",
                    detail="working",
                    output={"v": 1},
                    updated_at=101,
                ),
            ),
            # new turn finished with new output
            httpx.Response(
                200,
                json=session(
                    status="exit",
                    detail="finished",
                    output={"v": 2},
                    updated_at=102,
                ),
            ),
        ],
    )
    router.add(
        "POST", MSGS, lambda r: httpx.Response(200, json={"ok": True})
    )
    router.add("GET", MSGS, lambda r: messages("done again"))

    client, _, _ = make_client(router)
    result = client.continue_structured("sess-1", "please update")

    assert result.structured_output == {"v": 2}
    assert router.count("POST", MSGS) == 1


def test_terminate_session_swallows_404():
    router = Router()
    router.add(
        "DELETE", SESS, lambda r: problem(404, "Not Found", "no such session")
    )
    client, _, _ = make_client(router)
    client.terminate_session("sess-1")  # must not raise

    # but a real error still surfaces
    router2 = Router()
    router2.add("DELETE", SESS, lambda r: problem(500, "Internal", "boom"))
    client2, _, _ = make_client(router2)
    with pytest.raises(DevinError):
        client2.terminate_session("sess-1")


def test_list_messages_paginates():
    router = Router()
    seen_after = []

    def msgs(request):
        seen_after.append(request.url.params.get("after"))
        if request.url.params.get("after") == "c1":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "event_id": "e2",
                            "source": "devin",
                            "message": "second",
                            "created_at": 2,
                        }
                    ],
                    "end_cursor": None,
                    "has_next_page": False,
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "event_id": "e1",
                        "source": "devin",
                        "message": "first",
                        "created_at": 1,
                    }
                ],
                "end_cursor": "c1",
                "has_next_page": True,
            },
        )

    router.add("GET", MSGS, msgs)
    client, _, _ = make_client(router)
    items = client.list_messages("sess-1")
    assert [i["message"] for i in items] == ["first", "second"]
    assert seen_after == [None, "c1"]


def test_settings_repr_redacts_key():
    r = repr(SETTINGS)
    assert "cog_testkey" not in r
    assert "redacted" in r
    assert ORG in r


def test_from_env_missing_key_and_org(monkeypatch, tmp_path):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    empty = tmp_path / "nothing.env"  # does not exist
    with pytest.raises(DevinConfigError) as ei:
        DevinSettings.from_env(str(empty))
    assert "DEVIN_API_KEY" in str(ei.value)

    monkeypatch.setenv("DEVIN_API_KEY", "cog_ok")
    with pytest.raises(DevinConfigError) as ei2:
        DevinSettings.from_env(str(empty))
    assert "DEVIN_ORG_ID" in str(ei2.value)


def test_from_env_rejects_unknown_key_prefix(monkeypatch, tmp_path):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEVIN_API_KEY", "xyz_nope")
    monkeypatch.setenv("DEVIN_ORG_ID", "org-1")
    with pytest.raises(DevinConfigError) as ei:
        DevinSettings.from_env(str(tmp_path / "none.env"))
    assert "cog_" in str(ei.value)


def test_from_env_v1_legacy_key_no_org_required(monkeypatch, tmp_path, caplog):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEVIN_API_KEY", "apk_user_abc")
    s = DevinSettings.from_env(str(tmp_path / "none.env"))
    assert s.api_version == "v1"
    assert s.resolved_base_url == "https://api.devin.ai/v1"
    assert s.org_id is None
    assert "deprecated Devin API v1" in caplog.text


def test_v3_settings_require_org_id():
    s = DevinSettings(api_key="cog_x")
    assert s.api_version == "v3"
    with pytest.raises(DevinConfigError):
        DevinClient(s, transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def test_from_env_loads_dotenv_file(monkeypatch, tmp_path):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "devin.env"
    env_file.write_text(
        "DEVIN_API_KEY=cog_fromfile\n"
        "DEVIN_ORG_ID=org-99\n"
        "DEVIN_MODE=lite\n"
        "DEVIN_MAX_ACU_LIMIT=7\n"
        "DEVIN_POLL_INTERVAL_S=3\n"
        "DEVIN_SESSION_TIMEOUT_S=120\n"
    )
    try:
        s = DevinSettings.from_env(str(env_file))
    finally:
        for name in ENV_NAMES:
            os.environ.pop(name, None)
    assert s.api_key == "cog_fromfile"
    assert s.org_id == "org-99"
    assert s.devin_mode == "lite"
    assert s.max_acu_limit == 7
    assert s.poll_interval_s == 3.0
    assert s.session_timeout_s == 120.0
    assert s.base_url == "https://api.devin.ai/v3"


# ---------------------------------------------------------------------------
# continue_structured gate hardening + on_poll
# ---------------------------------------------------------------------------


def test_continue_structured_updated_at_bump_does_not_return_stale():
    """Message POST bumps updated_at before the new turn; stale finished must not win."""
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(
                200,
                json=session(status="exit", detail="finished", output={"v": 1}, updated_at=100),
            ),
            # first poll: updated_at advanced, but still the OLD finished turn + stale output
            httpx.Response(
                200,
                json=session(status="exit", detail="finished", output={"v": 1}, updated_at=101),
            ),
            httpx.Response(
                200,
                json=session(status="exit", detail="finished", output={"v": 2}, updated_at=105),
            ),
        ],
    )
    router.add("POST", MSGS, lambda r: httpx.Response(200, json={"ok": True}))
    router.add("GET", MSGS, lambda r: messages("ok"))
    client, _, _ = make_client(router)
    result = client.continue_structured("sess-1", "update please", timeout_s=60)
    assert result.structured_output == {"v": 2}


def test_continue_structured_grace_period_returns_stale_output():
    """If no new turn shows up within stale_grace_s, return the (stale) output anyway."""
    router = Router()
    stale = session(status="exit", detail="finished", output={"v": 1}, updated_at=100)
    router.add_queue(
        "GET",
        SESS,
        [httpx.Response(200, json=stale)],
    )
    router.add("POST", MSGS, lambda r: httpx.Response(200, json={"ok": True}))
    router.add("GET", MSGS, lambda r: messages("nothing new"))
    settings = DevinSettings(
        api_key="cog_testkey", org_id=ORG, poll_interval_s=8.0,
        session_timeout_s=60.0, stale_grace_s=10.0,
    )
    client, _, _ = make_client(router, settings)
    result = client.continue_structured("sess-1", "update please")
    assert result.structured_output == {"v": 1}
    assert result.polls >= 2  # it kept polling until the grace elapsed


def test_wait_for_completion_on_poll_called():
    router = Router()
    router.add_queue(
        "GET",
        SESS,
        [
            httpx.Response(200, json=session(status="running", detail="working")),
            httpx.Response(200, json=session(status="exit", detail="finished", output={"ok": 1})),
        ],
    )
    router.add("GET", MSGS, lambda r: messages("done"))
    client, _, _ = make_client(router)
    seen = []
    result = client.wait_for_completion("sess-1", on_poll=seen.append)
    assert result.structured_output == {"ok": 1}
    assert len(seen) == 2
    assert seen[0]["status"] == "running"


# ---------------------------------------------------------------------------
# v1 legacy API adapter
# ---------------------------------------------------------------------------

V1_SETTINGS = DevinSettings(api_key="apk_user_legacy", org_id=None)
V1_SESS = "/sessions/sess-v1"


def v1_session(status_enum="working", output=None, status="Running", msgs=None):
    return {
        "session_id": "sess-v1",
        "status": status,
        "status_enum": status_enum,
        "structured_output": output,
        "messages": msgs or [],
        "created_at": "2026-10-24T00:00:00Z",
        "updated_at": "2026-10-24T00:01:00Z",
        "title": "t",
        "tags": [],
    }


def make_v1_client(router: Router):
    clock = FakeClock()
    sleep = FakeSleep(clock)
    transport = httpx.MockTransport(router)
    return DevinClient(V1_SETTINGS, transport=transport, sleep=sleep, clock=clock)


def test_v1_run_structured_blocked_with_output_succeeds():
    router = Router()
    router.add(
        "POST",
        "/sessions",
        lambda r: httpx.Response(
            200, json={"session_id": "sess-v1", "url": "https://devin.ai/s/sess-v1", "is_new_session": True}
        ),
    )
    router.add_queue(
        "GET",
        V1_SESS,
        [
            httpx.Response(200, json=v1_session("working")),
            httpx.Response(200, json=v1_session("blocked", output={"ok": True})),
        ],
    )
    client = make_v1_client(router)
    result = client.run_structured("do it", {"type": "object"})
    assert result.structured_output == {"ok": True}
    assert result.api_version == "v1"
    assert result.acus_consumed is None
    assert result.url == "https://devin.ai/s/sess-v1"


def test_v1_expired_without_output_fails_with_last_message():
    router = Router()
    router.add_queue(
        "GET",
        V1_SESS,
        [
            httpx.Response(
                200,
                json=v1_session(
                    "expired",
                    msgs=[
                        {"type": "devin_message", "event_id": "e1", "message": "I ran out of road", "timestamp": "t1"}
                    ],
                ),
            )
        ],
    )
    client = make_v1_client(router)
    with pytest.raises(DevinSessionFailed) as ei:
        client.wait_for_completion("sess-v1")
    assert "I ran out of road" in str(ei.value)


def test_v1_message_to_suspended_raises():
    router = Router()
    router.add_queue(
        "GET",
        V1_SESS,
        [httpx.Response(200, json=v1_session("suspend_requested"))],
    )
    router.add(
        "POST",
        f"{V1_SESS}/message",
        lambda r: httpx.Response(200, json={"detail": "session is suspended"}),
    )
    client = make_v1_client(router)
    with pytest.raises(DevinSessionFailed) as ei:
        client.continue_structured("sess-v1", "hello?")
    assert "session is suspended" in str(ei.value)


def test_v1_terminate_tolerates_exited_session():
    router = Router()
    router.add(
        "DELETE",
        V1_SESS,
        lambda r: httpx.Response(409, json={"detail": "session already exited"}),
    )
    client = make_v1_client(router)
    client.terminate_session("sess-v1")  # must not raise


def test_v1_create_omits_v3_only_fields():
    import json as _json

    router = Router()
    router.add(
        "POST",
        "/sessions",
        lambda r: httpx.Response(200, json={"session_id": "s1", "url": "u"}),
    )
    settings = DevinSettings(api_key="apk_user_x", devin_mode="lite", max_acu_limit=3)
    client = DevinClient(settings, transport=httpx.MockTransport(router))
    client.create_session("hi", structured_output_schema={"type": "object"})
    body = _json.loads(router.requests[0].content)
    assert body == {
        "prompt": "hi",
        "max_acu_limit": 3,
        "structured_output_schema": {"type": "object"},
    }
    assert "devin_mode" not in body
    assert "resumable" not in body
    assert "structured_output_required" not in body


def test_v1_whoami():
    router = Router()
    router.add("GET", "/sessions", lambda r: httpx.Response(200, json={"sessions": []}))
    client = make_v1_client(router)
    me = client.whoami()
    assert me == {"principal_type": "legacy_api_key", "api_version": "v1"}
