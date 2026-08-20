# End goal

Already true (D, A, B shipped): a hand-picked "Interested" URL that isn't Greenhouse/Lever/Ashby
gets a real attempt at structured fields via JSON-LD, a headless-Chromium retry for JS-rendered
shells, and a bounded number of retries before giving up and asking a human to fill the JD in by
hand — never scored against a blank description, and never retried forever.

If Option C is ever picked up (only on its trigger): the same enrichment floor exists without
requiring Playwright/Chromium to run in the pipeline's actual runtime environment, by paying a
per-call fee to a scraping API instead of self-hosting a headless browser — a straight substitution
for the B fallback, not a new capability.
