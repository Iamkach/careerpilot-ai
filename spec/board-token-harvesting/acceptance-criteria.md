# Acceptance criteria

- [ ] `parse_board_url()` correctly parses all three Greenhouse URL shapes, Lever, and Ashby, and
      returns `None` on lookalike hosts (`evilgreenhouse.io`, `notlever.co`, a lever.co substring
      buried in a query string).
- [ ] `harvest_board_tokens()` marks a board-sourced job's own token `provenance: "observed"`.
- [ ] An observed token is never overwritten by a subsequent guess; a guess is overwritten by a
      later observation.
- [ ] A Greenhouse observation whose `_probe_greenhouse()` confirmation fails is **not** written.
- [ ] `discover_tokens()` skips an `"observed"` entry even when `checked` is more than 30 days old.
- [ ] Existing cache entries with no `provenance` key behave exactly as before this change
      (read as `"guessed"`).
- [ ] After a real `python run.py --stage 1` run, a diff of `config/ats_tokens.json` shows new
      `provenance: "observed"` entries and zero downgrades of any previously-observed token.
- [ ] A newly-observed company's token is skipped on the next `discover_tokens()` re-probe pass.
