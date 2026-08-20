# End goal

Once Phase 1 ships: every job sourced directly from a Greenhouse/Lever/Ashby board
self-confirms that company's token in `config/ats_tokens.json`, marking it `provenance:
"observed"` instead of `"guessed"`. An observed token is never re-probed (the 30-day staleness
rule no longer applies to it) and a future guess can never downgrade it. Unreachable boards
(Workday, iCIMS, etc.) are recorded as data even where nothing can be crawled, so a future
decision to build a new crawler is evidence-based rather than speculative.

This is explicitly a **self-confirmation** mechanism for Phase 1, not a new-coverage mechanism —
it does not, by itself, move the 23/100 baseline for companies with zero observed board presence.
The registry compounds over time (each run's board-sourced jobs seed the next run's confidence),
and later stories (the curated target-companies list, Step 15's live-apply-page feed) are the
paths that grow *coverage* past today's 23%.
