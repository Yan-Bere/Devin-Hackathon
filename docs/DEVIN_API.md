# Devin API: access, verification and quota

The engine uses our existing Devin subscription as its only AI provider. Devin is called
from the backend to interpret a requirements document into structured engineering data
(`coldplate/parser.py`). No other model API is used.

## Credentials (backend only)

Credentials live in a git-ignored `.env` at the repository root (template: `.env.example`).
They are read only by `coldplate/devin_client.py`, never logged, and never sent to a browser.

| Variable | Meaning |
|---|---|
| `DEVIN_API_KEY` | `cog_…` Personal Access Token (API v3, preferred) **or** legacy `apk_user_…` personal key (API v1, deprecated) |
| `DEVIN_ORG_ID` | `org-…` organization id; required for v3, ignored for v1 |
| `DEVIN_MODE` | optional v3 agent mode (`lite`, `normal`, …); empty = organization default |
| `DEVIN_MAX_ACU_LIMIT` | optional hard ACU cap per parser session |

The client picks the API version from the key prefix:

- **v3 (primary):** `cog_` Personal Access Token from app.devin.ai → Settings → **Devin API** → **PATs**.
  The organization id is shown at the top of the same page. Sessions are attributed to your user.
- **v1 (fallback):** legacy `apk_user_` key from Settings → API Keys. Cognition has deprecated
  these keys and says they "will be removed soon". The v1 API has no `acus_consumed` field,
  so per-session consumption cannot be reported.

## Endpoints used

| Purpose | v3 | v1 (legacy) |
|---|---|---|
| Verify credentials (no quota) | `GET /v3/self` | `GET /v1/sessions?limit=1` |
| Create session with a JSON-Schema structured output | `POST /v3/organizations/{org}/sessions` | `POST /v1/sessions` |
| Poll status / read `structured_output` | `GET /v3/organizations/{org}/sessions/{id}` | `GET /v1/sessions/{id}` |
| Targeted repair (at most one per parse) | `POST …/sessions/{id}/messages` | `POST /v1/sessions/{id}/message` |
| Stop the session after the result | `DELETE …/sessions/{id}` | `DELETE /v1/sessions/{id}` |

Both versions accept `structured_output_schema` (JSON Schema Draft 7, ≤ 64 KB, self-contained).
Ours is generated from `coldplate/extraction_schema.py` and is about 14 KB. Requests use
bounded retries: GET/DELETE retry on transport errors, 429 and 5xx; POST retries only on
connection failures and 429, so a retry can never create a duplicate session. All requests
have timeouts, and polling has a session deadline.

## Smoke test (2026-10-24)

```
.venv\Scripts\python.exe scripts\devin_smoke_test.py --dry-run   # credential check only, no quota
.venv\Scripts\python.exe scripts\devin_smoke_test.py             # one minimal session
```

| Item | Result |
|---|---|
| `GET /v3/self` with the account's current key | 403. The key is a legacy `apk_user_` key, which v3 rejects. |
| `GET /v1/sessions?limit=1` | 200 |
| Session created | `devin-f4d815ab17a9461aba5da205c3e96735` (origin: API) |
| Structured output returned | `{"ok": true, "echo": "coldplate-smoke-v1"}` (exact match) |
| Status at completion | `running / waiting_for_user` (turn finished), then terminated by the script |
| Wall time | 8.6 s (2 polls) |
| ACUs consumed | not reported by API v1 |

**Conclusion:** this account can run API-created Devin sessions. The v3 code path is
implemented and unit-tested with mocked responses. It has not been exercised live, because
no `cog_` PAT has been issued yet.

First real parse of the canonical ITherm document (prompt v1): one session, about 45 s,
no repair needed, zero rubric errors. See `prompts/requirements_parser/eval/`.

## How API sessions consume the subscription

Sources: docs.devin.ai › Admin › Billing › Usage and Self-serve plans.

- API sessions are ordinary Devin sessions. They draw on the same usage allowance as sessions
  started in the web app, the Devin CLI and Devin Desktop. Self-serve plans consume the plan's
  included quota first, then prepaid on-demand credits if any exist.
- **Max** has a weekly allowance with no daily cap, shared across all of those surfaces.
  Cognition documents **no separate or unlimited API allowance**, so every parse here spends
  the same weekly quota as interactive use. A promotional Max plan should not be assumed to
  change this.
- Usage depends on the work Devin does plus a small amount of VM time. Sessions created via
  the API go to sleep after 5 minutes of inactivity (not the usual 30), and a sleeping
  session consumes nothing.
- Remaining quota is shown at app.devin.ai → Settings → Usage & limits. With a v3 key,
  `acus_consumed` is also recorded per session in our results.

How this engine keeps consumption low:

1. Parse results are cached by a hash of prompt version, schema version, prompt text and
   document text (`runs/cache/parse/`). An identical document costs zero further sessions.
2. Each parse is one short session with a strict schema, plus at most one targeted repair
   message, and the session is terminated as soon as a result is accepted.
3. Prompts are short and versioned (`prompts/requirements_parser/v*/`). No conversational
   context or repositories are attached.
4. Optional `DEVIN_MAX_ACU_LIMIT` caps each session; `DEVIN_MODE=lite` (v3) selects the
   lower-cost mode.
5. Tests replay recorded Devin outputs (`tests/fixtures/devin_recordings/`), so the regression
   suite consumes no quota. Only tests marked `live` call Devin.
