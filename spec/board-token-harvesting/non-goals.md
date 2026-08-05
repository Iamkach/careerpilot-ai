# Non-goals

- **LinkedIn/Indeed apply-URL harvesting** — dropped entirely, not deferred. LinkedIn confirmed
  empty (falsified by spike). Indeed's only populated path requires `followApplyRedirects: True`,
  which is parked (see below), not adopted.
- **Flipping Indeed's `followApplyRedirects` to harvest `externalApplyLink`.** Parked, not
  rejected — two spikes disagree on both cost (+64% vs. no measurable delta) and yield
  composition (0/4 vs. 1/1 ATS hosts) at samples too small to trust either way. Revisit only with
  a properly sized measurement (`max_results=25`+ across several `TARGET_ROLES`), and only if
  Step 15's live-page feed turns out not to cover enough volume on its own.
- **Following LinkedIn apply redirects.** Excluded by rule (constraints.md #4), not deferred —
  rejected. LinkedIn's apply link sits behind an authwall; resolving it would require an
  authenticated session, the exact ToS/behavioral-detection surface `FILLABLE_CHANNELS` already
  excludes LinkedIn from.
- **Mirroring the registry to Notion.** That's a separate, already-implemented story (the curated
  target-companies list), scoped to a curated subset rather than the full harvested registry —
  not tracked here.
- **Careers-page crawling for companies with no observed URL** (fetch `{company}.com/careers`,
  look for ATS links). A real per-company network cost; only worth it if Phases 1-2 leave a large
  gap.
- **Step 15's live-apply-page harvest feed.** The stronger, confirmed-not-guessed signal (a human
  standing on a real apply form) belongs to `spec/application-prefill-extension/` once implemented
  — this story only commits to keeping `parse_board_url()` and the cache schema
  (`provenance`, `observed_from`, `checked`) stable enough for that feed to plug in without rework.
- **Phase 3 new `BOARD_SOURCES` entries** (SmartRecruiters, Workable, etc.) — gated on Phase 2
  data showing ≥5 tracked companies on a given provider; not built speculatively.
