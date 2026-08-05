# End goal

Cut the ~20 min/application spent in the browser, for **new inbound jobs only**. Not backlog
drainage — the 450 existing actionable rows are explicitly out of scope.

Once this ships, the human experience is: open the side panel, pick a ready job from the list, the
extension opens that job's real apply page and already knows which Notion row it belongs to. The
panel shows which fields are `ready` (answer resolved), which are `review_required`, and which are
permanently read-only (LinkedIn/Indeed). One click attaches the correct tailored resume, verified
by reading the file input back rather than assumed. One click fills every `ready` field. Free-text
essay questions get an AI-drafted starting point the human edits and inserts themselves, field by
field. After the human reviews and clicks the form's own Submit button, one more explicit click in
the panel records `Applied` in Notion with an audit trail proving a human made the claim.

Every answer-resolution decision still lives in Python (`build_application_plan()`,
`readiness_report()`, `_resolve_field()`) — the extension is a thin DOM client, never a second
place where eligibility/salary/sponsorship logic could drift from the CLI path.

Ashby, Workday, and arbitrary custom career sites — none of which the Playwright layer can reach —
become reachable through this one code path, because the live DOM is the schema and the human is
already past auth and captcha.
