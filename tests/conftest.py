"""
tests/conftest.py — Phase 0 test harness.

Provides two fake collaborators every later phase's tests build on:
  - FakeAIChat / patch_ai_chat  — a monkeypatched stand-in for ai_chat/claude_chat/
    ai_chat_blocks that returns caller-supplied canned responses instead of calling a real
    AI backend.
  - FakeNotionDB / patch_notion_db — an in-memory stand-in for the db_*()/
    get_notion_jobs_by_status() functions in scripts/utils.py, so tests never touch the real
    Notion API.

Every stage script does `from scripts.utils import db_add_job, ...` (a direct name import,
not `import scripts.utils as utils`), which binds its own module-level reference at import
time. Patching scripts.utils.db_add_job afterwards would not affect a stage module's already-
bound name — so patch_ai_chat/patch_notion_db take the *importing* module (e.g.
scripts.stage1_scrape) and patch the names there, which is where each stage actually looks
them up.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Fake ai_chat / claude_chat / ai_chat_blocks ──────────────────────────────

class FakeAIChat:
    """Callable stand-in for ai_chat/claude_chat/ai_chat_blocks.

    Records every call in `.calls` and returns responses from a queue (consumed in order,
    FIFO) or the fixed `.response` when no queue is set / the queue is exhausted. Set
    `.raises` to have every subsequent call raise that exception instead (e.g. to simulate
    AIChatError after retries are exhausted).
    """

    def __init__(self, response: str = "", responses: list[str] | None = None):
        self.response = response
        self._queue = list(responses) if responses else None
        self.raises: Exception | None = None
        self.calls: list[dict] = []

    def set_response(self, response: str):
        self.response = response
        self._queue = None

    def set_responses(self, responses: list[str]):
        self._queue = list(responses)

    def _next_response(self) -> str:
        if self._queue:
            return self._queue.pop(0)
        return self.response

    # Matches ai_chat(prompt, system="", max_tokens=4096, quality=False)
    def __call__(self, prompt: str, system: str = "", max_tokens: int = 4096,
                 quality: bool = False) -> str:
        self.calls.append({
            "prompt": prompt, "system": system, "max_tokens": max_tokens, "quality": quality,
        })
        if self.raises is not None:
            raise self.raises
        return self._next_response()

    # Matches ai_chat_blocks(blocks, system="", max_tokens=4096, quality=False)
    def blocks(self, blocks: list, system: str = "", max_tokens: int = 4096,
               quality: bool = False) -> str:
        self.calls.append({
            "blocks": blocks, "system": system, "max_tokens": max_tokens, "quality": quality,
        })
        if self.raises is not None:
            raise self.raises
        return self._next_response()


@pytest.fixture
def patch_ai_chat(monkeypatch):
    """Factory fixture: patch_ai_chat(module, response=..., responses=[...]) -> FakeAIChat.

    Patches whichever of `ai_chat`, `claude_chat`, `ai_chat_blocks` exist as attributes on
    `module` (a stage module, e.g. scripts.stage1_scrape) to a shared FakeAIChat, and returns
    that fake so the test can inspect `.calls`, queue further `.set_responses(...)`, or set
    `.raises` mid-test.
    """
    def _patch(module, response: str = "", responses: list[str] | None = None) -> FakeAIChat:
        fake = FakeAIChat(response=response, responses=responses)
        for name in ("ai_chat", "claude_chat"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, fake)
        if hasattr(module, "ai_chat_blocks"):
            monkeypatch.setattr(module, "ai_chat_blocks", fake.blocks)
        return fake
    return _patch


# ── Fake in-memory Notion layer ──────────────────────────────────────────────

class FakeNotionDB:
    """In-memory stand-in for the db_*()/get_notion_jobs_by_status() Notion helpers in
    scripts/utils.py. Stores pages as plain dicts keyed by an auto-incrementing page id, and
    mirrors the exact shapes those functions read/return so a stage under test can't tell the
    difference from the real Notion-backed versions.
    """

    def __init__(self):
        self._pages: dict[str, dict] = {}
        self._next_id = 1

    def _new_id(self) -> str:
        page_id = f"fake-page-{self._next_id}"
        self._next_id += 1
        return page_id

    @staticmethod
    def _to_page_shape(page_id: str, rec: dict) -> dict:
        """Mirror utils._page_to_job()'s output shape."""
        return {
            "page_id":          page_id,
            "id":               page_id,
            "title":            rec.get("title", ""),
            "company":          rec.get("company", ""),
            "location":         rec.get("location", ""),
            "url":              rec.get("url", ""),
            "ats":              rec.get("ats_score"),
            "ats_score":        rec.get("ats_score"),
            "resume_link":      rec.get("resume_link", ""),
            "hm":               rec.get("hiring_manager", ""),
            "hm_li":            rec.get("hiring_manager_linkedin", ""),
            "sponsorship":      rec.get("sponsorship"),
            "scoring_attempts": rec.get("scoring_attempts", 0) or 0,
            "notes":            rec.get("notes", ""),
            "missing_keywords": list(rec.get("missing_keywords") or []),
        }

    # ── seeding helper (not a real db_* function — used to set up test state) ──
    def seed(self, status: str = "Scraped", **fields) -> str:
        page_id = self._new_id()
        self._pages[page_id] = {"status": status, "description": "", **fields}
        return page_id

    # ── mirrors of scripts/utils.py's public db_* interface ──────────────────

    def db_add_job(self, job: dict) -> str:
        page_id = self._new_id()
        self._pages[page_id] = {**job, "status": job.get("status") or "Scraped"}
        return page_id

    def db_add_job_linked(self, job: dict, notion_page_id: str, status: str = "Scraped") -> str:
        rec = self._pages.setdefault(notion_page_id, {"status": status, "description": ""})
        rec.update(job)
        rec["status"] = status
        return notion_page_id

    def db_find_job_by_url(self, url: str, exclude_page_id: str = "") -> str | None:
        for page_id, rec in self._pages.items():
            if rec.get("url") == url and page_id != exclude_page_id:
                return page_id
        return None

    def db_update_status(self, job_id: str, status: str, extra_props: dict | None = None):
        rec = self._pages.setdefault(job_id, {"status": status, "description": ""})
        rec["status"] = status
        rec.update(extra_props or {})

    def db_get_ready_to_apply(self) -> list[dict]:
        rows = [
            self._to_page_shape(pid, rec) for pid, rec in self._pages.items()
            if rec.get("status") == "Resume Tailored" and not rec.get("date_applied")
        ]
        return sorted(rows, key=lambda r: r["ats_score"] or 0, reverse=True)

    def db_get_job_description(self, job_id: str) -> str:
        return self._pages.get(job_id, {}).get("description", "") or ""

    def db_get_jobs(self, status: str, min_score: float = 0) -> list[dict]:
        rows = [
            self._to_page_shape(pid, rec) for pid, rec in self._pages.items()
            if rec.get("status") == status and (rec.get("ats_score") or 0) >= min_score
        ]
        return sorted(rows, key=lambda r: r["ats_score"] or 0, reverse=True)

    def db_get_all_jobs(self) -> list[dict]:
        return [
            {
                "page_id":   pid,
                "title":     rec.get("title", ""),
                "company":   rec.get("company", ""),
                "location":  rec.get("location", ""),
                "url":       rec.get("url", ""),
                "status":    rec.get("status", ""),
                "ats_score": rec.get("ats_score") or 0,
            }
            for pid, rec in self._pages.items()
        ]

    def db_get_job_by_company(self, company: str) -> dict | None:
        for pid, rec in self._pages.items():
            if company.lower() in rec.get("company", "").lower():
                return self._to_page_shape(pid, rec)
        return None

    def get_notion_jobs_by_status(self, status: str) -> list[dict]:
        return [
            {
                "notion_page_id": pid,
                "url":            rec.get("url", ""),
                "title":          rec.get("title", ""),
                "company":        rec.get("company", ""),
                "location":       rec.get("location", ""),
            }
            for pid, rec in self._pages.items()
            if rec.get("status") == status and rec.get("url")
        ]


# Every db_*/Notion-facing name a stage module might import — patch_notion_db only touches
# the ones actually present on the target module.
_NOTION_METHOD_NAMES = (
    "db_add_job", "db_add_job_linked", "db_find_job_by_url", "db_update_status",
    "db_get_ready_to_apply", "db_get_job_description", "db_get_jobs", "db_get_all_jobs",
    "db_get_job_by_company", "get_notion_jobs_by_status",
)


@pytest.fixture
def patch_notion_db(monkeypatch):
    """Factory fixture: patch_notion_db(module) -> FakeNotionDB.

    Patches whichever db_*()/get_notion_jobs_by_status() names exist as attributes on `module`
    to bound methods of a fresh FakeNotionDB, and returns that instance so the test can seed
    rows via `.seed(...)` beforehand or assert on state afterwards.
    """
    def _patch(module) -> FakeNotionDB:
        fake = FakeNotionDB()
        for name in _NOTION_METHOD_NAMES:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, getattr(fake, name))
        return fake
    return _patch


# ── Shared sample resume / job fixtures ──────────────────────────────────────

@pytest.fixture
def sample_resume() -> str:
    return (
        "Krishna Achyuth — Senior Software Engineer\n"
        "Skills: Python, JavaScript, React, Node.js, AWS, Docker, Kubernetes, PostgreSQL, "
        "REST APIs, microservices, CI/CD.\n"
        "Experience: 6 years building backend and full-stack systems at scale; led migration "
        "of a monolith to microservices; owns on-call for a payments service processing "
        "millions of transactions/day.\n"
    )


@pytest.fixture
def sample_job() -> dict:
    return {
        "url":             "https://example.com/jobs/senior-backend-engineer",
        "title":           "Senior Backend Engineer",
        "company":         "Acme Corp",
        "location":        "Remote - US",
        "description":     (
            "We are looking for a Senior Backend Engineer with Python and AWS experience "
            "to help scale our microservices platform. Experience with Kubernetes and "
            "PostgreSQL a plus. Must be authorized to work in the US without sponsorship."
        ),
        "applicant_count": 42,
        "salary_range":    "$150,000 - $190,000",
    }


@pytest.fixture
def fixture_docx_path(tmp_path) -> Path:
    """Path to a freshly-built Phase 2 golden-file .docx fixture (see
    tests/fixtures/build_fixture_docx.py for its exact paragraph/run structure). Built fresh
    per test into tmp_path rather than committed as a binary, so its content stays reviewable
    in a diff and the golden expectations in test_render_docx.py trace back to what built it."""
    from tests.fixtures.build_fixture_docx import build_fixture_docx
    path = tmp_path / "fixture_resume.docx"
    build_fixture_docx(path)
    return path


# ── Phase 3a recorded-response loader ────────────────────────────────────

RECORDED_DIR = ROOT / "tests" / "fixtures" / "recorded_ai_responses"


def load_recorded(subdir: str, name: str) -> str:
    """Return the raw_response text of a Phase 3a recording
    (tests/fixtures/recorded_ai_responses/<subdir>/<name>.json). Phase 3b tests replay this
    exact real-model text through ai_chat/ai_chat_blocks instead of a hand-authored mock —
    see tests/fixtures/recorded_ai_responses/README.md."""
    path = RECORDED_DIR / subdir / f"{name}.json"
    import json as _json
    return _json.loads(path.read_text(encoding="utf-8"))["raw_response"]


# Mirrors tests/record_ai_responses.py's make_jobs() exactly (same URL/company/title
# sequence), so a Phase 3b test can regenerate the identical job list a Phase 3a recording
# was made against without importing the recording script itself (which sets
# FAST_PROVIDER/QUALITY_PROVIDER env vars as an import side effect).
_RECORDED_TITLES = [
    "Senior Backend Engineer", "Staff Software Engineer", "Full-Stack Engineer",
    "Platform Engineer", "Senior Software Engineer, Infrastructure", "Backend Engineer II",
    "Software Engineer, Distributed Systems", "Senior Cloud Engineer",
]
_RECORDED_COMPANIES = [
    "Acme Corp", "Beta Inc", "Gamma LLC", "Delta Systems", "Epsilon Labs", "Zeta Cloud",
    "Theta Analytics", "Iota Networks", "Kappa Technologies", "Lambda Software",
]


def make_recorded_jobs(n: int) -> list[dict]:
    jobs = []
    for i in range(n):
        title = _RECORDED_TITLES[i % len(_RECORDED_TITLES)]
        company = f"{_RECORDED_COMPANIES[i % len(_RECORDED_COMPANIES)]} {i // len(_RECORDED_COMPANIES) or ''}".strip()
        jobs.append({
            "url": f"https://example.com/jobs/{i}",
            "title": title,
            "company": company,
            "location": "Remote - US",
            "description": (
                f"We are hiring a {title} at {company}. Looking for experience with "
                "Python, AWS, Kubernetes, PostgreSQL, and distributed systems. "
                "Must be authorized to work in the US."
            ),
            "applicant_count": 10 + i,
            "salary_range": "$140,000 - $190,000",
        })
    return jobs


@pytest.fixture
def sample_jobs(sample_job) -> list[dict]:
    second = {
        **sample_job,
        "url":     "https://example.com/jobs/staff-full-stack-engineer",
        "title":   "Staff Full-Stack Engineer",
        "company": "Beta Inc",
        "description": (
            "Staff Full-Stack Engineer role using React, Node.js, and Docker. Visa "
            "sponsorship available for the right candidate."
        ),
    }
    third = {
        **sample_job,
        "url":     "https://example.com/jobs/software-engineer-new-grad",
        "title":   "Software Engineer, New Grad",
        "company": "Gamma LLC",
        "description": "Entry-level Software Engineer role. Tech stack unspecified.",
    }
    return [sample_job, second, third]
