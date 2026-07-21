#!/usr/bin/env python3
"""
autoapply_browser.py — Stage 7 Layer 2: pre-fill a live application form. NEVER submits.
──────────────────────────────────────────────────────────────────────────────────────────
Spec: docs/backlog/step-10-auto-apply-subsystem.md §5 (Phase 2)

Takes the plan built by scripts/autoapply.py, opens the real form in Chromium, fills only the
fields the plan marked `ready`, attaches the tailored resume, screenshots the result, and stops.
The human reviews and clicks Submit.

THREE RULES THIS MODULE IS BUILT AROUND — each one is a failure mode observed in comparable
open-source auto-appliers, not a hypothetical:

 1. NO SUBMIT CODE PATH EXISTS HERE. Not behind a flag, not behind a config value. There is no
    call that clicks a submit control anywhere in this file, so no bug, bad plan, or future
    edit can accidentally fire one. tests/test_autoapply_browser.py asserts this.

 2. NEVER CLAIM SUCCESS YOU DIDN'T VERIFY. Comparable tools are widely reported to mark jobs
    applied that were never submitted, which poisons the tracker in the worst direction — you
    stop re-applying to jobs you never actually applied to. Every return here reports only what
    was *observed*: fields actually filled, files actually attached.

 3. FAIL SAFE, NEVER HALF-FILL. If materially fewer fields resolve than the plan expected, the
    page markup has drifted (the thing that archives these projects). Abort and say so rather
    than leave a plausible-looking, subtly-wrong form sitting in front of the human.

Captcha handling: Cloudflare Turnstile and friends are usually *invisible* — they run a scoring
loop and either issue a token or stall forever rather than raising. So every wait here carries an
explicit timeout, and a timeout is classified as a probable challenge and handed to the human.
We never solve, never retry-loop, never hammer.

Requires `pip install playwright` + `playwright install chromium`. Missing or broken Playwright
returns a normal result dict (never raises), so the planning layer degrades cleanly — the same
contract as _headless_fetch() in scripts/sources.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.utils import log, today
from config.settings import APPLICATIONS_DIR

ROOT = Path(__file__).parent.parent

# Per-action ceiling. Generous enough for a slow form, short enough that an invisible captcha
# surfaces as a timeout we can classify instead of an indefinite hang.
ACTION_TIMEOUT_MS = 8000
NAV_TIMEOUT_MS = 30000

# If fewer than this fraction of the plan's ready fields actually resolve on the page, treat it
# as markup drift and abort rather than submitting the human a half-filled form to trust.
MIN_RESOLVE_RATIO = 0.6

# Substrings that betray a bot challenge or a login wall in page content//URL.
_CAPTCHA_HINTS = ("turnstile", "recaptcha", "hcaptcha", "cf-challenge", "are you a robot")
_AUTH_HINTS = ("sign in", "log in", "create an account", "/login", "/signin")


def _result(ok: bool, outcome: str, detail: str = "", filled: int = 0,
            screenshot: str = "") -> dict:
    return {"ok": ok, "outcome": outcome, "detail": detail,
            "filled": filled, "screenshot": screenshot}


def _candidate_selectors(field: dict) -> list[str]:
    """Selectors to try for one planned field, most precise first.

    Greenhouse names its inputs exactly as the public schema reports (`first_name`,
    `question_12345`), so the name-based selectors are reliable *there*. The label-based
    fallbacks are what carry boards with no public schema, and are also what survives a class
    rename — matching on user-visible label text rather than styling hooks, since the visible
    text is far more stable than the CSS classes that broke every comparable project.
    """
    name = (field.get("name") or "").strip()
    label = (field.get("label") or "").strip()
    sels: list[str] = []
    if name:
        sels += [f'[name="{name}"]', f'#{name}']
    if label:
        esc = label.replace('"', '\\"')
        sels += [f'//label[contains(normalize-space(.), "{esc[:40]}")]//input',
                 f'//label[contains(normalize-space(.), "{esc[:40]}")]//textarea',
                 f'//label[contains(normalize-space(.), "{esc[:40]}")]/following::input[1]']
    return sels


def _find(page, field):
    """First locator matching this field that's actually attached, else None. Every wait is
    bounded — an unbounded wait is how an invisible captcha turns into a hang."""
    for sel in _candidate_selectors(field):
        try:
            loc = page.locator(sel).first if not sel.startswith("//") else page.locator(f"xpath={sel}").first
            loc.wait_for(state="attached", timeout=1200)
            return loc
        except Exception:
            continue
    return None


def _accepts_docx(loc) -> bool:
    """Whether a file input will take a .docx. Stage 2 only produces .docx and this repo has no
    docx→PDF converter, so a PDF-only form is a genuine stop rather than something to force."""
    try:
        accept = (loc.get_attribute("accept") or "").lower()
    except Exception:
        return True
    if not accept:
        return True
    return ".docx" in accept or ".doc" in accept or "word" in accept or "*" in accept


def _classify_block(page) -> tuple[str, str] | None:
    """Detect a captcha/login wall. Returns (outcome, detail) or None if the page looks normal."""
    try:
        url = (page.url or "").lower()
        body = (page.content() or "").lower()
    except Exception:
        return None
    for hint in _CAPTCHA_HINTS:
        if hint in body:
            return "captcha", f"bot challenge detected ({hint}) — solve it yourself and submit"
    for hint in _AUTH_HINTS:
        if hint in url:
            return "auth", "the form is behind a login wall — sign in yourself and submit"
    return None


def fill_application(url: str, plan: dict, headless: bool = False) -> dict:
    """Open `url`, fill every `ready` field from `plan`, attach the resume, screenshot, stop.

    Returns {ok, outcome, detail, filled, screenshot}. Outcomes: "filled" (ok=True),
    "captcha", "auth", "drift", "pdf_only", "unavailable", "failed". Never raises.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _result(False, "unavailable",
                       "Playwright not installed (pip install playwright && "
                       "playwright install chromium)")

    ready = [f for f in plan.get("fields", []) if f.get("status") == "ready"]
    if not ready:
        return _result(False, "failed", "plan has no fillable fields")

    out_dir = ROOT / APPLICATIONS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / f"{today()}_{re.sub(r'[^A-Za-z0-9]+', '_', url)[:60]}.png"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page(user_agent="Mozilla/5.0")
                page.set_default_timeout(ACTION_TIMEOUT_MS)
                page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")

                blocked = _classify_block(page)
                if blocked:
                    return _result(False, blocked[0], blocked[1])

                filled, missed = 0, []
                for field in ready:
                    loc = _find(page, field)
                    if loc is None:
                        missed.append(field.get("label") or field.get("name") or "?")
                        continue
                    try:
                        if field["type"] in ("input_file", "attachment"):
                            if not _accepts_docx(loc):
                                return _result(
                                    False, "pdf_only",
                                    "this form rejects .docx and stage 2 only produces .docx — "
                                    "convert the resume by hand and apply from the answer sheet",
                                    filled, "")
                            loc.set_input_files(str(field["value"]))
                        elif field["type"] == "multi_value_single_select":
                            val = field["value"]
                            loc.select_option(label="Yes" if val is True else
                                                    "No" if val is False else str(val))
                        else:
                            loc.fill(str(field["value"]))
                        filled += 1
                    except Exception as e:
                        missed.append(f"{field.get('label','?')} ({type(e).__name__})")

                # Drift guard: too few fields resolving means the markup moved under us.
                if filled < MIN_RESOLVE_RATIO * len(ready):
                    return _result(
                        False, "drift",
                        f"only {filled}/{len(ready)} planned fields resolved — the form's markup "
                        f"likely changed. Not leaving a half-filled form; apply from the answer "
                        f"sheet. Unresolved: {', '.join(missed[:6])}", filled, "")

                try:
                    page.screenshot(path=str(shot), full_page=True)
                except Exception:
                    shot = Path("")

                if missed:
                    log(f"  ⚠ Left for you: {', '.join(missed[:6])}")
                # The browser is intentionally left OPEN in headed mode so the human can review
                # and submit. Closing it here would throw away the entire point of the stage.
                if headless:
                    browser.close()
                return _result(True, "filled",
                               f"{filled}/{len(ready)} fields filled; form NOT submitted",
                               filled, str(shot))
            except Exception as e:
                try:
                    browser.close()
                except Exception:
                    pass
                return _result(False, "failed", f"{type(e).__name__}: {e}")
    except Exception as e:
        return _result(False, "failed", f"browser launch failed: {type(e).__name__}: {e}")
