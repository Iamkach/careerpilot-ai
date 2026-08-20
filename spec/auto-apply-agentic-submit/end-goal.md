# End goal

A job at `Resume Tailored` can reach `Applied` with zero human interaction whenever every required
field on the live application resolves — either from Layer 1's deterministic plan or from the
agent locating and filling it on the page — and the application is confirmed submitted by an
observed post-submit signal on the page itself.

The agent can navigate multi-step application flows, locate fields Layer 1's static schema never
saw (schema-unknown channels like Lever/Ashby, or a live DOM structure that diverges from the
public schema), and recover from a partial resolution by adapting instead of drift-aborting.

Eligibility, sponsorship, salary, and any yes/no legal-eligibility question are answered *only*
from `APPLICATION_PROFILE`/`EEO_RESPONSES` or block — this is true after this feature ships
exactly as it is true today, provably so by the shape of the tool the agent must call for those
answers (no free-form value parameter exists), not by anything the agent is told not to do.

A job the agent cannot fully resolve does not dead-end silently in a state only a human would
think to check — it requeues itself automatically, bounded by an attempts ceiling, and only
becomes a terminal human-review item once that ceiling is exhausted.

`Applied` in Notion means the same thing it means today — a real, observed confirmation that the
application was received — regardless of which of the (now three) paths set it.
