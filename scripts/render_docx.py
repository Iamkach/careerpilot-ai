#!/usr/bin/env python3
"""
render_docx.py — in-place .docx text edits for tailored resumes
────────────────────────────────────────────────────────────────
Primary role today: `extract_docx_text()` / `apply_docx_edits()` apply targeted
`{old → new}` text replacements directly to a copy of the base resume `.docx`
(`RESUME_TEMPLATE_PATH`, default `config/Achyuth_Resume.docx`) via python-docx,
preserving the original document's formatting (fonts, spacing, run-level
bold/italic, ...) — this is the default flow stage 2 uses.

`render_resume_docx()` below is a legacy Jinja2/docxtpl template-render path
(paired with `scripts/make_resume_template.py`'s scaffolded
`config/resume_template.docx`) kept for reference but no longer used by the
default flow; it requires the optional `docxtpl` package to be installed
separately.

Expected `data` schema for `render_resume_docx()` (see RESUME_SCHEMA_DOC below):
    {
      "name": str,
      "contact": str,                 # single contact line
      "summary": str,
      "skills": [str, ...],
      "experience": [
        {"company": str, "title": str, "dates": str, "bullets": [str, ...]}
      ],
      "education": [
        {"institution": str, "degree": str, "year": str}
      ]
    }

Template placeholders (Jinja2 syntax inside the .docx):
    {{ name }}
    {{ contact }}
    {{ summary }}
    Skills line: {% for s in skills %}{{ s }}{% if not loop.last %} • {% endif %}{% endfor %}
    Experience: {% for job in experience %} ... {{ job.company }} | {{ job.title }} | {{ job.dates }}
                {% for b in job.bullets %}{{ b }}{% endfor %} ... {% endfor %}
    Education:  {% for ed in education %}{{ ed.institution }} | {{ ed.degree }} | {{ ed.year }}{% endfor %}
"""

import shutil
from pathlib import Path

from config.settings import YOUR_NAME

# Human-readable reference of the placeholders a template must use.
RESUME_SCHEMA_DOC = """\
Your config/resume_template.docx should contain these docxtpl (Jinja2) tags:

  {{ name }}                 — full name (header)
  {{ contact }}              — single contact line (email | linkedin | location)
  {{ summary }}              — professional summary paragraph

  Skills (inline, bullet-separated):
    {% for s in skills %}{{ s }}{% if not loop.last %} • {% endif %}{% endfor %}

  Experience (repeat block per role):
    {% for job in experience %}
    {{ job.company }} | {{ job.title }} | {{ job.dates }}
    {% for b in job.bullets %}
    {{ b }}
    {% endfor %}
    {% endfor %}

  Education (repeat block):
    {% for ed in education %}
    {{ ed.institution }} | {{ ed.degree }} | {{ ed.year }}
    {% endfor %}
"""

_REQUIRED_KEYS = ("name", "contact", "summary", "skills", "experience", "education")


def normalize_resume_data(data: dict) -> dict:
    """Fill in missing keys with safe empties so the template never crashes."""
    out = {
        "name": str(data.get("name", "") or ""),
        "contact": str(data.get("contact", "") or ""),
        "summary": str(data.get("summary", "") or ""),
        "skills": list(data.get("skills", []) or []),
        "experience": [],
        "education": [],
    }
    for job in data.get("experience", []) or []:
        out["experience"].append({
            "company": str(job.get("company", "") or ""),
            "title":   str(job.get("title", "") or ""),
            "dates":   str(job.get("dates", "") or ""),
            "bullets": list(job.get("bullets", []) or []),
        })
    for ed in data.get("education", []) or []:
        out["education"].append({
            "institution": str(ed.get("institution", "") or ""),
            "degree":      str(ed.get("degree", "") or ""),
            "year":        str(ed.get("year", "") or ""),
        })
    return out


def render_resume_docx(data: dict, template_path: str, out_path: str) -> str:
    """Render `data` into `template_path` and write the result to `out_path`.

    Raises FileNotFoundError if the template is missing, with guidance on
    the placeholders the template must contain.
    """
    try:
        from docxtpl import DocxTemplate
    except ImportError as e:
        raise ImportError(
            "docxtpl is required to render .docx resumes. "
            "Install it with: pip install docxtpl"
        ) from e

    tpl_path = Path(template_path)
    if not tpl_path.exists():
        raise FileNotFoundError(
            f"Resume template not found at {template_path}.\n\n{RESUME_SCHEMA_DOC}"
        )

    context = normalize_resume_data(data)

    doc = DocxTemplate(str(tpl_path))
    doc.render(context)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def extract_docx_text(docx_path: str) -> str:
    """Return all non-empty paragraph text from a .docx, one line per paragraph."""
    try:
        from docx import Document
    except ImportError as e:
        raise ImportError("python-docx is required. Install with: pip install python-docx") from e
    doc = Document(docx_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _replace_para_text(para, old: str, new: str) -> None:
    """Replace the first occurrence of old with new inside a paragraph, touching only the
    run(s) that overlap the matched span.

    Paragraph-level formatting (indent, bullet style, spacing) is preserved, as is each
    run's own formatting (bold, italic, ...) — a run entirely outside the matched span is
    never modified. The replacement text is written into the first run overlapping the
    match, so it inherits that run's style rather than the paragraph's first run.
    """
    runs = para.runs
    if not runs:
        para.add_run(para.text.replace(old, new, 1))
        return

    full = "".join(r.text for r in runs)
    start = full.find(old)
    if start == -1:
        # Shouldn't happen — caller already checked `old in para.text` — but fall back to
        # a whole-paragraph replace rather than silently doing nothing.
        para.runs[0].text = full.replace(old, new, 1)
        for run in para.runs[1:]:
            run.text = ""
        return
    end = start + len(old)

    pos = 0
    replaced = False
    for run in runs:
        run_start, run_end = pos, pos + len(run.text)
        pos = run_end
        if run_end <= start or run_start >= end:
            continue  # entirely outside the matched span — leave untouched
        prefix = run.text[:max(0, start - run_start)]
        suffix = run.text[max(0, end - run_start):]
        run.text = (prefix + new + suffix) if not replaced else (prefix + suffix)
        replaced = True


def apply_docx_edits(base_path: str, edits: list, out_path: str, job: dict | None = None) -> tuple[str, list]:
    """Copy base_path to out_path and apply targeted text replacements.

    edits: list of {"old": <exact existing text>, "new": <replacement text>}
    Each edit matches the first paragraph whose text contains the "old" string.

    job: optional {"title": str, "company": str} used to set per-resume docx
    core metadata (title/subject/keywords) below. When omitted, metadata still
    gets author/last_modified_by but falls back to a generic title/subject.

    Returns (out_path, unmatched_edits) — unmatched_edits lists any edit whose
    "old" text wasn't found in any paragraph, so the caller can surface it
    instead of it silently vanishing.
    """
    try:
        from docx import Document
    except ImportError as e:
        raise ImportError("python-docx is required. Install with: pip install python-docx") from e

    if not Path(base_path).exists():
        raise FileNotFoundError(
            f"Base resume not found at {base_path}. "
            "Set RESUME_TEMPLATE_PATH to an existing .docx file in config/settings.py."
        )

    shutil.copy2(base_path, out_path)
    doc = Document(out_path)

    unmatched = []
    for edit in edits:
        old = (edit.get("old") or "").strip()
        new = (edit.get("new") or "").strip()
        if not old or not new or old == new:
            continue
        for para in doc.paragraphs:
            if old in para.text:
                _replace_para_text(para, old, new)
                break
        else:
            unmatched.append(edit)

    job_title = (job or {}).get("title") or ""
    job_company = (job or {}).get("company") or ""
    props = doc.core_properties
    props.author = YOUR_NAME
    props.last_modified_by = YOUR_NAME
    props.category = "Resume"
    props.comments = ""
    props.title = f"{YOUR_NAME} - Resume" + (f" - {job_title}" if job_title else "")
    props.subject = job_title
    props.keywords = ", ".join(filter(None, [job_title, job_company]))

    doc.save(out_path)
    return out_path, unmatched


def resume_data_to_text(data: dict) -> str:
    """Flatten structured resume data into plain text (for quick review / .txt)."""
    d = normalize_resume_data(data)
    lines = [d["name"], d["contact"], ""]
    if d["summary"]:
        lines += ["SUMMARY", d["summary"], ""]
    if d["skills"]:
        lines += ["SKILLS", " • ".join(d["skills"]), ""]
    if d["experience"]:
        lines.append("EXPERIENCE")
        for job in d["experience"]:
            header = " | ".join(p for p in (job["company"], job["title"], job["dates"]) if p)
            lines.append(header)
            lines += [f"- {b}" for b in job["bullets"]]
            lines.append("")
    if d["education"]:
        lines.append("EDUCATION")
        for ed in d["education"]:
            lines.append(" | ".join(p for p in (ed["institution"], ed["degree"], ed["year"]) if p))
        lines.append("")
    return "\n".join(lines).strip() + "\n"
