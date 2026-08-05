# End goal

Once this ships: every job that reaches `Reviewed` automatically gets its LinkedIn-visible poster/
recruiter/hiring-manager captured as a durable Lead in a new Notion Leads DB (prong 1, near-zero
marginal cost — the data rides an actor swap already in place). Separately, a small, budget-capped
queue of top-ATS jobs gets a **verified** professional email resolved via Hunter.io for the
highest-ranked contact (prong 2, ~1 person/day given the free tier).

For both prongs: the AI only ranks who's worth contacting and drafts outreach prose — it never
invents a name, title, email, or domain. A human reviews every draft in Notion and must explicitly
set `Approved` before anything is drafted for send; nothing auto-advances past that gate, and
nothing is ever auto-sent or auto-connected. The whole subsystem runs unattended on a GitHub
Actions schedule, with drafts landing durably in the Notion lead page body (not just a
run-artifact that disappears with the ephemeral runner).
