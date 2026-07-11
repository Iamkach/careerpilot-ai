# Quick fixes — independent, slot anywhere

**Priority:** P1 — both are cheap and unblock/de-risk downstream work; do not wait for the Step
0-7 spine.
**Depends on:** none
**Blocks:** nothing directly, but R10 blocks confidence in Stage 6 and should land before anyone
relies on negotiation briefs.
**Size:** XS each
**Source plan(s):** architecture-analysis.md §D.1 risk register (R10, R14);
`refinement-plans/communications/communications-subsystem.md` Phase 4 (names the encoding fix)

## Fix 1 — Stage 6 `UnboundLocalError` on every run

### Context

Stage 6 (negotiate) currently crashes on every invocation — it is a fully broken stage, not a
quality issue.

### Current behavior

`stage6_negotiate.py:125` uses `job` before it's assigned; the assignment happens at `:135`. Every
`python run.py --stage 6` or `workflow.py --task negotiate` call raises `UnboundLocalError`.

### Acceptance criteria

- [ ] Reorder so `job` is assigned before its first use (or fetch it earlier in the function).
- [ ] `python run.py --stage 6 --company "<test company>" --role "<test role>" --offer 100000`
      completes without raising.
- [ ] Output HTML negotiation brief is produced in `output/negotiation/` as expected.

### Files touched

`scripts/stage6_negotiate.py`

## Fix 2 — `save_draft()` non-UTF-8 write crashes on real names

### Context

Outreach drafts are saved with the platform default encoding. On Windows that's cp1252, which
cannot encode many real human names (accented characters, non-Latin scripts) — a crash that will
eventually hit in production once outreach volume includes non-ASCII names.

### Current behavior

`stage3_outreach.py:140` — `save_draft()` calls `.write_text(content)` with no `encoding=`
argument.

### Acceptance criteria

- [ ] Add `encoding="utf-8"` to the `write_text()` call.
- [ ] Manual test: draft an outreach email with a contact name containing a non-ASCII character
      (e.g. "José García") on Windows — confirm no `UnicodeEncodeError`.

### Files touched

`scripts/stage3_outreach.py`

## References

- Architecture analysis §A.8 defect B1 (Stage 6), §D.1 risk register R10 (🟠), R14 (🟡).
- `refinement-plans/README.md` — "Independent — slot anywhere."
