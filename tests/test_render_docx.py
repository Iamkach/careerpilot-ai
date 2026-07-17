"""
Phase 2 — golden-file tests for scripts/render_docx.py's extract_docx_text / apply_docx_edits.

No AI call happens in this module — the AI only produces the {old, new} edit list upstream in
stage 2 — so its I/O is fully deterministic given the fixture .docx, making it a strong
golden-file/snapshot-testing target. The fixture itself is built in code by
tests/fixtures/build_fixture_docx.py (see `fixture_docx_path` in conftest.py) rather than
committed as an opaque binary, so its exact structure stays reviewable in a diff.
"""
from scripts.render_docx import extract_docx_text, apply_docx_edits


# ── extract_docx_text ────────────────────────────────────────────────────

def test_extract_docx_text_exact_expected_lines(fixture_docx_path):
    text = extract_docx_text(str(fixture_docx_path))
    assert text == (
        "Krishna Achyuth\n"
        "Senior Software Engineer\n"
        "Summary: Experienced backend engineer with strong AWS skills.\n"
        "Led critical system migrations.\n"
        "Skilled in Python and Java."
    )


def test_extract_docx_text_skips_blank_paragraphs(fixture_docx_path):
    # The fixture has a blank paragraph between the title lines and the summary — it must
    # not produce an empty line or extra blank entry in the joined output.
    text = extract_docx_text(str(fixture_docx_path))
    assert "\n\n" not in text


# ── apply_docx_edits — happy path ───────────────────────────────────────

def test_apply_docx_edits_applies_clean_non_overlapping_edits(fixture_docx_path, tmp_path):
    out_path = tmp_path / "edited.docx"
    edits = [
        {"old": "Senior Software Engineer", "new": "Staff Software Engineer"},
        {"old": "AWS skills", "new": "AWS and GCP skills"},
    ]
    result_path, unmatched = apply_docx_edits(str(fixture_docx_path), edits, str(out_path))

    assert result_path == str(out_path)
    assert unmatched == []
    text = extract_docx_text(str(out_path))
    assert "Staff Software Engineer" in text
    assert "Senior Software Engineer" not in text
    assert "AWS and GCP skills" in text


def test_apply_docx_edits_only_touches_the_matched_paragraph(fixture_docx_path, tmp_path):
    # The real requirement behind apply_docx_edits: a targeted ATS keyword edit must land
    # only in the one paragraph it's meant for and leave every other paragraph byte-for-byte
    # unchanged — a tailoring run touching unrelated resume content would be a real bug.
    out_path = tmp_path / "edited.docx"
    before = extract_docx_text(str(fixture_docx_path)).splitlines()

    apply_docx_edits(str(fixture_docx_path),
                      [{"old": "Senior Software Engineer", "new": "Staff Software Engineer"}],
                      str(out_path))

    after = extract_docx_text(str(out_path)).splitlines()
    assert len(after) == len(before)
    changed = [i for i, (b, a) in enumerate(zip(before, after)) if b != a]
    assert changed == [1]  # only the "Senior Software Engineer" line (index 1) changed
    assert after[1] == "Staff Software Engineer"


def test_apply_docx_edits_ignores_noop_and_blank_edits(fixture_docx_path, tmp_path):
    out_path = tmp_path / "edited.docx"
    edits = [
        {"old": "Krishna Achyuth", "new": "Krishna Achyuth"},  # no-op: old == new
        {"old": "", "new": "should be ignored"},               # blank old
        {"old": "should be ignored too", "new": ""},            # blank new
    ]
    _, unmatched = apply_docx_edits(str(fixture_docx_path), edits, str(out_path))
    # None of these are even attempted, so none show up as unmatched either.
    assert unmatched == []
    assert extract_docx_text(str(out_path)) == extract_docx_text(str(fixture_docx_path))


def test_apply_docx_edits_unmatched_edit_is_reported_not_silently_dropped(fixture_docx_path, tmp_path):
    out_path = tmp_path / "edited.docx"
    edits = [
        {"old": "text that does not appear anywhere", "new": "replacement"},
    ]
    _, unmatched = apply_docx_edits(str(fixture_docx_path), edits, str(out_path))

    assert len(unmatched) == 1
    assert unmatched[0]["old"] == "text that does not appear anywhere"


def test_apply_docx_edits_writes_core_properties(fixture_docx_path, tmp_path):
    from docx import Document
    out_path = tmp_path / "edited.docx"
    job = {"title": "Senior Backend Engineer", "company": "Acme Corp"}

    apply_docx_edits(str(fixture_docx_path), [], str(out_path), job=job)

    props = Document(str(out_path)).core_properties
    assert "Senior Backend Engineer" in props.title
    assert props.subject == "Senior Backend Engineer"
    assert props.keywords == "Senior Backend Engineer, Acme Corp"


def test_apply_docx_edits_core_properties_fallback_without_job(fixture_docx_path, tmp_path):
    from docx import Document
    out_path = tmp_path / "edited.docx"

    apply_docx_edits(str(fixture_docx_path), [], str(out_path), job=None)

    props = Document(str(out_path)).core_properties
    assert props.subject == ""
    assert props.keywords == ""


# ── apply_docx_edits — documented characterization tests (not fixes) ───

def test_characterization_run_collapsing_loses_formatting_on_rest_of_paragraph(fixture_docx_path, tmp_path):
    """Known gap: a partial-paragraph edit collapses all runs in that paragraph into the
    first run's style, losing run-level formatting (e.g. bold) on the rest of the paragraph.
    Locks in today's behavior — not a fix."""
    from docx import Document
    out_path = tmp_path / "edited.docx"
    edits = [{"old": "critical", "new": "highly critical and complex"}]

    apply_docx_edits(str(fixture_docx_path), edits, str(out_path))

    doc = Document(str(out_path))
    edited_para = next(p for p in doc.paragraphs if "highly critical and complex" in p.text)
    assert edited_para.text == "Led highly critical and complex system migrations."
    # Everything landed in the first run, which was never bold — the word "critical" was
    # bold in the fixture, but that formatting is gone from the merged text.
    assert len(edited_para.runs) >= 1
    assert edited_para.runs[0].text == "Led highly critical and complex system migrations."
    assert not edited_para.runs[0].bold


def test_characterization_same_paragraph_double_edit_clobber(fixture_docx_path, tmp_path):
    """Known gap: two edits in the same paragraph are applied sequentially against the
    paragraph's *current* (already-edited) text, not the original. If the first edit's `new`
    text happens to reintroduce the second edit's `old` substring earlier in the paragraph,
    the second edit clobbers the wrong occurrence instead of the one it was meant for.

    Fixture paragraph: "Skilled in Python and Java."
      Edit A: old="Python", new="Java"   → "Skilled in Java and Java."
      Edit B: old="Java",   new="Kotlin" → replaces the FIRST "Java" (the one edit A just
              introduced), not the original second one.
    Result: "Skilled in Kotlin and Java." — the original "Java" survives untouched, and the
    text edit A introduced gets clobbered by edit B instead. Locks in today's behavior."""
    out_path = tmp_path / "edited.docx"
    edits = [
        {"old": "Python", "new": "Java"},
        {"old": "Java", "new": "Kotlin"},
    ]

    apply_docx_edits(str(fixture_docx_path), edits, str(out_path))

    text = extract_docx_text(str(out_path))
    assert "Skilled in Kotlin and Java." in text
