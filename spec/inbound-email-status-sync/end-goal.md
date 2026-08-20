# End goal

Once this ships: the tracker stops going silent after Submit. Every in-flight job (`Applied`,
`Outreach Sent`, `Interview Scheduled`) gets its inbox watched automatically; a matching reply is
classified and, for a small high-confidence unambiguous subset (single-candidate match, confidence
at/above threshold, a signal that maps to a forward-only status), the Notion `Status` updates
itself — `Rejected`, `Interview Scheduled`, or `Offer Received`. Every match, written or not, leaves
a visible audit trail in the job's Notion page body so the human can see *why*, even when nothing
changed.

The human still combs their own inbox less, but the system never silently closes a job that's
still alive — the write policy is deliberately narrower than the classification itself, and there
is no code path that ever regresses a status backward.
