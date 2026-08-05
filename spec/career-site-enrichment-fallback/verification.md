# Verification

**Already run (D, A, B):**
1. **A:** pointed at real SPA career pages with known JSON-LD (confirmed via `curl` that the
   `<script type="application/ld+json">` block exists first); confirmed `generic_url_fetch()`
   returns a real `company`/`location`, not blank.
2. **B:** pointed at a confirmed SPA failure case; confirmed real JD text comes back where the
   static fetch previously failed the 200-char guard.
3. **D:** forced 3+ consecutive enrichment failures on a test URL; confirmed it stops retrying
   after the ceiling and lands in a clearly-marked terminal state instead of looping forever.

**If Option C is picked up:** repeat verification step 2 above with C as the active fallback
instead of B, on the same confirmed-SPA-failure test case, to confirm parity before switching.
