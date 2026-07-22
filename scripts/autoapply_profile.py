#!/usr/bin/env python3
"""
autoapply_profile.py — one-time interactive setup for Stage 7's application answers.

WHY
    Stage 7 answers application questions from APPLICATION_PROFILE / EEO_RESPONSES /
    COMMON_QUESTION_PRESETS in config/settings.py. Editing a checked-in Python file every time
    you want to change your notice period is the wrong ergonomics, and it puts personal details
    into version control. This wizard asks once, writes the answers to a git-ignored JSON file,
    and settings.py overlays that file over the defaults on every run.

WHAT IT WRITES
    config/application_profile.json  (git-ignored)  — your answers only. It never contains API
    keys or secrets; those stay env-sourced exactly as before.

EDITING LATER
    Re-run this (it pre-fills every prompt with your current answer, so pressing Enter through
    the whole thing changes nothing), or hand-edit the JSON — it's a flat, readable file.

Run:
    python run.py --setup-profile          # same thing, via the main entry point
    python scripts/autoapply_profile.py
    python scripts/autoapply_profile.py --show      # print current answers, change nothing
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
PROFILE_PATH = ROOT / "config" / "application_profile.json"


def say(msg: str = "") -> None:
    """print() that survives a cp1252 Windows console. Mirrors utils.log()'s handling without
    the timestamp prefix (this is an interactive wizard, not a pipeline log)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(msg.encode(enc, errors="replace").decode(enc))


# Each entry: (section, key, prompt, kind). kind ∈ {"text", "yesno", "choice"}.
# Only the fields worth asking a human are here — name/email already live in settings.py as
# YOUR_NAME/YOUR_EMAIL and are derived, not re-asked.
QUESTIONS = [
    ("profile", "phone", "Phone number (as you'd type it on an application)", "text"),
    ("profile", "location", "Current location (e.g. 'Austin, TX')", "text"),
    ("profile", "linkedin_url", "LinkedIn profile URL", "text"),
    ("profile", "github_url", "GitHub URL (blank to skip)", "text"),
    ("profile", "portfolio_url", "Portfolio/personal site (blank to skip)", "text"),
    ("profile", "work_authorized",
     "Are you legally authorized to work in the US?", "yesno"),
    ("profile", "requires_sponsorship",
     "Will you now or in the future require visa sponsorship?", "yesno"),

    # Legal name/address as it appears on your ID — some ATS forms (confirmed live on
    # Greenhouse) ask this separately from the resume/outreach display name above, and it may
    # differ (e.g. a preferred first name vs. a legal one), so these are kept independent.
    ("address", "legal_first_name", "Legal first name (as on your ID/paycheck)", "text"),
    ("address", "legal_last_name", "Legal last name (as on your ID/paycheck)", "text"),
    ("address", "address_line1", "Street address, line 1", "text"),
    ("address", "address_line2", "Street address, line 2 (apt/suite — blank to skip)", "text"),
    ("address", "city", "City", "text"),
    ("address", "state", "State/Province", "text"),
    ("address", "country", "Country", "text"),
    ("address", "zip_code", "ZIP/Postal code", "text"),
    ("address", "address_type", "Address type (e.g. 'Home', 'Mailing')", "text"),

    ("presets", "years of experience", "Total years of professional experience", "text"),
    ("presets", "salary expectation", "Salary expectation (e.g. '180000' or 'Negotiable')", "text"),
    ("presets", "notice period", "Notice period (e.g. '2 weeks', 'Immediate')", "text"),
    ("presets", "willing to relocate", "Willing to relocate?", "text"),
    ("presets", "start date", "Earliest start date (e.g. 'Immediately', '2026-09-01')", "text"),
    ("presets", "how did you hear", "Default answer to 'How did you hear about this job?'", "text"),

    ("eeo", "gender", "EEO — gender", "text"),
    ("eeo", "race", "EEO — race", "text"),
    ("eeo", "ethnicity", "EEO — ethnicity", "text"),
    ("eeo", "veteran", "EEO — veteran status", "text"),
    ("eeo", "disability", "EEO — disability status", "text"),
]

# Shown once before the eligibility questions, because these two are the ones that actually
# cost you something if answered wrong.
ELIGIBILITY_NOTE = (
    "\n  These two are never guessed by the pipeline — a wrong answer to a work-authorization\n"
    "  or sponsorship question is disqualifying and can't be retracted. Leave either blank to\n"
    "  keep being asked by hand on every application.\n"
)


def load_profile(path: Path = PROFILE_PATH) -> dict:
    """Read the saved answers. Returns {} when absent or unreadable — the caller falls back to
    the settings.py defaults, so a missing/corrupt file degrades rather than breaking a run."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_profile(data: dict, path: Path = PROFILE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fmt_current(value) -> str:
    if value is None or value == "":
        return "not set"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return str(value)


def _parse_yesno(raw: str, current):
    """'y'/'n' → True/False. Blank keeps the current value; 'clear' unsets it back to None
    (which means 'always ask me'), since there must be a way to undo a wrong answer."""
    raw = (raw or "").strip().lower()
    if not raw:
        return current
    if raw in ("clear", "unset", "-"):
        return None
    if raw in ("y", "yes", "true", "1"):
        return True
    if raw in ("n", "no", "false", "0"):
        return False
    return current


def build_profile(answers: dict, existing: dict | None = None) -> dict:
    """Merge a flat {(section, key): value} answer map into the saved-profile shape."""
    out = {"profile": {}, "presets": {}, "eeo": {}, "address": {}}
    for section in out:
        out[section] = dict((existing or {}).get(section, {}))
    for (section, key), value in answers.items():
        out[section][key] = value
    return out


def effective_defaults() -> dict:
    """The values Stage 7 would use right now — config/settings.py's defaults with any saved
    profile already overlaid (settings.py applies that overlay at import).

    Prompts are seeded from these rather than from the raw saved file, so pressing Enter keeps
    what the pipeline actually uses. Seeding from the file alone would show "not set" for a
    field that has a real default (EEO answers especially) and then *save* that blank over the
    default — quietly turning "Decline to self-identify" into an empty answer on a live
    application.
    """
    try:
        from config.settings import (
            APPLICATION_PROFILE, COMMON_QUESTION_PRESETS, EEO_RESPONSES, APPLICATION_ADDRESS,
        )
    except Exception:
        return {"profile": {}, "presets": {}, "eeo": {}, "address": {}}
    return {"profile": dict(APPLICATION_PROFILE),
            "presets": dict(COMMON_QUESTION_PRESETS),
            "eeo": dict(EEO_RESPONSES),
            "address": dict(APPLICATION_ADDRESS)}


def run_wizard(input_fn=input, existing: dict | None = None) -> dict:
    """Ask every question, pre-filled with the current answer. Returns the new profile dict.

    `input_fn` is injectable so the flow is testable without a TTY.
    """
    existing = existing if existing is not None else load_profile()
    defaults = effective_defaults()
    answers: dict = {}
    shown_note = False

    say("\nStage 7 application profile — press Enter to keep the current answer.\n")

    for section, key, prompt, kind in QUESTIONS:
        current = existing.get(section, {}).get(
            key, defaults.get(section, {}).get(key, "" if kind == "text" else None))

        if kind == "yesno" and not shown_note:
            say(ELIGIBILITY_NOTE)
            shown_note = True

        suffix = " [y/n, 'clear' to always ask]" if kind == "yesno" else ""
        raw = input_fn(f"  {prompt}{suffix}\n    [{_fmt_current(current)}] > ")

        if kind == "yesno":
            answers[(section, key)] = _parse_yesno(raw, current)
        else:
            raw = (raw or "").strip()
            if raw.lower() in ("clear", "unset", "-"):
                answers[(section, key)] = ""
            elif raw:
                answers[(section, key)] = raw
            else:
                answers[(section, key)] = current

    return build_profile(answers, existing)


def show(path: Path = PROFILE_PATH) -> int:
    data = load_profile(path)
    if not data:
        say(f"No saved profile at {path}. Run `python run.py --setup-profile` to create one.")
        return 1
    say(f"\nSaved profile — {path}\n")
    for section in ("profile", "address", "presets", "eeo"):
        if not data.get(section):
            continue
        say(f"  [{section}]")
        for key, value in sorted(data[section].items()):
            say(f"    {key:24} {_fmt_current(value)}")
        say()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="One-time setup for Stage 7's application answers.")
    ap.add_argument("--show", action="store_true",
                    help="Print the saved answers and exit without changing anything.")
    args = ap.parse_args(argv)

    if args.show:
        return show()

    try:
        profile = run_wizard()
    except (KeyboardInterrupt, EOFError):
        say("\nCancelled — nothing was saved.")
        return 1

    path = save_profile(profile)
    say(f"\n✓ Saved to {path}")
    say("  This file is git-ignored. Re-run this command any time to change an answer,")
    say("  or edit the JSON directly. Stage 7 picks it up on the next run.")

    unset = [k for section in ("profile", "address")
             for k, v in profile.get(section, {}).items() if v in (None, "")]
    if unset:
        say(f"\n  Still unset (you'll be asked by hand for these): {', '.join(unset)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
