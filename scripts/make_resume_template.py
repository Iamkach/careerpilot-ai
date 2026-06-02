#!/usr/bin/env python3
"""
make_resume_template.py — generate a starter resume_template.docx
──────────────────────────────────────────────────────────────────
Builds a clean, single-column Word template with the docxtpl/Jinja2
placeholders that stage 2 fills in. This is a REFERENCE/starter — open
the result in Word and restyle fonts, colours, and spacing however you
like. As long as you keep the {{ ... }} / {% ... %} tags, tailoring will
keep working and every tailored resume will share this exact layout.

Run:  python scripts/make_resume_template.py
      python scripts/make_resume_template.py --out config/resume_template.docx
"""

import argparse
from pathlib import Path


def build_template(out_path: str) -> str:
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Header — name + contact line
    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = name.add_run("{{ name }}")
    run.bold = True
    run.font.size = Pt(20)

    contact = doc.add_paragraph()
    contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact.add_run("{{ contact }}").font.size = Pt(10)

    # Summary
    doc.add_heading("SUMMARY", level=1)
    doc.add_paragraph("{{ summary }}")

    # Skills — inline, bullet-separated
    doc.add_heading("SKILLS", level=1)
    doc.add_paragraph(
        "{% for s in skills %}{{ s }}{% if not loop.last %} • {% endif %}{% endfor %}"
    )

    # Experience — repeat block per role
    doc.add_heading("EXPERIENCE", level=1)
    exp = doc.add_paragraph()
    exp.add_run("{% for job in experience %}")
    role = doc.add_paragraph()
    role.add_run("{{ job.company }} | {{ job.title }} | {{ job.dates }}").bold = True
    doc.add_paragraph("{% for b in job.bullets %}", style=None)
    doc.add_paragraph("{{ b }}", style="List Bullet")
    doc.add_paragraph("{% endfor %}")
    doc.add_paragraph("{% endfor %}")

    # Education — repeat block
    doc.add_heading("EDUCATION", level=1)
    doc.add_paragraph("{% for ed in education %}")
    doc.add_paragraph("{{ ed.institution }} | {{ ed.degree }} | {{ ed.year }}")
    doc.add_paragraph("{% endfor %}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="config/resume_template.docx",
                        help="Where to write the template .docx")
    args = parser.parse_args()
    path = build_template(args.out)
    print(f"[OK] Wrote starter template: {path}")
    print("  Open it in Word to restyle. Keep the {{ }} / {% %} tags intact.")
