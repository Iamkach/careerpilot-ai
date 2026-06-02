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

from pathlib import Path

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
