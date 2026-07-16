#!/usr/bin/env python3
"""
render_docx.py — render a tailored resume into a .docx template
────────────────────────────────────────────────────────────────
Given structured resume data (a dict) and a Word template that uses
docxtpl / Jinja2 placeholders, produce a formatted .docx. The template
owns ALL formatting (fonts, spacing, colours) so every tailored resume
looks identical — only the content changes per job.

Expected `data` schema (see RESUME_SCHEMA_DOC below):
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
    """Replace old with new inside a paragraph, collapsing runs into the first one.

    Paragraph-level formatting (indent, bullet style, spacing) is preserved.
    Run-level formatting within the paragraph is collapsed to the first run's style —
    acceptable for resume bullets where a whole bullet shares the same style.
    """
    full = para.text.replace(old, new, 1)
    if para.runs:
        para.runs[0].text = full
        for run in para.runs[1:]:
            run.text = ""
    else:
        para.add_run(full)


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
