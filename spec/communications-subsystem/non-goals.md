# Non-goals

- **Any automated sending/connecting.** The human-approval gate is non-negotiable per the
  governing rule; do not build a "Sent" auto-transition even as a future toggle.
- **Scaling Mode B (discovery via `TARGET_ROLES × TARGET_COMPANIES`) beyond weekly cadence.** Real
  cost (~$9/mo) — keep opt-in and infrequent.
- **Using Hunter Domain Search merely to resolve a domain.** It bills per email returned — it's a
  person-discovery tool for prong 2's hiring-manager search, not a domain resolver.
- **Ever constructing an email address from Hunter's `pattern` field.** Display-only; zero code
  path to the `Email` property.
- **Guessing a company domain when the resolution chain fails.** No domain → no Email Finder call
  → LinkedIn fallback + "no verified email" flag, never a guess.
