# Claude-in-Chrome: execution mechanics and parallelism limits for auto-apply

*Research note for [issue #25](https://github.com/Iamkach/careerpilot-ai/issues/25), a child of
wayfinder map [issue #24](https://github.com/Iamkach/careerpilot-ai/issues/24)
(`spec/auto-apply-subsystem/`, `spec/application-prefill-extension/`). Primary-source investigation
only — no code changed, no architecture decision made here. Written in the style of
`docs/research/sourcing-bottleneck-analysis.md`: a measurement/findings record, not a plan.*

## Question asked

Is Claude-in-Chrome driven from an interactive Claude Code session, a background `Agent` call, or
something scriptable/headless that could run truly unattended? What are its practical constraints
for applying to N job postings "in parallel" — session/tab limits, rate limits, per-application
latency, and cost?

## Top-line answer

**Claude-in-Chrome, as available in this environment (`mcp__claude-in-chrome__*` tools inside
Claude Code), requires a real, running Chrome (or Edge/Chromium) browser on a machine with the
extension installed, connected to an interactive Claude Code session via a native-messaging host.
There is no documented headless or fully-unattended invocation path for this tool family.** Browser
actions execute one at a time within a single connected browser (batchable via `browser_batch`, but
still sequential, not concurrent); "multiple tabs" means Claude can *track and read across* several
open tabs in one session, not drive them simultaneously. No official documentation states a hard
numeric tab limit, a rate limit, or a per-task token/cost benchmark for this tool family — those are
explicitly flagged below as open questions rather than guessed at.

This directly bears on the map's premise ("user triggers next step, then multiple jobs get applied
to in parallel"): true parallelism (N jobs filled concurrently, unattended) is not something the
`mcp__claude-in-chrome__*` tool family is documented to provide. Any "parallel" story would have to
be built as N *sequential* fills orchestrated by something else (see open questions below), not N
simultaneous Claude-in-Chrome executions.

---

## 1. What Claude-in-Chrome concretely is, and what has to be running

There are **two distinct products** built on the same browser extension, and the repo's proposal
(`mcp__claude-in-chrome__*` tools "available in Claude Code") is specifically the second one:

- **Claude in Chrome (claude.ai product)** — a side-panel assistant inside Chrome, driven from
  claude.ai or the Claude desktop app. Source:
  [Get started with Claude in Chrome](https://support.claude.com/en/articles/12012173-get-started-with-claude-in-chrome)
  — "Claude in Chrome is a browser extension that allows Claude to read, click, and navigate
  websites alongside you." "Claude in Chrome is not supported on other Chromium-based web browsers
  or mobile devices."
- **Claude Code's Chrome integration** — the same extension, but driven from a Claude Code CLI/VS
  Code session via MCP tools (`mcp__claude-in-chrome__*`), which is what this repo's environment
  exposes. Source:
  [Use Claude Code with Chrome](https://code.claude.com/docs/en/chrome) — "Claude Code integrates
  with the Claude in Chrome browser extension to give you browser automation capabilities from the
  CLI or the VS Code extension." "Browser actions run in a visible Chrome window in real time."

For the Claude Code path (the relevant one here), concretely required, per the same doc:

- Google Chrome, Microsoft Edge, or another Chromium-based browser (Brave, Arc, Vivaldi, Opera) —
  **not** supported in WSL: "Chrome integration isn't supported in Windows Subsystem for Linux
  (WSL)."
- The Claude in Chrome extension installed (version 1.0.36+) in that browser.
- Claude Code itself, started with `--chrome` (or enabled by default via `/chrome`).
- Sign-in via `/login` with a direct Anthropic plan (Pro/Max/Team/Enterprise) — "If you authenticate
  with an API key or a long-lived token from `claude setup-token`, Claude Code keeps Chrome
  integration off... because the browser extension can't authenticate with those credentials."
  "Chrome integration is not available through third-party providers like Amazon Bedrock, Google
  Cloud's Agent Platform, or Microsoft Foundry."
- A native-messaging host config file that Chrome reads on startup, installed by Claude Code on
  first Chrome-integration use, at a machine-specific path (e.g.
  `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.anthropic.claude_code_browser_extension.json`
  on macOS, or a Windows registry key `HKCU\Software\Google\Chrome\NativeMessagingHosts\`).

Session state and identity ride on the local browser: "Claude opens new tabs for browser tasks and
shares your browser's login state, so it can access any site you're already signed into." This is
why a form on an authenticated site (e.g. a LinkedIn-gated apply flow) would "just work" without new
credential plumbing — and also why the browser has to be *this* browser, on *this* machine, already
logged in.

**No remote/headless mode is documented.** The doc's own troubleshooting section assumes a visible,
locally-running Chrome the whole way through (e.g. "Check if a modal dialog... is blocking the
page," "Ask Claude to create a new tab and try again," service-worker-goes-idle disconnects). Nothing
in `code.claude.com/docs/en/chrome` describes pointing this integration at a remote/CI browser, a
Docker container, or a display-less environment. This is different from the separate, lower-level
**Computer Use API tool** (`computer_20251124` etc., see
[Computer use tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)),
which *is* explicitly designed to run against a sandboxed/headless VM the caller provisions — but
that is a raw API primitive requiring you to build your own agent loop and browser environment, not
the `mcp__claude-in-chrome__*` tool family this repo would actually consume. **Open question:**
whether Claude-in-Chrome specifically (as opposed to the generic Computer Use primitive) can be
pointed at a non-local, non-interactive browser at all — not found in available documentation.

## 2. Can it be kicked off non-interactively (no human watching)?

**No documented path for this.** Several independent signals converge:

- Tool-level: the `mcp__claude-in-chrome__list_connected_browsers` tool's own description (visible
  in this environment's tool schema) states: *"Before any browser action, you MUST call the
  AskUserQuestion tool with a question listing EVERY connected browser as a separate option... Do
  not skip any connected browser and do not pick one yourself."* — browser selection is
  hard-required to route through a human-facing question, by the tool's own instructions, not just
  a convention.
- Login/CAPTCHA: `code.claude.com/docs/en/chrome` — "When Claude encounters a login page or CAPTCHA,
  it pauses and asks you to handle it manually." A blocked run cannot self-resolve.
- Permission gating: browser tool calls that change state (clicks, typing, navigation, tab/window
  management) prompt for approval in plan mode; only pure reads (`read_page`, `get_page_text`,
  `find`, console/network reads, screenshots) run without a prompt. Source: same doc, "Browser tools
  in plan mode" section.
- First-use install/consent: "Before Claude's first browser action, Claude Code asks for permission
  to use the `claude-in-chrome` skill." — an explicit one-time human approval gate, separate from
  per-site permissions.
- The `computer` tool's own upstream guardrail (the primitive this integration is built on) is
  explicitly designed around a human being present: Anthropic's guidance is to have a human
  *"confirm decisions that might result in meaningful real-world consequences and any tasks
  requiring affirmative consent, such as accepting cookies, completing financial transactions, or
  agreeing to terms of service."* Its prompt-injection classifier layer "steer[s] the model to ask
  for user confirmation before proceeding with the next action," and Anthropic's own docs note this
  "won't be ideal for every use case (for example, use cases without a human in the loop)" — opting
  out requires contacting Anthropic support, i.e. it is not something this app can silently disable.
  Source: [Computer use tool — Security considerations](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool).

**Background `Agent` tool call:** launching Claude-in-Chrome-driven work from a background `Agent`
call (as opposed to the interactive foreground session) does not change any of the above — the
underlying MCP tools still route browser selection and any state-changing/CAPTCHA/login moment
through the same human-confirmation mechanics. A background agent would either stall at the first
such prompt (no human present to answer) or would need pre-answered/non-interactive tool
configuration that is not documented as available for this tool family. **Open question:** whether
there is an unattended/pre-approved mode for `mcp__claude-in-chrome__*` tools specifically (distinct
from the raw Computer Use API, which does support a fully programmatic agent loop against a
self-provisioned sandbox) — not found in available documentation; the working assumption should be
"no" until Anthropic documents otherwise.

Separately, the **claude.ai product** (not Claude Code) does offer scheduled/recurring tasks and a
"planning mode" that, once approved, "let[s] it execute independently until complete" — per
`support.claude.com`'s release notes (Sept 16 2025: multi-step workflows continue "even when you
switch tabs (as long as Chrome is open)"; Sept 29 2025: multi-tab; Nov 24 2025: scheduled tasks and
planning mode). **This is a different execution surface from the `mcp__claude-in-chrome__*` tools
available in Claude Code** — it is claude.ai's own side-panel product operating standalone, not
something this repo's Claude Code environment can invoke via the MCP tool family named in the
ticket. Whether "planning mode" is architecturally closer to what issue #24 wants (approve once,
then unattended execution) is a real avenue, but it is a **different product surface** than the one
the ticket names, still requires Chrome to be open on a real machine ("as long as Chrome is open"),
and its own scheduling/unattended guardrails are not documented in enough depth here to say whether
it would still pause on a login/CAPTCHA/consent moment the way the interactive tool does. Flagged as
an open question for the orchestration-mechanism ticket, not resolved here.

## 3. Tab/session parallelism

- `mcp__claude-in-chrome__browser_batch` — the closest thing to "do several things per round trip" —
  is explicitly sequential, not concurrent: its own description states *"Actions execute
  SEQUENTIALLY (not in parallel) and stop on the first error."* One failing step (e.g. a field not
  found) halts the rest of the batch.
- `mcp__claude-in-chrome__tabs_create_mcp` / `tabs_context_mcp` / `tabs_close_mcp` manage a group of
  tabs *within one MCP session*, one browser connection. Nothing in these tools' descriptions
  suggests concurrent driving of multiple tabs — `tabs_context_mcp`'s guidance is "get the context
  at least once before using other browser automation tools so you know what tabs exist," implying
  a single active context the agent reasons over serially.
- claude.ai's own release notes describe multi-tab as Claude "juggl[ing]" tabs and being able to
  "see and work across all of them simultaneously" (Sept 29 2025 note) — read/track across tabs, not
  documented as literally acting on N tabs at the same instant. No official source states a per-tab
  or per-session numeric cap for either surface.
- `mcp__claude-in-chrome__list_connected_browsers` / `select_browser` / `switch_browser` operate at
  the *browser instance* level (e.g. picking among multiple machines' Chrome extensions connected to
  one account), not at the tab-parallelism level, and every path through them is gated by the
  human-facing `AskUserQuestion` step noted above.

**Conclusion:** within the `mcp__claude-in-chrome__*` tool family, "N jobs in parallel" is not
supported as concurrent execution. It would have to be N sequential form-fills (one job's tab and
fields at a time), possibly interleaved across tabs for context-gathering but not simultaneously
acted on. True process-level parallelism (multiple independent browser/agent processes) is not
something this tool family exposes — it is scoped to one connected browser, one MCP session.

## 4. Latency and cost per form-fill task

**No official documented numbers were found for either Claude-in-Chrome specifically or a
comparable "typical job-application form" task.** This is stated plainly per the task instructions
rather than estimated:

- `code.claude.com/docs/en/chrome` documents *capabilities* (navigate, read_page, get_page_text,
  find, form_input, computer, javascript_tool, file_upload, gif_creator) and example workflows, but
  no latency/turn-count/token benchmarks for any workflow, including the closest analog ("Automate
  form filling" — a CRM data-entry example with no timing/cost figures attached).
- The Computer Use API doc (`platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool`)
  gives *qualitative* cost guidance only, and only for the raw API tool, not the Claude-in-Chrome MCP
  layer: thinking-effort recommendations by model ("Claude Opus 4.7: use `high` as the default; use
  `low` for high-throughput or cost-sensitive workloads"; "Claude Sonnet 4.6 and Claude Opus 4.6: use
  `medium` as the default (best accuracy-to-cost ratio)... `low` uses *fewer* output tokens than
  disabling thinking entirely"), and a default `max_iterations=10` example in its reference agent
  loop as a runaway-cost safeguard — "This safeguard prevents potential infinite loops that could
  result in unexpected API costs" — with no stated real-world dollar or token figure attached to that
  default.
- Real per-application mechanics (how many `find`/`read_page`/`computer`/`form_input` calls a
  multi-field Greenhouse/Lever form would realistically take) were not exercised as part of this
  research task, per its scope (documentation-only, no code/execution). Given this repo's own
  Stage 7 Layer 1 evidence (`scripts/autoapply.py`'s `GENERIC_QUESTIONS` fallback and Greenhouse
  schema fetch), a typical application form has on the order of 10-20 fields, which — by rough
  inference, not a documented figure — would plausibly need one read/find call per field-group plus
  one write call per field, i.e. low tens of tool calls per application; this is an *inference from
  the pipeline's own field counts*, not something Anthropic's docs state, and should not be treated
  as a benchmark.

**Open question, stated explicitly rather than guessed at:** no primary source gives wall-clock time
or token cost per form-fill task for Claude-in-Chrome. Any planning that depends on this number
should be based on a live measured pilot (e.g. instrument a handful of real Stage-7-eligible
applications through the MCP tools and record turn count/tokens/wall-clock directly), not on
documentation, because the documentation does not contain it.

## 5. Safety/guardrail mechanisms relevant to "never auto-submit"

Several mechanisms exist, at different layers, that are directly relevant to this repo's hard
invariant (Python decides what's safe to fill; a human clicks Submit; `Applied` is never inferred —
see CLAUDE.md's Stage 7 section):

- **Per-action risk classification.** `support.claude.com`'s safety article: *"Automatic action
  screening: When Claude works on its own, it checks each action for risk and for hidden malicious
  instructions before running it."* And: *"Action confirmations for certain high-risk actions such
  as downloading a file or entering sensitive information."* Source:
  [Use Claude in Chrome safely](https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely).
- **Explicit block list.** The same article states Claude is blocked from "Engaging in stock trading
  or investment transactions, Bypassing captchas, Inputting sensitive data, Gathering or scraping
  facial images." Submitting a job application is not on this explicit block list, so it is **not**
  structurally prevented by Claude-in-Chrome itself — the "never auto-submit" invariant would remain
  something this repo's own prompting/tool-usage discipline has to enforce (e.g. simply never issuing
  the click on the Submit button), not something Anthropic's guardrails enforce for you.
- **Content-injection classifiers.** `support.claude.com`: *"We scan all untrusted content entering
  Claude's context and flag potential injections before they can affect behavior,"* claimed to
  reduce "attack success rates to less than 0.08% against our internal testing." Relevant because a
  job-posting page or ATS form is exactly the kind of untrusted third-party content this classifier
  is meant to screen — a poisoned job description could otherwise attempt to redirect Claude's
  actions.
- **User responsibility clause.** Explicitly stated: *"You remain responsible for all browser actions
  taken by Claude performed on your behalf."* — Anthropic's own framing places the onus for
  correctness (including "did it actually stop before Submit") on the operator, not the tool.
- **Plan-mode read/write split** (Claude Code specifically, `code.claude.com/docs/en/chrome`):
  reads (`read_page`, `get_page_text`, `find`, console/network reads, screenshots) proceed without a
  prompt; anything state-changing (click, type, navigate, tab/window management, GIF recording)
  requires approval in plan mode. This is a real mechanical lever this repo could lean on: if a
  Claude-in-Chrome-driven fill flow runs in Claude Code's plan mode, every click (including a
  hypothetical Submit click) would require an explicit approval, which is a workable technical
  backstop for the "never auto-submit" invariant — but it is a Claude Code session-mode setting, not
  a Claude-in-Chrome-specific guarantee, and would need to be deliberately configured/verified as
  part of any implementation, not assumed.
- **Computer Use API's own explicit consent guidance** (the lower-level primitive): recommends "a
  human to confirm decisions... requiring affirmative consent, such as accepting cookies, completing
  financial transactions, or agreeing to terms of service" — guidance, not enforcement, and again
  aimed at API implementers building their own loop, not automatically inherited by the
  Claude-in-Chrome MCP layer.

**No mechanism found that structurally prevents a Submit click the way, say, captcha-bypass is
explicitly blocked.** The "never auto-submit" invariant would have to be enforced by this
repo's own tool-usage design (e.g. never granting/using a `computer`/`form_input` call that targets
the Submit control, and/or running under plan-mode confirmation for all state-changing calls), not
by any built-in Claude-in-Chrome restriction.

## 6. Unattended/bulk automation and ToS considerations

- Nothing in `code.claude.com/docs/en/chrome`, `support.claude.com`'s "Get started" article, or its
  "Use Claude in Chrome safely" article explicitly discusses or warns against bulk/automated job
  application submission as a use case. The safety article's explicit block list (stock trading,
  captcha bypass, sensitive data input, facial image scraping) does not name job-application
  automation.
- This is a narrower question than this repo's existing LinkedIn/Indeed concern. CLAUDE.md already
  documents (under "LinkedIn/Indeed are never filled") that automating applications on those two
  platforms specifically "violates ToS and is behaviorally detected" — that is a statement about
  **LinkedIn's/Indeed's own ToS**, not Claude-in-Chrome's usage policy. Whether Anthropic's own
  Claude-in-Chrome usage policy separately restricts or discourages using it against a platform whose
  own ToS prohibits automation was **not found in available documentation** — the safety article
  discusses site-permission allowlists/blocklists (admin-configurable) and a general prompt-injection
  defense, but not a blanket policy statement about respecting third-party sites' anti-automation
  ToS. **Open question**, not resolved here: does using Claude-in-Chrome to fill a LinkedIn Easy
  Apply form (which the repo already avoids for its own ToS reasons) additionally risk violating
  Anthropic's own usage policies for the tool, independent of LinkedIn's ToS? Not addressed by any
  primary source reviewed.
- Given issue #24's own scoping note ("Auth/session handling: Claude-in-Chrome runs in the user's
  real logged-in Chrome, which may unblock LinkedIn/Indeed... does that rule get revisited?"), this
  is a live open question for that map, not something this research closes — flagging it here rather
  than speculating on Anthropic's unstated policy stance.

---

## Summary table

| Question | Finding | Confidence |
|---|---|---|
| What is it, mechanically? | Chrome/Edge/Chromium extension + native-messaging host, connected to an interactive Claude Code (or claude.ai) session | Documented — `code.claude.com/docs/en/chrome`, `support.claude.com` |
| Needs a real running browser on the user's machine? | Yes — no remote/headless mode documented for this tool family; explicitly unsupported in WSL | Documented (absence of any headless path) |
| Can it run unattended (no human)? | No documented path — browser selection, CAPTCHA/login, and state-changing actions all require human interaction/confirmation by the tools' own descriptions and docs | Documented (multiple independent confirming signals) |
| Background `Agent` call changes this? | No — same MCP tools, same human-confirmation gates apply regardless of foreground/background invocation | Inferred from tool mechanics, not separately documented |
| Multiple jobs "in parallel"? | Not supported as concurrent execution — `browser_batch` is explicitly sequential; multi-tab is track/read-across, not simultaneous-act-on | Documented (`browser_batch` description) + absence of any concurrency claim elsewhere |
| Hard numeric tab/session limit? | Not found in any source reviewed | Open question |
| Rate limits specific to this tool family? | Not found in any source reviewed | Open question |
| Latency/token cost per form-fill task | No official benchmark found; only qualitative thinking-effort/cost guidance for the unrelated raw Computer Use API | Open question — recommend a live measured pilot |
| Guardrails relevant to "never auto-submit" | Risk-based action screening + high-risk action confirmations + plan-mode read/write split (Claude Code specific) — but no explicit block on form-submission itself | Documented, but doesn't fully cover the specific invariant |
| Anthropic ToS stance on bulk/unattended job-application automation, or on automating a site whose own ToS forbids it | Not found in available documentation | Open question |

## Sources

- [Use Claude Code with Chrome](https://code.claude.com/docs/en/chrome) — Claude Code docs, primary
  source for the `mcp__claude-in-chrome__*` tool family's requirements, plan-mode gating, and
  troubleshooting behavior.
- [Get started with Claude in Chrome](https://support.claude.com/en/articles/12012173-get-started-with-claude-in-chrome) —
  Claude Help Center, the claude.ai-product side of the same extension.
- [Use Claude in Chrome safely](https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely) —
  Claude Help Center, safety classifiers, action confirmations, explicit block list, user
  responsibility clause.
- [Release notes](https://support.claude.com/en/articles/12138966-release-notes) — Claude Help
  Center, dated entries for multi-tab (2025-09-29), continued multi-step workflows (2025-09-16),
  scheduled tasks and planning mode (2025-11-24).
- [Computer use tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) —
  Anthropic API docs for the lower-level Computer Use primitive Claude-in-Chrome is conceptually
  built on; used here only for its security-consideration guidance and cost/effort notes, which are
  explicitly **not** the same product as the MCP tool family this repo would consume.
- `mcp__claude-in-chrome__browser_batch`, `mcp__claude-in-chrome__tabs_context_mcp`,
  `mcp__claude-in-chrome__tabs_create_mcp`, `mcp__claude-in-chrome__tabs_close_mcp`,
  `mcp__claude-in-chrome__list_connected_browsers`, `mcp__claude-in-chrome__select_browser`,
  `mcp__claude-in-chrome__switch_browser` — tool schemas/descriptions as loaded directly in this
  Claude Code environment via `ToolSearch`, quoted verbatim above.
- GitHub issue [#25](https://github.com/Iamkach/careerpilot-ai/issues/25) and parent map
  [#24](https://github.com/Iamkach/careerpilot-ai/issues/24) — the questions and existing
  architectural context this research answers into.

## What was NOT done

No code was written or changed. No Claude-in-Chrome session was actually driven against a live job
application form to measure real latency/token cost — the task scope was documentation research
only, and the "no official benchmark found" conclusion in §4 reflects that boundary, not an attempt
that failed. No architecture decision was made; that remains for a later wayfinder session per
issue #24's own process note.
