# Acceptance criteria

## Already met (Phases 1-2, shipped — listed for completeness)
- [x] Layer 1 (`scripts/autoapply.py`) routes by channel, reads the Greenhouse field schema,
      resolves answers, gates on unresolved required fields, writes an answer sheet + Notion
      status, never submits.
- [x] Layer 2 (`scripts/autoapply_browser.py`) fills a Greenhouse/Lever form in a real browser,
      uploads the resume, stops before submit — no submit code path exists anywhere in the module.
- [x] `WRITABLE_STATUSES` excludes `Applied`; asserted by `tests/test_autoapply_notion.py`.
- [x] `--dry-run --limit N` samples real jobs with zero Notion writes.

## Open — Phase 3 (deliberate submit), not started
- [ ] A `--submit --yes-i-mean-it` flag exists and is the only way any code path reaches a real
      submit click.
- [ ] Submit is only ever attempted on Greenhouse forms with zero unresolved required fields and
      no detected captcha.
- [ ] A hard daily cap applies to submitted (not just filled) applications.
- [ ] Ashby's captcha is handled as a clean handoff, never a retry loop.

## Open — Phase 4 (agentic long tail via Playwright), not started
- [ ] An agentic driver can navigate at least one real Workday multi-page form far enough to
      surface where it needs human input, without silently mis-filling a field.
- [ ] Account provisioning (Workday tenant account + email verification) is treated as its own
      gated step, never assumed to already exist.
- [ ] Every agentic fill still pauses for human confirmation before submit — no exception.

## Residual gaps carried over from Phases 1-2 (still open, not new work)
- [ ] The Layer-2 fill path (`--stage 7 --fill`, real browser open) has been run against at least
      one live, currently-open form (the two READY Anthropic jobs identified 2026-07-30 are
      current candidates, subject to still being open).
- [ ] A replacement live-fill validation target exists for the SmithRx posting that 404s.
- [ ] `python scripts/setup_notion_schema.py --apply` has been run once against the live tracker
      before any Phase 3/4 work attempts a status transition that depends on the six new `Status`
      options / four new properties.
