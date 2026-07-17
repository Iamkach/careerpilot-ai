"""
scripts/run_evals.py — Step 9 Phase 5: AI-quality eval layer.

Standalone, opt-in, and deliberately OUTSIDE run.py's pipeline entry point — never invoked by
`run.py`, `--evaluate`, `nightly-pipeline.yml`, or `tests.yml`. Phases 0-4's pytest suite proves
the *plumbing* is correct against recorded/mocked AI responses; this script hits the **real**
Anthropic API against a small hand-labeled dataset to catch drift in the AI's actual *judgment*
(scoring accuracy, keyword recall, tailoring lift) — something a mocked contract test cannot see
by construction. Run manually before/after a prompt or QUALITY_MODEL/AI_MODEL_OVERRIDE change.

Usage:
    python scripts/run_evals.py                  # stage 1 scoring + keyword recall only
    python scripts/run_evals.py --tailor          # also run stage 2 tailoring + ATS delta
    python scripts/run_evals.py --comp-check      # also print a stage 6 negotiation-brief
                                                   # sample for manual eyeballing (see note below)
    python scripts/run_evals.py --dataset path.json --out path.json

Requires a real AI_PROVIDER configured in config/settings.py / .env (ANTHROPIC_API_KEY for the
default "claude" provider, or a logged-in Claude Code session for "claude_code"). Costs real
tokens — this is why it is not part of tests.yml.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils import load_resume, log  # noqa: E402
from scripts.stage1_scrape import score_jobs_batch  # noqa: E402
from scripts.stage2_tailor import _tailor_resume_single, verify_tailored_score  # noqa: E402

DEFAULT_DATASET = ROOT / "tests" / "eval_data" / "jobs.json"
DEFAULT_OUT_DIR = ROOT / "output" / "evals"

# Jobs whose description is intentionally empty/garbled — observational only, excluded from the
# score-hit-rate and keyword-recall aggregates (their expected_score range spans 0-100 by design
# and would otherwise silently inflate the hit rate).
_OBSERVATIONAL_ONLY = {"empty-description", "garbled-description"}


def _load_dataset(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _keyword_recall(expected: list[str], predicted: list[str]) -> tuple[int, int, list[str]]:
    """Fuzzy, case-insensitive substring match in either direction — an expected keyword
    counts as found if it's a substring of (or contains) any predicted missing_keyword. Real
    model phrasing varies ("RAG" vs "RAG pipelines"), so exact-match recall would understate
    quality most of what this eval is trying to measure."""
    if not expected:
        return 0, 0, []
    pred_lower = [p.lower() for p in predicted]
    missed = []
    hits = 0
    for kw in expected:
        kw_l = kw.lower()
        if any(kw_l in p or p in kw_l for p in pred_lower):
            hits += 1
        else:
            missed.append(kw)
    return hits, len(expected), missed


def _apply_edits_to_text(resume_text: str, edits: list[dict]) -> str:
    """Approximate the tailored resume as plain text via naive verbatim replacement, mirroring
    apply_docx_edits' first-occurrence-per-edit semantics without touching the .docx machinery
    (Phase 2 already golden-file-tests the real docx path) — good enough for a re-score."""
    text = resume_text
    for e in edits:
        old, new = e.get("old", ""), e.get("new", "")
        if old and old in text:
            text = text.replace(old, new, 1)
    return text


def run_scoring_eval(dataset: list[dict], resume: str) -> dict:
    log(f"Scoring {len(dataset)} labeled jobs against the real API...")
    jobs = [{"url": j["url"], "title": j["title"], "company": j["company"],
              "description": j["description"]} for j in dataset]
    results = score_jobs_batch(jobs, resume)
    by_url = {r["url"]: r for r in results}

    rows = []
    scored_for_agg = []
    for job in dataset:
        r = by_url.get(job["url"], {})
        score = r.get("score")
        scored = r.get("scored", False)
        observational = job["id"] in _OBSERVATIONAL_ONLY
        in_range = (
            scored and score is not None
            and job["expected_score_min"] <= score <= job["expected_score_max"]
        )
        kw_hits, kw_total, kw_missed = _keyword_recall(
            job.get("expected_missing_keywords", []), r.get("missing_keywords", [])
        )
        row = {
            "id": job["id"],
            "company": job["company"],
            "scored": scored,
            "score": score,
            "expected_range": [job["expected_score_min"], job["expected_score_max"]],
            "in_expected_range": in_range,
            "sponsorship": r.get("sponsorship"),
            "expected_sponsorship": job.get("expected_sponsorship"),
            "sponsorship_match": r.get("sponsorship") == job.get("expected_sponsorship"),
            "company_type": r.get("company_type"),
            "expected_company_type": job.get("expected_company_type"),
            "company_type_match": r.get("company_type") == job.get("expected_company_type"),
            "keyword_recall": f"{kw_hits}/{kw_total}" if kw_total else "n/a",
            "missed_keywords": kw_missed,
            "observational_only": observational,
        }
        rows.append(row)
        if not observational:
            scored_for_agg.append(row)

    n = len(scored_for_agg)
    score_hits = sum(1 for r in scored_for_agg if r["in_expected_range"])
    sponsor_hits = sum(1 for r in scored_for_agg if r["sponsorship_match"])
    type_hits = sum(1 for r in scored_for_agg if r["company_type_match"])
    total_kw_hits = sum(
        int(r["keyword_recall"].split("/")[0]) for r in scored_for_agg if r["keyword_recall"] != "n/a"
    )
    total_kw_expected = sum(
        int(r["keyword_recall"].split("/")[1]) for r in scored_for_agg if r["keyword_recall"] != "n/a"
    )

    summary = {
        "score_hit_rate": f"{score_hits}/{n}" if n else "n/a",
        "sponsorship_hit_rate": f"{sponsor_hits}/{n}" if n else "n/a",
        "company_type_hit_rate": f"{type_hits}/{n}" if n else "n/a",
        "keyword_recall_overall": f"{total_kw_hits}/{total_kw_expected}" if total_kw_expected else "n/a",
    }
    return {"rows": rows, "summary": summary}


def run_tailor_eval(dataset: list[dict], resume: str, scoring_rows: list[dict]) -> dict:
    """Tailor + re-score each labeled job (skipping observational-only entries), reusing the
    stage 1 score already computed as the 'before' value so this doesn't re-spend a call."""
    before_by_id = {r["id"]: r["score"] for r in scoring_rows}
    rows = []
    deltas = []
    for job in dataset:
        if job["id"] in _OBSERVATIONAL_ONLY:
            continue
        before = before_by_id.get(job["id"])
        log(f"Tailoring: {job['id']}...")
        job_dict = {"url": job["url"], "title": job["title"], "company": job["company"],
                    "missing_keywords": job.get("expected_missing_keywords", [])}
        edits, keywords_injected = _tailor_resume_single(resume, job["description"], job_dict)
        tailored_text = _apply_edits_to_text(resume, edits)
        after_result = verify_tailored_score(tailored_text, job["description"], job_dict)
        after = after_result.get("score")
        delta = (after - before) if (before is not None and after is not None) else None
        if delta is not None:
            deltas.append(delta)
        rows.append({
            "id": job["id"],
            "company": job["company"],
            "before": before,
            "after": after,
            "delta": delta,
            "num_edits": len(edits),
            "keywords_injected": keywords_injected,
        })
    avg_delta = round(sum(deltas) / len(deltas), 1) if deltas else None
    return {"rows": rows, "summary": {"avg_ats_delta": avg_delta, "n": len(deltas)}}


def run_comp_check() -> None:
    """Not a scored eval — the source plan (docs/refinement-plans/testing/evals-strategy.md,
    Phase 5) flags that generate_negotiation_brief's prompt claims 'Claude + web search' in its
    module docstring but never calls an actual search tool, so its comp-benchmark numbers come
    from the model's own training knowledge and can go stale silently. This prints one sample
    brief for a human to eyeball for staleness/plausibility — there's no fixed oracle to assert
    against, so it's deliberately not part of the pass/fail summary."""
    from scripts.stage6_negotiate import generate_negotiation_brief
    log("Generating a sample negotiation brief for manual review "
        "(comp data staleness has no automated oracle — eyeball this)...")
    brief = generate_negotiation_brief(
        company="Stripe", role="Senior Software Engineer", city="San Francisco, CA", offer=185000
    )
    print("\n" + "=" * 70)
    print("STAGE 6 COMP-BENCHMARK SAMPLE (manual review only, not scored)")
    print("=" * 70)
    print(brief)
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=None,
                         help="Where to write the JSON report (default: output/evals/<timestamp>.json)")
    parser.add_argument("--tailor", action="store_true", help="Also run stage 2 tailoring + ATS delta")
    parser.add_argument("--comp-check", action="store_true",
                         help="Also print a stage 6 negotiation-brief sample for manual review")
    args = parser.parse_args()

    dataset = _load_dataset(args.dataset)
    resume = load_resume()

    scoring = run_scoring_eval(dataset, resume)
    report = {"dataset": str(args.dataset), "scoring": scoring}

    print("\n--- Stage 1 scoring eval ---")
    for row in scoring["rows"]:
        flag = "  (observational)" if row["observational_only"] else ""
        print(f"  [{'OK ' if row['in_expected_range'] or row['observational_only'] else 'MISS'}] "
              f"{row['id']}: score={row['score']} expected={row['expected_range']} "
              f"kw_recall={row['keyword_recall']} sponsorship={row['sponsorship']}"
              f"({'match' if row['sponsorship_match'] else 'mismatch'}){flag}")
    print(f"\nSummary: {scoring['summary']}")

    if args.tailor:
        tailoring = run_tailor_eval(dataset, resume, scoring["rows"])
        report["tailoring"] = tailoring
        print("\n--- Stage 2 tailoring eval ---")
        for row in tailoring["rows"]:
            print(f"  {row['id']}: {row['before']} -> {row['after']} "
                  f"(delta={row['delta']}, {row['num_edits']} edits)")
        print(f"\nSummary: {tailoring['summary']}")

    if args.comp_check:
        run_comp_check()

    out_path = args.out
    if out_path is None:
        DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
        from scripts.utils import today
        out_path = DEFAULT_OUT_DIR / f"eval_{today()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
