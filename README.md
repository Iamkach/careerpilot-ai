# 🤖 AI Job Search Pipeline

Automated job search system using Claude API — no N8N, no VPS required.
Scrapes LinkedIn, tailors resumes, drafts outreach, preps interviews, and negotiates offers.
All tracked in your Notion database.

---

## Workflow

```mermaid
flowchart TD
    A([Your Resume\nconfig/resume.txt]) --> S1
    CFG([config/settings.py\nAI_PROVIDER + API keys]) --> S1

    subgraph S1["Stage 1 — Scrape"]
        L1[Apify LinkedIn Scraper] --> L2[Claude: ATS score vs resume]
        L2 --> L3[Notion: Status = Scraped]
    end

    S1 --> S2

    subgraph S2["Stage 2 — Tailor  --min-score N"]
        T1[Fetch Scraped jobs from Notion] --> T2[Claude: rewrite resume per JD]
        T2 --> T3[output/resumes/*.txt]
        T3 --> T4[Notion: Status = Resume Tailored]
    end

    S2 --> S3 & S4

    subgraph S3["Stage 3 — Outreach  --company X"]
        O1[Claude: cold email or warm referral] --> O2[output/outreach/*.txt]
        O2 --> O3{Human review}
        O3 -->|confirm| O4[Notion: Status = Outreach Sent]
    end

    subgraph S4["Stage 4 — Digest  --send"]
        D1[Collect ready-to-apply jobs] --> D2[output/digest_DATE.html]
        D2 -->|--send flag| D3[Gmail API → your inbox]
    end

    S2 --> S5

    subgraph S5["Stage 5 — Interview Prep  --company X --role Y"]
        I1[Claude: behavioral + technical Q&A\nSTAR frameworks + cheat sheet] --> I2[output/prep_guides/*.html]
        I2 --> I3[Notion: Status = Interview Scheduled]
    end

    S5 --> S6

    subgraph S6["Stage 6 — Negotiate  --offer N"]
        N1[Claude: market benchmarks\ncounter-offer script] --> N2[output/negotiation/*.html]
        N2 --> N3[Notion: Status = Offer Received]
    end

    style S1 fill:#e8f4fd,stroke:#4a9eda
    style S2 fill:#e8f4fd,stroke:#4a9eda
    style S3 fill:#fff3e0,stroke:#f5a623
    style S4 fill:#e8f4fd,stroke:#4a9eda
    style S5 fill:#e8f4fd,stroke:#4a9eda
    style S6 fill:#e8fce8,stroke:#27ae60
```

**Provider swap:** change `AI_PROVIDER` in `config/settings.py` to `"claude"` / `"gemini"` / `"codex"` — all stages use the same `ai_chat()` dispatcher with no other changes needed.

---

## Setup (5 minutes)

### 1. Install dependencies

Install the SDK for your chosen AI provider plus the shared dependencies:

```bash
# Claude (default)
pip install anthropic notion-client requests

# Gemini
pip install google-generativeai notion-client requests

# OpenAI / Codex
pip install openai notion-client requests
```

### 2. Add your resume
Create `config/resume.txt` and paste your full resume as plain text.

### 3. Fill in config
Open `config/settings.py` and fill in:
- `AI_PROVIDER`       — `"claude"` (default), `"gemini"`, or `"codex"`
- `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` — matching your provider
- `APIFY_API_TOKEN`   — from https://apify.com (free)
- `NOTION_API_KEY`    — from https://www.notion.so/my-integrations
  - Create an integration, give it access to your Job Search Tracker database
- Your name, email, bio, target roles, and city

### 4. Verify setup
```bash
python run.py --setup
```

---

## Daily usage

### Morning routine (run all at once)
```bash
python run.py
```
This runs: Scrape → Tailor resumes → Send digest

### Or run individual stages

| Stage | Command | What it does |
|-------|---------|--------------|
| 1 | `python run.py --stage 1` | Scrape fresh LinkedIn jobs → Notion |
| 2 | `python run.py --stage 2 --min-score 60` | AI-tailor resume per job |
| 3 | `python run.py --stage 3 --company "Stripe"` | Draft cold outreach email |
| 3 | `python run.py --stage 3 --company "Google" --contact "Jane Doe"` | Draft warm referral |
| 4 | `python run.py --stage 4` | Print morning digest to terminal |
| 4 | `python run.py --stage 4 --send` | Also email digest via Gmail |
| 5 | `python run.py --stage 5 --company "Meta" --role "Senior PM"` | Interview prep guide |
| 6 | `python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000` | Negotiation brief |

---

## Pipeline flow

```
Stage 1: Scrape
  LinkedIn (via Apify) → Claude scores ATS match → Notion "Scraped"

Stage 2: Tailor
  Notion "Scraped" → Claude rewrites resume → saved to output/resumes/ → Notion "Resume Tailored"

Stage 3: Outreach
  Notion "Resume Tailored" → Claude drafts email → saved to output/outreach/ → Notion "Outreach Sent"

Stage 4: Digest
  Notion "Resume Tailored" + not applied → HTML email digest → your inbox

Stage 5: Interview Prep
  Company + JD → Claude generates full prep guide → output/prep_guides/ → Notion "Interview Scheduled"

Stage 6: Negotiate
  Company + offer → Claude researches benchmarks + writes script → output/negotiation/ → Notion "Offer Received"
```

---

## Output files

| Folder | Contents |
|--------|----------|
| `output/resumes/` | Tailored resumes per job as `.txt` |
| `output/outreach/` | Cold + warm email drafts as `.txt` |
| `output/prep_guides/` | Interview prep as `.html` (open in browser) |
| `output/negotiation/` | Negotiation briefs as `.html` |
| `output/digest_YYYY-MM-DD.html` | Daily digest (open in browser) |

---

## Notion tracker

Your tracker is already live:
https://www.notion.so/2ac0907e693744698a1c748d37774a07

Status pipeline:
`Scraped → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received`

Scripts update status automatically at each stage.

---

## Gmail digest (optional)

To send the digest via email:
1. Create a Google Cloud project and enable the Gmail API
2. Download `credentials.json` and place it at `config/gmail_credentials.json`
3. Run `python run.py --stage 4 --send`

---

## Tips

- Run Stage 1 daily for fresh <24h postings (highest conversion)
- Use `--min-score 65` on Stage 2 to only tailor high-match jobs
- Stage 3 outreach files need your review before sending — never auto-sent
- Prep guides open as HTML — works in any browser, no install needed
- All scripts are idempotent — safe to re-run, duplicates are skipped
