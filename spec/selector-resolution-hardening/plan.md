# Plan — Selector resolution hardening (Stage 7 Layer 2)

File-by-file implementation breakdown — the "how."

> **Scope note.** This plan covers `scripts/autoapply_browser.py`'s field-resolution path only.
> It does **not** change Layer 1 planning, does not add a submit path, and does not change the
> Playwright dependency. The driver was evaluated and deliberately retained — see
> `docs/research/agent-browser-landscape.md` for that decision and its reversal triggers.

## Summary

`_find()` (line 89) resolves a planned field by walking `_candidate_selectors()` (line 67):
`[name="…"]` / `#id`, then three XPath label fallbacks. When every candidate misses, the field is
silently added to `missed` and the run either under-fills or trips the `MIN_RESOLVE_RATIO = 0.6`
drift guard (line 212). The maintenance cost being absorbed today is that drift verdict firing on
forms whose markup is fine — the resolver simply cannot see the field.

Two changes, in order. Phase 1 widens what the resolver can see. Phase 2 makes failures
diagnosable so the next fix is targeted rather than guessed. Phase 3 is scoped but deliberately
not built yet.

## Files

- **New:** `tests/test_autoapply_selector_tiers.py` — unit tests, no browser, runs in the default
  suite. Covers `_candidate_selectors()` purity and tier ordering.
- **Modify:** `scripts/autoapply_browser.py` — `_candidate_selectors()`, new `_semantic_locators()`,
  `_find()`, the fill loop in `fill_application()`, `_result()`.
- **Modify:** `tests/test_autoapply_browser.py` — new `browser`-marked cases for the a11y-only
  fields and the telemetry payload.
- **Modify:** `tests/fixtures/greenhouse_form.html` — add three fields that are *unresolvable*
  under today's selectors (see Phase 1).
- **Modify:** `CLAUDE.md` — the "Stage 7 Auto-Apply" section documents the resolution order as an
  architecture decision; per the repo's own rule it updates in the same change.
- **Modify:** `spec/INDEX.md` — add this feature's row.
- **No change:** `scripts/autoapply.py`. Layer 1 planning, `_resolve_field()`, `_LABEL_RULES` and
  the `_label_matches_pattern()` subsequence matcher are untouched — this plan is about finding a
  field in the DOM, not about deciding its answer.
- **No change:** `extension/content.js`. Layer 3 has its own independent DOM scraper by design.
  It will *not* inherit these improvements; note the divergence in `CLAUDE.md` rather than
  silently letting the two resolvers drift further apart.

---

## Phase 1 — Accessibility-tree locators

### Why today's selectors miss

The XPath fallbacks require the input to be a **descendant** of the `<label>`, or the immediately
following input. Three common real-world markups defeat all of them:

| Markup | Why it misses today |
|---|---|
| `<label for="x">Question</label>` with the input elsewhere in the DOM | Not a descendant; `following::input[1]` may hit a different field |
| `<input aria-label="Question">` with no `<label>` element at all | No label node to match |
| `<input aria-labelledby="q7-title">` | Label text lives in a referenced node |

There is also a latent collision: the label is truncated to `esc[:40]` (line 83) and matched with
`contains()`, so two long questions sharing a 40-character prefix resolve to the same element.
Playwright's `get_by_label(..., exact=True)` closes that specific hole.

Verified: `get_by_label` and `get_by_role` appear **nowhere** in `scripts/`, and
`tests/fixtures/greenhouse_form.html` contains **zero** `aria-label` / `aria-labelledby`
attributes — so neither the capability nor its test coverage exists today.

### Implementation

Keep `_candidate_selectors()` a **pure string function** — it needs no `page` and is unit-testable
without a browser, which is what keeps these tests out of the slow `browser`-marked suite. Add
semantic resolution as a separate, page-aware generator:

```python
def _semantic_locators(page, field):
    """(tier, locator) pairs from the accessibility tree, most precise first.

    Separate from _candidate_selectors() on purpose: these need a live `page`, while the
    string selectors stay pure and unit-testable. Exact-match first — get_by_label defaults
    to substring matching, which reintroduces the same 40-char prefix collision the XPath
    fallbacks already have.
    """
    label = (field.get("label") or "").strip()
    if not label:
        return
    yield "aria_exact", page.get_by_label(label, exact=True)
    yield "aria_loose", page.get_by_label(label)
    yield "role_name",  page.get_by_role("textbox", name=label)
```

Resolution order in `_find()`:

1. `name` — `[name="…"]`, `#id`. Most precise on Greenhouse, where the public schema reports the
   real input name. **Stays first.**
2. `aria_exact`, `aria_loose`, `role_name` — the new tier. Robust across class renames and the
   three markups above.
3. `xpath_*` — the existing fallbacks, unchanged, now genuinely last-resort.

### Timeout budget — do not skip this

`_find()` currently waits `timeout=1200` per candidate against up to 5 candidates: 6s worst case
per unresolved field. Adding three tiers makes that 8 candidates → **9.6s per unresolved field**,
and a drifted form has many. On a 20-field form that is over three minutes of pure waiting before
the drift guard fires.

Fix in the same change: only the **first** candidate needs a real wait (the page may still be
settling). Once it has waited once, the DOM is loaded — later tiers can use ~300ms. Worst case
lands at roughly `1200 + 7×300 ≈ 3.3s`, better than today's 6s despite three more tiers.

---

## Phase 2 — Which tier resolved it

Phase 1 is a hypothesis. Without telemetry there is no way to confirm it worked, and no way to
tell whether a future regression is concentrated on one board or spread across all of them —
completely different fixes.

- `_find()` returns `(locator, tier)` instead of a bare locator; `None` becomes `(None, None)`.
- The fill loop accumulates `resolved_by: dict[str, int]` keyed by tier name.
- `_result()` gains a `resolved_by` key (default `{}`), and `missed` entries record which tiers
  were attempted.
- On a `drift` outcome, include the tier histogram in `detail`. "0/12 resolved, all tiers missed"
  and "7/12 resolved, all via xpath fallback" are the same verdict today and want opposite fixes.

**Compatibility — already verified.** `fill_application()` has exactly one consumer:
`scripts/autoapply.py:800`, which reads the result dict exclusively via `.get()` (lines 801–811).
`scripts/autoapply_server.py` does not call it — Layer 3 composes its own path. Adding a key is
therefore safe with no call-site change.

---

## Phase 3 — SUPERSEDED, not built

> This phase was scoped (below, kept for historical record) but never implemented. It is
> superseded by `spec/auto-apply-agentic-submit/` — the user decided the whole Layer 2 fill path
> should become a full agentic loop rather than a narrow last-resort fallback for exhausted
> selector tiers. Phase 1+2's `_find()`/`_semantic_locators()`/`resolved_by` telemetry are not
> discarded — they are reused verbatim by that feature's `locate_and_fill_field()` tool as the
> deterministic-first resolution path inside the agent loop.

Original scoping (superseded): when `_find()` exhausts every tier, snapshot the accessibility
tree, have the model map that one field, then **cache the resolved selector** back to disk so the
cost is paid once per form, not once per run. Deliberately deferred until Phase 2 telemetry said
how often the tiers actually exhaust; it was to "stay a last-resort fallback, never the primary
path." The superseding feature makes a different, explicitly-decided tradeoff instead — see
`spec/auto-apply-agentic-submit/problem.md`.

---

## Risks

- **Playwright strict mode.** `get_by_label` raises on multiple matches rather than picking one.
  Use `.first` consistently, as the existing code does at line 94.
- **`get_by_role("textbox")` is narrow.** It will not match selects, checkboxes, or file inputs.
  That is acceptable — those already resolve by `name` on Greenhouse — but do not assume the
  role tier covers `input_file` or `multi_value_single_select` fields.
- **A wider net can resolve the *wrong* field.** `aria_loose` is substring matching. This is the
  one change here that could make an application worse rather than merely unfilled, which is the
  failure class this whole subsystem is built to avoid. Exact-before-loose ordering is the
  mitigation; the fixture test below is the proof.
- **No change to `_classify_block()`.** Captcha/auth detection is out of scope.

## Verification

1. `pytest -v` — default suite, ~1.5s, must stay green. New `tests/test_autoapply_selector_tiers.py`
   runs here.
2. `pytest -m browser` — ~80s, needs `playwright install chromium`. Required, since this change is
   entirely inside `scripts/autoapply_browser.py`.
3. **Fixture must fail before it passes.** Add the three a11y-only fields to
   `tests/fixtures/greenhouse_form.html` and confirm they resolve `0/3` on current `main` before
   Phase 1, `3/3` after. A test that passes both before and after proves nothing.
4. Assert the existing invariant still holds: **the form is never submitted.** This is the single
   most important assertion in `tests/test_autoapply_browser.py` and must not be weakened.
5. Confirm `MIN_RESOLVE_RATIO` is unchanged at `0.6`. The goal is to raise the true resolve rate,
   not to lower the bar that detects drift.
6. `python scripts/dev_check.py` per the repo's Definition of Done.

## Pre-flight — resolve before starting

The working tree is not in a state where this change can be reviewed:

- **181 modified files, ~24.5k insertions / 24.5k deletions. Ignoring whitespace, the real diff is
  `spec/INDEX.md`, +2 lines.** 180 files are pure CRLF/LF churn — the same class of failure
  documented in `CLAUDE.md`'s Definition of Done and in the Step 15 changelog entry. Renormalize
  per `.gitattributes` first, or this change lands inside an unreviewable diff.
- **`feature/assemble` is `ahead 168, behind 168` of `origin/main`.** Symmetric counts point to a
  rebase or force-push on one side rather than 168 genuinely divergent commits each way. Confirm
  what happened before merging anything.
- 4 untracked files.
