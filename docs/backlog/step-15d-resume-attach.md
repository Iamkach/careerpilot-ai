# Step 15d — Resume attach: `GET /resume` + DataTransfer (Layer 3, increment 3a)

**Status:** queued, not started (2026-07-31). Size **M**. Depends on
[step-15c](step-15c-extension-readonly-overlay.md). Fourth of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first — this is the **go/no-go checkpoint** for the whole epic, see Risk 2 there).

## Goal

Deliver the headline win: attach the correct tailored resume file to the form's upload field with
one click, verified by reading the input back — no typed answers yet, zero eligibility risk. This
carries the least risk of any increment (it fills no answer content) and is the mechanism most
likely to vary per site, so it is measured before `step-15e` invests further.

## Scope

**In:** `GET /resume?page_id=&accept=`; the 403 containment check; PDF-only fallback via
`render_docx.convert_docx_to_pdf()`; the `accepts_docx()` extraction from
`autoapply_browser.py:102-112`; the three-tier client-side dropzone strategy; verify-don't-claim
readback.

**Out:** text/select field fill (`step-15e`), drafts (`step-15f`), confirm-applied (`step-15g`).

## Implementation

### Server: `GET /resume`

`?page_id=&accept=<input's accept attr>` → bytes, with:
- A hard containment check: `Path(p).resolve()` must be under `RESUMES_DIR`, else 403 — the Notion
  DB is user-editable and the browser is the caller, so this path cannot be trusted blindly.
- The shared `accepts_docx()` rule, falling back to `render_docx.convert_docx_to_pdf()` for
  PDF-only forms (reusing Layer 2's decision at `autoapply_browser.py:115-123`).
- `Content-Disposition` filename set from the resolved file, not from client input.
- 403 (no bytes) on a `_READONLY_CHANNELS` page — `/resume/meta` (from `step-15b`) stays allowed
  there; only bytes are gated.
- Constrain `_download_tailored_resume()` (`autoapply.py:493`)'s fetch host to
  `raw.githubusercontent.com` while in this file — closes the mild SSRF shape now that a browser
  request can trigger this path (epic Risk 6).

### Client: DataTransfer attach

```js
const dt = new DataTransfer();
dt.items.add(new File([bytes], filename, {type: mime, lastModified: Date.now()}));
input.files = dt.files;
input.dispatchEvent(new Event('input',  {bubbles: true}));
input.dispatchEvent(new Event('change', {bubbles: true}));
```

### Dropzone strategy, three tiers

1. **Find the hidden input.** Greenhouse, Ashby, Workday, Dropzone.js, react-dropzone, Uppy and
   Filestack all still render a real `<input type=file>`, hidden via `display:none`/`opacity:0`/1px.
   Query across the document **including open shadow roots**, do **not** filter on visibility, and
   prefer the one nearest the labelled question container. Covers the large majority.
2. **Synthesize a drop** — `dragenter`→`dragover`→`drop` carrying the same `DataTransfer`.
   react-dropzone reads `event.dataTransfer.files` and accepts this.
3. **Fail loudly, usefully** — badge the field and surface the resolved absolute path with a *Copy
   path* button. Even this floor removes both the Notion lookup and the file hunt: paste into the
   OS dialog's filename box.

Do **not** attempt `input.click()` to open the OS dialog — user-gesture-gated and not scriptable.
Do not imply otherwise in the UI.

**Verify, never claim.** Read back `input.files[0]?.name` and report *"attached (verified)"* or
*"not attached"* — `autoapply_browser.py`'s rule #2 applied here.

## Files

**New:** none beyond extending `extension/content.js` (attach logic) and
`scripts/autoapply_server.py` (`/resume` route) from prior stories.
**Modified:** `scripts/autoapply_browser.py` (extract `accepts_docx()` so both layers share one
rule) · `tests/test_autoapply_server.py` (adds `/resume` cases).

## Verification

Automated:
1. `/resume` bytes 403 on a read-only channel; `/resume/meta` still allowed.
2. `/resume` refuses a `file://`/local path outside `RESUMES_DIR`; bad token rejected *before* any
   Notion read.
3. PDF-only form gets a converted PDF (mock `convert_docx_to_pdf`).
4. `_download_tailored_resume()` fetch host constrained to `raw.githubusercontent.com` — a
   different host is rejected.

**Live, on forms you do not intend to submit** — this is the go/no-go: Greenhouse → Ashby → one
custom careers page reached *through* a LinkedIn posting → Workday (expect partial):
5. **Attach readback on all four sites.** Where it fails, confirm the Copy-path fallback appears
   and the path is correct/paste-able.
6. Open an untracked job: resume field is badged `resume-missing`, no attach attempted, no other
   job's resume is attached anywhere on the page.
7. LinkedIn Easy Apply: `/resume` 403s as expected, but filename + Copy path still render from
   `/resume/meta`.

## Decision point

If attach readback fails broadly across Ashby and the custom career site (tier 1 and tier 2 both
miss, tier 3 fallback is all that's left on most sites), stop and reassess before starting
`step-15e`: the headline win may not exist, and what remains (path display, Applied confirm,
read-only overlay from `step-15c`/`step-15g`) may not justify the second UI surface. This decision
belongs here, not at the end of the epic.

## Risks

`isTrusted: false` — some ATS validators and dropzones reject synthetic file assignment/drop
events; nothing a content script can do about it. Expect a nonzero per-site failure rate; this is
exactly what the tier-3 fallback and verify-don't-claim readback exist for.
