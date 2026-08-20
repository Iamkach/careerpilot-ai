# Agent-browser landscape — evaluation for Stage 7 Layer 2

**Date:** 2026-08-10
**Type:** research record (analysis, not a plan) — see `spec/selector-resolution-hardening/` for
the resulting work.

## Question

Stage 7 Layer 2 (`scripts/autoapply_browser.py`) drives Playwright. A backlog of fixes to that
automation prompted the question: should it move to one of the newer agent-native browsers or
MCP-based browser tools?

Requirements it has to satisfy: read a job page, fill a form, **upload a `.docx`**, run against a
few dozen known ATS boards with mixed public / login-walled access, and return a structured
failure with a reason rather than a partial success.

## Candidates

### Lightpanda — evaluated, rejected for the write path

A headless browser written in Zig, no rendering engine, ~10–30MB resident, ~11× faster cold start
than Chrome headless, with CDP and a native MCP server.

Its advantage is memory and cold start at **very high concurrency** — thousands of stateless page
loads. Stage 7 is capped at `AUTOAPPLY_DAILY_CAP = 10` applications per run against a few dozen
boards. The scale where that advantage pays for itself is never reached here.

Against that, it is still beta: no service workers, no IndexedDB, incomplete CORS, no graphical
rendering engine, and it does not implement every CDP behaviour Chrome does (notably, one
BrowserContext per connection). Reporting on it is explicit that it is a poor fit for SPA-heavy
applications — which describes Workday and most modern ATS front-ends.

**Possible future fit:** a cheap read-only pre-pass. It is not a candidate for the layer that
fills forms and attaches files.

### Vercel `agent-browser` — noted, not adopted

A Rust CLI/daemon over Chromium, 50+ commands, with compact DOM output that reportedly removes up
to 93% of irrelevant context. A persistent daemon keeps subsequent commands fast.

This is a **control layer**, not a browser engine — the category confusion worth recording is that
Lightpanda and `agent-browser` are not competitors; one replaces Chromium, the other replaces the
Playwright-shaped API on top of it. Its compact-output idea is the genuinely interesting part and
is what Phase 3 of the plan borrows. Rejected for now on maturity, and because adopting it would
mean rewriting the working 90% to fix the failing 10%.

### MCP browser tools

| Tool | Note |
|---|---|
| Playwright MCP | Real Chromium, accessibility-tree output, file-upload tool, persistent profiles |
| Chrome DevTools MCP | Google's official, CDP over puppeteer-core. Closest drop-in, Chromium only |
| Browserbase MCP | Managed, best debugging — session replay |
| Steel MCP | Open source, self-hostable or cloud behind one API |
| Hyperbrowser MCP | Leans hardest into stealth and captcha handling |

These matter for the *fallback* path, not the primary one. An MCP browser's value is that it hands
a model the accessibility tree and lets it resolve fields per-run — trading selector maintenance
cost for per-run token cost and nondeterminism. That trade is worth making for the fields that
currently fail; it is a bad trade for the fields that already resolve deterministically.

### Direct Playwright alternatives

- **Chrome DevTools MCP** — closest drop-in, barely changes the calling code.
- **Selenium** — W3C WebDriver, Python-native, most mature, the only option here with real
  non-Chromium support. Slower, clunkier API.
- **nodriver / zendriver / pydoll** — Python, raw CDP, no webdriver. Stealthier and Python-first;
  smaller ecosystems, and an MCP wrapper would have to be written.
- **Puppeteer MCP** — Node-only. Poor fit for a 99%-Python repo.
- **Patchright / Camoufox** — these appear in "Playwright alternative" lists but are Playwright
  underneath. They are stealth patches, not a different driver.

## Headed vs headless, and session administration

Headed/headless is a launch flag, not an architectural choice — the same tools and actions work
either way. `AUTOAPPLY_HEADLESS = False` (`config/settings.py`) already reflects the deliberate
choice to leave the browser open for the human to review and submit.

The standard pattern for login-walled boards is: bootstrap headed so the human logs in and clears
MFA, persist to a `--user-data-dir` profile or `storage_state`, run headless thereafter, and
re-escalate to headed when the session expires.

The constraint worth recording: **a server-side agent cannot pop a window for the user.** Xvfb
gives you a "headed" virtual display (useful against headless sniffing) but the human still cannot
interact with it. The real answer for cloud deployment is a live-view session URL — Browserbase and
Steel both provide one — which the human opens, logs in, and whose session then persists into
subsequent headless runs. For a locally-run agent, a Chrome extension attached to the user's own
already-authenticated browser removes the bootstrap step entirely; the repo's Layer 3 extension
already takes this route.

## Conclusion — retain Playwright

The measured evidence points away from the driver. `scripts/autoapply_browser.py` is 240 lines, of
which the fragile part is `_candidate_selectors()` / `_find()`: a hand-rolled resolver that tries
`[name=]`, `#id`, and three XPath label fallbacks, then silently gives up. Every candidate driver
above would require re-implementing that same resolver and would inherit the same misses, because
the misses are caused by markup the selectors cannot express — labels linked by `for=`,
`aria-label`, `aria-labelledby` — not by anything Playwright does or fails to do.

Playwright already ships accessibility-tree locators (`get_by_label`, `get_by_role`) that cover
exactly those cases and are not currently used. The cheapest available fix is inside the tool
already in the repo.

## What would reverse this

Following the "backup plan" convention used for the Apify sourcing pair in `CLAUDE.md` — recorded
now so the trigger is recognised rather than re-derived later:

- **Phase 2 telemetry shows the tiers still exhaust often after Phase 1.** Then per-run model
  resolution is genuinely needed, and an MCP browser becomes the natural home for it.
- **Stage 7 moves to cloud/CI execution with login-walled boards.** Self-hosted Playwright has no
  answer for handing a human an interactive session; Browserbase or Steel do.
- **Concurrency rises by an order of magnitude.** Lightpanda's memory profile only starts to
  matter well above the current `AUTOAPPLY_DAILY_CAP = 10`.
- **Non-Chromium coverage becomes a requirement.** Selenium is the only realistic option.

None of these are true today.

## Addendum (2026-08-10, same day) — conclusion reversed by direct decision

This conclusion has been explicitly reversed — not by one of the triggers above firing, but by a
direct decision that the deterministic ceiling itself (not a selector-tier gap) is now the
dominant cost: jobs on schema-unknown channels (Lever/Ashby) or hitting `MIN_RESOLVE_RATIO` drift
have no adaptation path and sit at `Needs Human: *` until a human notices, and every successfully
filled application still required a human to open it and click Submit. See
`spec/auto-apply-agentic-submit/problem.md` for the full reasoning.

The analysis above is not wrong and is left intact: it correctly identified that the
then-known failure mode (selector-tier misses) had a cheaper fix already inside Playwright, and
that fix shipped as `spec/selector-resolution-hardening/` Phase 1+2. That work is not discarded —
it is reused as the deterministic-first resolution tier inside the new agentic loop
(`locate_and_fill_field()` in `scripts/autoapply_agent_tools.py` tries it before falling back to
agent reasoning). What changed is the scope of the question: this addendum answers "should the
whole fill-and-submit flow become agentic," not "should the selector resolver."

## Sources

- [Lightpanda documentation](https://lightpanda.io/docs/) · [Why build a new browser](https://lightpanda.io/blog/posts/why-build-a-new-browser)
- [Lightpanda limitations analysis](https://www.qoo10.co.id/en/tech/91797/lightpanda-challenges-chrome-in-headless-speed-yet-its-limits-remain-hard-to-ignore/)
- [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) · [agent-browser.dev](https://agent-browser.dev/)
- [Browserbase vs Steel vs Hyperbrowser (APIScout, 2026)](https://apiscout.dev/guides/browserbase-vs-steel-vs-hyperbrowser-browser-infrastructure-2026)
- [Best browser agents 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-browser-agents)
- [Headless browsers for AI agents compared](https://yan-labs.github.io/headless-browser-ai-agents/)
