# Constraints

## Governing rule (borrowed from the communications-subsystem spec)

*The profile supplies facts; AI only drafts prose.* The model never invents an answer to a
work-authorization, sponsorship, salary, or yes/no eligibility question — those come from a
structured `APPLICATION_PROFILE` or the field is flagged `review_required`. A code-level validator
enforces this, not the prompt.

## Scenarios the router must handle (enumerated so every case has an owner)

1. Public read, form submit, no login, no captcha (Greenhouse/Lever/Ashby hosted forms) — best
   automation candidate.
2. Form + invisible/anti-bot captcha (reCAPTCHA v3, hCaptcha, Turnstile) — semi-auto hands off at
   the captcha.
3. Account required before applying (Workday, iCIMS, Taleo, SuccessFactors, Oracle) — each company
   is a separate tenant needing its own account + email verification; assisted only.
4. Multi-page dynamic form (Workday especially) — fragile to automate; assisted, agentic driver.
5. Authenticated-platform quick-apply (LinkedIn Easy Apply, Indeed Apply) — ToS-prohibited and
   behaviorally flagged; route to manual, pre-filled answer sheet, never drive the submit.
6. Knockout/screening questions (free-text, dropdowns, work-auth, sponsorship, salary, notice
   period, EEO) — deterministic answers from a profile where possible; LLM-drafted free-text
   behind human review; never guess work-auth or sponsorship.
7. File-upload variants (resume required, cover letter optional/required, portfolio, format
   constraints) — resume is Stage 2's `.docx`; may need on-the-fly PDF conversion.
8. External redirect (LinkedIn/Indeed listing whose Apply bounces to a company ATS) — measured
   2026-07-29 and found largely not implementable/not worth implementing; see problem.md.
9. Already applied / duplicate — hard idempotency gate on Notion status + `job_fingerprint`.
10. Login/session expiry mid-run, IP/rate blocks, bot-fingerprint challenges — typed errors + back
    off, never hammer.
11. Form changed / selector drift — prefer schema-driven or agentic (self-locating) filling over
    brittle CSS selectors; verify a known field resolved before trusting the fill.

## Source-class feasibility (routing key = job's `Source`/URL domain, same key `sources.py` uses)

| Source class | Read schema? | Submit path | Captcha likelihood | Auth needed | Automation |
|---|---|---|---|---|---|
| Greenhouse (hosted) | `?questions=true` exact schema | Browser fill | Low-med | None | Semi-auto, first target; hands-off only if 0 custom questions + no captcha |
| Lever (hosted) | Partial (no question schema) | Browser fill | Low-med | None | Semi-auto, second target |
| Ashby (hosted) | Partial | Browser fill | Med-high (Turnstile common) | None | Semi-auto, expect captcha handoff |
| Workday/iCIMS/Taleo/SF/Oracle | No | Multi-page, per-company account | Med | Account + email verify | Assisted/agentic only |
| LinkedIn Easy Apply | n/a | Authenticated quick-apply | Behavioral flagging | Logged-in session | Manual only, no automated submit |
| Indeed Apply | n/a | Authenticated quick-apply | Med | Session | Manual only |
| Company careers page (custom) | No | Arbitrary form | Unknown | Varies | Agentic driver, always human-confirm |

## Notion status & schema (already shipped, constrains any future write)

```
Reviewed → Resume Tailored → [Application Queued] → [Applying] → Applied
                                        │
                                        ├──→ [Needs Human: Captcha]
                                        ├──→ [Needs Human: Auth/Account]
                                        ├──→ [Needs Human: Question]   (unanswerable knockout/free-text)
                                        └──→ [Apply Failed]            (typed error, safe to retry)
```

New properties (optionally-present, per `_notion_write_job()`'s existing convention): `Apply
Channel`, `Apply Attempts`, `Application Log`, `Needs Human Reason`. Idempotency via status +
`job_fingerprint()`; "prepare, don't auto-send" gate via a `--submit` flag, same shape as Stage 4's
`--send`.

## Hurdles and mitigations any future phase must respect

- **Captcha** — never build solving into the default path; treat as the designed human-handoff.
- **Authentication** — Workday-style per-company accounts need a credential vault + email
  verification reader; treat account provisioning as its own phase, not folded into fill logic.
- **Knockout questions** — work-auth/sponsorship/salary from `APPLICATION_PROFILE` only; anything
  unmapped → `Needs Human: Question`, never a guess.
- **Selector drift & silent form changes** — prefer schema-driven or agentic filling; assert an
  expected field resolved before submit; on mismatch → fail safe to `Apply Failed`, never submit a
  half-filled form.
- **Duplicate/double submit** — status gate + fingerprint; write `Applying` *before* the attempt so
  a crash can't silently double-apply.
- **Rate/IP/fingerprint blocks** — cap applications/day; human-paced timing; typed errors +
  backoff; never blind-retry a bot-challenge.
- **Wrong resume/wrong company** — pre-submit verification: confirm the tailored `.docx` actually
  matches this `page_id` and the form's company matches the job's company before any submit.
