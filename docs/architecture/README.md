# Architecture Analysis — how to use these files

A comprehensive Low-Level Design (LLD), Entity-Relationship (ERD), and component-design analysis of
the AI Job Search Pipeline across three change horizons: **`main`** (baseline) → **`feat/maverick`**
(advancements) → **`refinement-plans/`** (proposed future). Contains ~21 professional diagrams
(system context, component/container, ERD, pipeline flow, sequence, state machine, roadmap DAG, Gantt).

## Files

| File | What it is |
|---|---|
| **`architecture-analysis.md`** | The canonical document (Mermaid diagrams as fenced code). Edit this. |
| **`architecture-analysis.html`** | Self-contained rendered report — open in a browser; **print to PDF**. Generated from the `.md`. |
| **`build_report.py`** | Regenerates the HTML from the `.md`. Run after any edit. |
| **`job-status-flow.md`** | Standalone reference: every Notion `Status` value, in flow order, with which stage (or human) moves a job between them. Not part of the generated report — edit directly. |

## View it / export to PDF

1. Open `architecture-analysis.html` in any browser (double-click, or serve the folder).
2. All diagrams render inline (Mermaid + marked.js load from CDN — internet required on first open).
3. To export: **`Ctrl/Cmd + P` → Save as PDF**. Print styles paginate each section and hide the nav.

## Import to Confluence / Notion

Paste `architecture-analysis.md`:
- **Confluence** renders the ` ```mermaid ` blocks via the *Mermaid Diagrams for Confluence* macro.
- **Notion** renders them in a `mermaid` code block.
- **GitHub / GitLab / VS Code** render them natively.

## Regenerate after editing

```bash
python docs/architecture/build_report.py
```

The Markdown is base64-embedded into the HTML, so the two never drift — always edit the `.md` and rebuild.

## Legend

🟦 `main` · 🟪 `feat/maverick` · 🟩 `refinement-plans` · cylinders = datastores · diamonds = gates/decisions · ⚠️ = a defect cited to `file:line`.
