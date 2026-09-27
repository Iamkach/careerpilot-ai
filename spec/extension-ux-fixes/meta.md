# Extension UX fixes

**Status:** superseded — dropped with `application-prefill-extension` 2026-09-27, see
[triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61) and closed
[#44](https://github.com/Iamkach/careerpilot-ai/issues/44): fixing UX bugs in a decommissioned
extension is not worth doing.
**Priority:** —
**Size:** S — three targeted, independent fixes in existing files; no new architecture.
**Depends-on:** [application-prefill-extension]

Three Layer 3 browser-extension bugs, diagnosed via direct code read 2026-08-02/03 (not guessed):
bridge token never auto-recovers after a manual `--serve` restart, field badges flicker on live
application forms, and opening a job from the panel's job list doesn't route to that job's plan.
