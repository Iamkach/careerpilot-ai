# End goal

Once this ships: `ENABLED_SOURCES` can include `"wellfound"`, and every Stage 1 run additionally
searches Wellfound per `TARGET_ROLES` via a chosen Apify actor, returning listings in the same
shared dict shape every other source uses. Those listings flow through the existing
`collapse_by_fingerprint()` dedup (so a job also posted to a company's Greenhouse board still
collapses to one row, board-sourced per `SOURCE_PRIORITY`), the existing freshness/company/
sponsorship filters, and the existing batched AI scoring — completely unmodified. A user running
the default pipeline sees startup/early-stage roles that never touch LinkedIn, Indeed, or a
public ATS board.

`SOURCE_PRIORITY` gets a `"wellfound"` entry so a cross-posted job still collapses onto the fuller
ATS-board copy when one exists, the same reasoning already documented for `linkedin`/`indeed`
losing to `greenhouse`/`lever`/`ashby`.
