# Acceptance criteria

## Already met (D, A, B — shipped)
- [x] A URL with known JSON-LD returns a real `company`/`location`, not blank.
- [x] A confirmed SPA case that static fetch fails now returns real JD text via headless render.
- [x] After `MAX_ENRICHMENT_ATTEMPTS` consecutive failures on one URL, enrichment stops retrying
      and the row lands in a clearly-marked terminal state (`Scraped` + `Notes` marker) instead of
      looping forever.
- [x] Playwright absent or the render failing degrades to the pre-existing "treat as enrichment
      failure" behavior, never a hard error.

## Open (Option C only, gated by its trigger)
- [ ] If Option C is picked up: the same three D/A/B-equivalent behaviors above hold when C is the
      active SPA fallback instead of B, with no change to `ingest_interested_from_notion()`'s
      calling contract.
