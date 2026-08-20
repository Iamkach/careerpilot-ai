# Acceptance criteria

- [ ] Phase-0 spike answers recorded before any Phase 1+ code is written.
- [ ] Loud failure: point `LEAD_ACTOR` at garbage → non-zero exit, nothing written. Empty-but-real
      run → exit 0, "0 leads." Same for a Hunter 401/429.
- [ ] Leads DB created by hand first; renaming one property afterward produces a real, logged
      Notion exception — not a silent no-op.
- [ ] `accept_all` policy: (a) score ≥ threshold + address present → persisted, unverified note in
      digest; (b) score < threshold → no email; (c) only `pattern` present, no address → Email
      property stays empty.
- [ ] Unit test proves `pattern` has zero code path to the `Email` property, and the AI validator
      drops any returned idx/name/email absent from the API input set.
- [ ] Credit budget: cap reserve floor to 2 spendable credits, enqueue 5 jobs → ≤2 spent, 3 remain
      `Ranked`; re-querying the same search in the same calendar month costs Hunter **0**.
- [ ] CI parity: `workflow_dispatch` run with `AI_PROVIDER=claude` succeeds with no `claude /login`
      session; local run under `claude_code` produces equivalent output; `ANTHROPIC_API_KEY`
      confirmed absent from the local environment.
- [ ] After a CI run, every draft is readable in the Notion lead page body, not only the artifact.
- [ ] A staffing-firm recruiter is dropped `company`; a relevance score of 40 is dropped
      `low-relevance`.
- [ ] The gate holds: stage 7 lands every lead as `New`; running the drafter with none `Approved`
      produces zero drafts; approving one by hand produces exactly one draft, moving only that lead
      to `Drafted`; re-running does not re-draft it; no code path auto-advances to `Sent`.
- [ ] Re-running stage 7 immediately produces zero new lead rows (dedup holds).
- [ ] Digest renders `valid`, `accept_all`, and no-email rows in their distinct correct forms.
- [ ] A lead whose coregent record is `is_recruiter_like` is never labeled `hiring_manager` and is
      never used as prong 2's target.
- [ ] For a job with a matched lead, the cold-email draft contains a real hiring-manager line (not
      a bare `- ` bullet) and the job row's `Hiring Manager LinkedIn` is populated.
