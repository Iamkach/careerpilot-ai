# Step 15a — `run.py --serve` bridge scaffold (Layer 3, increment 0)

**Status:** queued, not started (2026-07-31). Size **S**. Depends on: nothing beyond Step 10
Phases 1–2 (done). First of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (the epic —
read it first for architecture/why/security decisions this story assumes). Blocks
[step-15b](step-15b-plan-endpoint-identify-job.md).

## Goal

Stand up the local HTTP bridge process with nothing behind it yet but a health check — the
skeleton every later increment attaches routes to. No plan logic, no extension, no answer data
leaves this process in this story.

## Scope

**In:** `run.py --serve [--port]` flag (mirrors the `--setup-profile` pattern at `run.py:564`/
`:625`); new `scripts/autoapply_server.py` as a thin `BaseHTTPRequestHandler` subclass over
`ThreadingHTTPServer`; explicit `("127.0.0.1", port)` bind (never `("", port)`); random token
generated per `--serve` invocation and written to git-ignored `config/extension_token.txt`; every
request (once routes exist) will check this token, so wire the check now even though `/health` is
the only route; `GET /health` returning a trivial JSON body with no auth required (so a human/extension
can probe "is the bridge up" without a token round-trip).

**Out:** `/plan`, `/resume`, `/drafts`, `/confirm-applied` — every real route (later stories). The
extension itself (later stories) — this story is server-only, tested with `curl`/`requests` or a
Python test client, no browser.

## Implementation

- `scripts/autoapply_server.py`: module docstring states up front that routing is keyed off the
  *live page URL*, never the Notion row's URL, and that this bridge does **not** reuse
  `plan_for_job()` (`autoapply.py:669`) — flagged here so every later story that touches this file
  restates rather than silently drifts from it.
- Token: regenerate on every `--serve` start (not reused across runs), store as plain text in
  `config/extension_token.txt`, add that path to `.gitignore`.
- CORS: even with no real routes yet, decide and implement the policy now — echo back the
  request's `Origin` header, never an extension-id allowlist (an unpacked extension's id changes on
  reload).
- Bind literal `"127.0.0.1"` must appear as a literal string in a test-greppable location — this is
  what item 4 of the epic's automated verification list checks going forward.

## Files

**New:** `scripts/autoapply_server.py`, `tests/test_autoapply_server.py` (scaffold-only tests
below), `tests/test_run_serve_wiring.py`.
**Modified:** `run.py` (`--serve`/`--port`), `.gitignore` (`config/extension_token.txt`).

## Verification

1. `GET /health` returns 200 with no token required.
2. Any other path returns 404 (routes don't exist yet) — proves the handler doesn't silently
   accept unknown routes.
3. A request with a wrong/missing token to a would-be-authed route path is rejected — test this
   against a stub route registered only in the test, since no real authed route exists yet.
4. Bind literal is `"127.0.0.1"` (grep-level assertion) — never `""`.
5. Starting `--serve` twice on the same port fails cleanly (address already in use), doesn't hang.
6. Token file is regenerated (different content) across two separate `--serve` invocations.
