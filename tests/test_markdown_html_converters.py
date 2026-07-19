"""
Phase 1 — unit tests for the pure, AI-independent markdown→HTML regex converters:
stage5_interview_prep.render_html and stage6_negotiate.render_brief.

Includes tests for consecutive `<li>` lines being wrapped in `<ul>`/`</ul>` (formerly a
documented gap in docs/backlog/step-9-evals-testing.md's non-goals — fixed via
scripts/utils.wrap_consecutive_li).
"""
from scripts import stage5_interview_prep as stage5
from scripts import stage6_negotiate as stage6


JOB = {"company": "Acme Corp", "title": "Senior Backend Engineer", "url": "https://example.com/job"}


# ── stage5_interview_prep.render_html ──────────────────────────────────────

def test_render_html_converts_h2_and_h3():
    html = stage5.render_html("## Section One\n### Subsection", JOB)
    assert "<h2>Section One</h2>" in html
    assert "<h3>Subsection</h3>" in html


def test_render_html_converts_bullet_lines_to_li():
    html = stage5.render_html("* First point\n- Second point", JOB)
    assert "<li>First point</li>" in html
    assert "<li>Second point</li>" in html


def test_render_html_converts_bold():
    html = stage5.render_html("This is **important** advice.", JOB)
    assert "<strong>important</strong>" in html


def test_render_html_paragraph_break_becomes_p_tags():
    html = stage5.render_html("First paragraph.\n\nSecond paragraph.", JOB)
    assert "First paragraph.</p><p>Second paragraph." in html


def test_render_html_includes_job_metadata():
    html = stage5.render_html("Some content", JOB)
    assert "Acme Corp" in html
    assert "Senior Backend Engineer" in html
    assert JOB["url"] in html


def test_render_html_wraps_consecutive_li_in_ul():
    html = stage5.render_html("* First\n* Second", JOB)
    assert "<li>First</li>" in html
    assert "<li>Second</li>" in html
    assert "<ul>" in html
    assert "</ul>" in html
    # both bullets share a single enclosing <ul>, not one each
    assert html.count("<ul>") == 1


# ── stage6_negotiate.render_brief ──────────────────────────────────────────

def test_render_brief_converts_h2_and_dash_bullets():
    html = stage6.render_brief("## Benchmarks\n- P50: $180k", "Acme Corp", "Senior PM", 180000.0)
    assert "<h2>Benchmarks</h2>" in html
    assert "<li>P50: $180k</li>" in html


def test_render_brief_converts_bold():
    html = stage6.render_brief("Target **$200,000** base.", "Acme Corp", "Senior PM", 180000.0)
    assert "<strong>$200,000</strong>" in html


def test_render_brief_includes_offer_and_company():
    html = stage6.render_brief("content", "Acme Corp", "Senior PM", 180000.0)
    assert "Acme Corp" in html
    assert "Senior PM" in html
    assert "$180,000" in html


def test_render_brief_characterization_asterisk_bullets_not_converted():
    # Known inconsistency (documented, not fixed): unlike stage5's render_html, render_brief
    # only handles "- " bullets, not "* " ones — a "* " line passes through as plain text.
    html = stage6.render_brief("* Not converted", "Acme Corp", "Senior PM", 180000.0)
    assert "<li>Not converted</li>" not in html
    assert "* Not converted" in html


def test_render_brief_wraps_consecutive_li_in_ul():
    html = stage6.render_brief("- First\n- Second", "Acme Corp", "Senior PM", 180000.0)
    assert "<li>First</li>" in html
    assert "<li>Second</li>" in html
    assert "<ul>" in html
    assert html.count("<ul>") == 1
