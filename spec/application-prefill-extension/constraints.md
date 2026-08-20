# Constraints

## Architecture

The content script scrapes the live DOM into the **exact schema shape `build_application_plan()`
already consumes**, so every answer decision stays in Python and nothing is ported to JS.

```
Chrome                                   127.0.0.1:8765 (python run.py --serve)
 content.js   scrape form → questions[]  ──POST /plan──▶  build_application_plan()   [unchanged]
              fill status=="ready"       ◀──plan JSON───  readiness_report()         [unchanged]
 drafts.js    per-field Insert           ──POST /drafts─▶ draft_free_text_answers()  [unchanged]
 background.js  holds token, fetches     ──GET /resume──▶ resolve_tailored_resume()  [unchanged]
 panel.js     job list, match, Applied   ──POST /confirm-applied──▶ db_update_status_verified()
 native_host/host.py  auto-starts the bridge on demand (increment 8) — a separate short-lived
                       process Chrome launches per request, not part of the diagram above
```

**Front door:** the docked side panel lists jobs at `Status = Resume Tailored` via
`GET /jobs/ready` (wraps `db_get_ready_to_apply()`, no new query logic), the user picks one, the
extension opens that job's apply URL itself (`chrome.tabs.create`), and the panel switches to the
plan view for that tab using the `page_id` it already knows. Multiple such job/panel pairs can run
at once, one per tab, each with independent session state.

**Routing is off the live page URL, never the Notion row's URL** — those routinely differ, and that
difference is the entire premise. `plan_for_job()` (`autoapply.py:669`) is therefore **not reused**;
the bridge composes `resolve_tailored_resume` + `build_application_plan` + `readiness_report`
itself — restated in `scripts/autoapply_server.py`'s own module docstring since it's the likeliest
silent mistake for anyone touching that file later.

## Settled decisions

| Decision | Choice | Why |
|---|---|---|
| Architecture | Local Python bridge; extension is a thin DOM client | All answer logic stays in `autoapply.py`, so nothing can drift |
| Fill behavior | Fill `ready` fields **on click**, badge the rest | Never on load — a wrong eligibility answer is unretractable |
| Scope | Every form **except LinkedIn/Indeed**, which stay read-only overlay | Preserves the existing permanent rule |
| Distribution | Unpacked / developer-mode only | A store listing for something that reads application forms is a different review problem |
| Fetch location | MV3 **service worker**, not the content script | `host_permissions` avoids CORS preflight for the auth header, and the token never enters a page that shares a DOM with the job site |
| Bridge startup | Manual `run.py --serve`, or native-messaging auto-launch (increment 8) — never a background daemon | The process must stay session-scoped and human-triggered either way |

## Security (non-negotiable)

Bind `("127.0.0.1", port)` **explicitly** — `HTTPServer(("", port))` binds all interfaces. Random
token in git-ignored `config/extension_token.txt`, regenerated per `--serve`, checked on every
request. CORS echoed **by page origin, not extension id** — an unpacked extension's id changes on
reload, so any id-keyed allowlist silently breaks. Runs only under an explicit `python run.py
--serve` invocation (typed by hand, or spawned by the native-messaging host on an explicit human
gesture — increment 8); never an unconditional daemon. `ThreadingHTTPServer` so a slow draft
doesn't block a concurrent `/resume`.

## The `Applied` invariant — reformulated, not broken

`WRITABLE_STATUSES` excludes `Applied` (`autoapply.py:65-80`), asserted by
`tests/test_autoapply_notion.py:50-63`. The rationale (`autoapply.py:67-71`) is that comparable
tools mark jobs applied that were never submitted — **inference from an unobservable event**. That
same comment already names the permitted case: "set by the human, by hand, after they click
Submit." It only assumed that hand was in Notion's UI.

> **New formulation:** `Applied` is never *inferred*. Planning and fill paths cannot write it. It
> may be written only by a dedicated confirmation route that is reachable solely from an explicit
> human gesture, carries no plan/fill data, and records in the tracker that the claim came from the
> human.

**What genuinely weakens:** today the guarantee is *physical* — no code path exists. After this,
one process holds both a credential and a path to the write. The threat model shifts from "the tool
lies" to "a bug or a future refactor reaches the write without a human keystroke." Compensating
controls (increment 5) ship in v1, not later.

## LinkedIn/Indeed enforcement is server-side, not client-side

`_READONLY_CHANNELS = {"linkedin", "indeed"}` keyed on `detect_apply_channel(live_page_url)` —
never the matched row's URL, since a LinkedIn *posting* whose Apply button bounces to a
Greenhouse/Ashby form is a page that *should* be filled. One post-pass rewrites every field to
`review_required` / `value: None` / `source: "channel read-only (linkedin/indeed) — never
filled"`, independent of profile completeness, so a bug or hand-edited content script can't bypass
it.

## Reused verbatim across every increment — this is the architectural claim, and it holds

`build_application_plan()` `autoapply.py:401` · `readiness_report()` `:434` · `_resolve_field()`
`:340` (incl. the `resume-missing` branch, which makes "no Notion match" a supported state with
**no new code**) · `detect_apply_channel()` `:111` · `parse_greenhouse_url()` `:127` ·
`fetch_greenhouse_questions()` `:165` (still preferred on Greenhouse, DOM as fallback) ·
`resolve_tailored_resume()` `:465` (already handles `file://` and CI `raw.githubusercontent.com`) ·
`draft_free_text_answers()` `:607` (already leaves `status`/`value` untouched) ·
`_resume_text_for()` `:647` · `db_get_jobs()` / `db_get_job_description()` /
`db_update_status_verified()` (`utils.py`) · `db_get_ready_to_apply()` (`utils.py`) — backs
`GET /jobs/ready`, no new Notion query logic.

**The only genuinely new logic is `_dom_to_schema()`** (increment 1) — kept a pure function so it
unit-diffs against `SAMPLE_QUESTIONS`. Plus one extraction: `accepts_docx(accept_attr)` pulled out
of `autoapply_browser.py` (increment 3a) so the bridge and Layer 2 share one rule.
