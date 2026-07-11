# Step 0 — Rotate `APIFY_API_TOKEN`

**Priority:** P0 — security incident, not a feature. Do this regardless of when the rest of the
roadmap lands.
**Depends on:** none
**Blocks:** Step 7 (moves secrets into GitHub Actions — must not carry a leaked token into CI)
**Size:** XS (~15 min + propagation)
**Source plan(s):** [`refinement-plans/README.md`](../refinement-plans/README.md) Step 0;
[`refinement-plans/sourcing/scraping-sources.md`](../refinement-plans/sourcing/scraping-sources.md)
(flags it independently)

## Context

A live Apify API token is committed in plaintext and is in git history — anyone with read access
to the repo (or its history) can spend against the account.

## Current behavior

`config/settings.py:142` hardcodes `APIFY_API_TOKEN` as a literal string. It has been committed
to VCS and is reachable via `git log -p` even if removed from the current file.

## Acceptance criteria

- [ ] Rotate the token in the Apify console (invalidates the leaked one immediately).
- [ ] Replace the literal in `config/settings.py` with `os.environ.get("APIFY_API_TOKEN", "")`.
- [ ] Add the new token to the local `.env` (or however secrets are loaded today) — **not** to the
      repo.
- [ ] Confirm `.env` (or equivalent) is in `.gitignore`.
- [ ] Grep the current tree for any other plaintext literal secrets alongside it (the architecture
      analysis also flags Anthropic/OpenAI/Supabase `service_role` keys as historically committed
      on `main`, R2 — confirm those are already env-sourced on this branch; if not, fold them into
      this rotation pass).
- [ ] `python run.py --setup` still reports Apify as configured after the swap.

## Out of scope

- Scrubbing git history (BFG/filter-repo) — a separate decision with its own blast radius; note it
  as a follow-up if the user wants it, don't do it as part of this story.
- Any other settings.py changes (those belong to later steps).

## Files touched

`config/settings.py`

## References

- Architecture analysis §D.1 risk register, R1 (🔴) and R2 (🔴).
- Architecture analysis §C.7 roadmap DAG — Step 0 is the only node with no inbound dependency.
