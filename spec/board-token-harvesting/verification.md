# Verification

1. `pytest -v` green, including `tests/test_sources_board_harvest.py`. No API keys, no network.
2. Back up `config/ats_tokens.json`, run `python run.py --stage 1`, then diff: new/changed entries
   should carry `provenance: "observed"`, and no existing token should be downgraded to a guess.
3. Confirm the log line reports a non-zero harvest count (expected: small — self-confirmation of
   already-successful guesses among board-sourced jobs, not new companies), and that a
   newly-observed company's token is skipped on the next `discover_tokens()` re-probe pass.
4. Re-measure the cache after ~5 nightly runs. This phase does **not** move the 23/100 baseline by
   itself — track `provenance: "observed"` count as its own number, separate from total hit count.
