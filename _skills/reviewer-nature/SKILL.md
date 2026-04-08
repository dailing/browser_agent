---
name: reviewer-nature
description: Review papers on Springer Nature (reviewer.springernature.com). Use when listing papers on the dashboard, obtaining the manuscript as PDF then markdown, drafting reviewer feedback with the user, or filling and submitting the report form. Work entirely through the browser UI (clicks, fields, menus, print dialog)—no terminal or shell commands. Login credentials in this skill. One continuous workflow in the main session — no sub-agents.
---

# Springer Nature paper reviewer — single-session workflow (UI only)


**Order of work**

1. **Prepare the paper** — In the browser: dashboard, sign in if needed, note IDs/URLs, use **Download files** to see attachments, end up with **one clean PDF of the main manuscript** (download if PDF, or **Open quick preview** + browser **Print → Save as PDF** if Word), then get **paper.md** into the review folder (see below—no shell required on your side).
2. **Draft the review with the user** — Read `paper.md`, analyze, write `review_notes.md` and `review_text.txt`, confirm concerns with the user before locking text.
3. **Fill the form and submit** — In the browser: open the **Submit Report** page, paste author comments, answer editor questions, use **Preview**, get explicit user confirmation, then submit.

Keep the same browser session through steps 1–3 when practical. If the session was lost, sign in again with the credentials below and return to the dashboard or the saved submit link.

---

## When to talk to the user

| Moment | What to do |
|--------|------------|
| Login fails after using the credentials in this skill | Stop. Report the error; do not guess credentials elsewhere. |
| After `paper.md` exists | Briefly report title, paths, and that the manuscript is ready to review. |
| Before writing final text into `review_text.txt` | Show summary and concern list; ask which concerns to include or adjust. |
| After filling the portal form (before final submit) | Describe the form state; ask whether to submit or what to change. |
| Final submit | Only after the user clearly confirms (e.g. yes / submit / go ahead). |

---

## 1. Prepare the paper (browser only)

### Login credentials (type manually)

Do **not** rely on password-manager autofill unless the user prefers it; type email and password into the site’s fields.

| Field | Value |
|-------|--------|
| Email | `qzyz_dailing@163.com` |
| Password | `a141421356` |

**Sign-in flow:** Use **Continue with ORCID** (or whatever sign-in the page shows). Complete ORCID or reviewer login with the email and password above. Use normal form fields (focus, type)—not image-based coordinate clicking for text.

### Open the dashboard

In the browser address bar, go to:

`https://reviewer.springernature.com/dashboard/reviews`

**Login:** As above—**Continue with ORCID**, then email and password.

From the dashboard, note:

- Manuscript submission id (from **Open quick preview** link: path like `/review-submission/<id>/view`, or from the row).
- **Submit Report** link or URL for the feedback form (needed in step 3).

### Main manuscript: **Download files** vs preview

Stay on the dashboard on the correct assignment row.

1. Click **Download files**. A popup lists uploads: main manuscript, supplementaries, figures/tables, prior **response to reviewers**, etc.
2. **Choose the main manuscript only**—the primary article file, not supplement-only bundles, separate figure packs, or response letters unless the user asked to review those as main text.
3. Read each row’s label and file type (`.pdf`, `.doc`, `.docx`, …).

**A — Manuscript is already PDF**

- Click the **download** control for that manuscript row so the browser saves a `.pdf`.
- Remember where the file was saved (browser download location or “Save as” path). That PDF is the source for markdown conversion.

**B — Manuscript is Word (`.doc` / `.docx`)**

- Prefer **not** using the raw Word file as the only source if the goal is a stable read-through PDF.
- Close or dismiss the popup if needed. Click **Open quick preview** for that paper so the manuscript opens in a **preview** (new tab or same tab—switch to it). Wait until content is visible.
- **Save as PDF from the browser:** Open the browser **Print** dialog (e.g. menu **File → Print**, or shortcut **Ctrl+P** / **Cmd+P**). Choose **Save as PDF** (or **Microsoft Print to PDF**, etc.) as the destination—not a physical printer. Save the file. Use that PDF as the source for markdown conversion.

**Goal:** One clean PDF of the main manuscript, whether the authors uploaded PDF or Word.

Optional: you may still download other listed files for reference; keep them separate from the file you treat as the main manuscript unless the user says otherwise.

### Markdown and folder layout (no commands)

You need a folder like `~/Sync/review/paper.<document_id>/` containing at least:

- `paper.md` — full manuscript as markdown (from whatever PDF-to-markdown step the user or another tool provides).
- `review_notes.md` — working notes (create empty or append as you work).
- `review_text.txt` — final text for the portal author box (create when ready).

**How to get `paper.md` without a terminal:** Use any available non-shell path the user has (e.g. upload PDF in a web-based converter the user uses, or the user drops `paper.md` into the folder). Your job is to **read and edit these files** through the editor/workspace once they exist—not to run `curl`, `mkdir`, or `mv`.

---

## 2. Draft the review with the user

Open and read `~/Sync/review/paper.<document_id>/paper.md` from the workspace.

Put a 1–2 sentence summary at the top of `review_notes.md` (or the notes file you use), plain text, no markdown headings required for that line if you prefer simplicity.

**Then stop and message the user** to interact. Systematically report:

0. What basic task the paper does (classification, detection, segmentation, regression, etc.).
1. Inputs, outputs, and the concrete task (diagnosis, survival, ranking, risk, etc.).
2. Claims vs. results—claimed novelty or advantage.
3. Dataset: what data, sample size, possible leakage, how splits/handling were done.
4. Table/text consistency—conflicts or impossible numbers.
5. Numerical plausibility (e.g. very high accuracy with tiny samples).
6. Other issues: references, language, misleading concepts, etc.

The user will confirm concerns or ask questions. When they want a concern in the report, add a concise entry to `review_notes.md`.

**Format for `review_text.txt`:**

```
SUMMARY
<1-2 sentences>

CONCERN 1:
<body, evidence-based, plain text>

CONCERN 2:
<body>

...
```

When the user says they are ready for the portal (e.g. “submit”, “fill the form”, “done with the text”), continue to step 3.

---

## 3. Fill the form and submit (clicks and fields only)

### Open the submit page

In the browser, go to the **Submit Report** URL you saved (pattern like):

`https://reviewer-feedback.springernature.com/feedback/<id>/<token>/report`

### Author comments

- Find the large text area used for **comments to authors** (often labeled in UI or `aria-label` containing “author” or similar).
- Paste the full contents of `review_text.txt` into that box. Trigger any “input” behavior the page needs (some sites require typing or an extra blur—if **Next** is disabled, try tabbing out of the field).

### **Next >**

- Click the button whose visible text is **Next >** (exact label may vary slightly; pick the primary forward control).

### Editor questions (radios and follow-up fields)

Do this in **two passes**—all through visible UI, not snapshots-only guessing.

**Pass 1 — Questions and radios**

1. Scroll through the page and identify each **question block** (often a **fieldset** with a **legend**, or a labeled section).
2. For each group of **radio** options, choose the option that matches the review (recommendation, methods, novelty, language, title/abstract, statistics, figures, references, image integrity, etc.).
3. Click the correct **radio** for each question so the choice is visibly selected.
4. Click **Next >** again when the step allows.

**Pass 2 — Fields that appear after your choices**

1. After selecting radios (and after each **Next >** if the wizard adds pages), **look again** for:
   - New or required **text areas** and **single-line text fields**;
   - **Dialogs** or overlays (modal titles, “explain”, validation messages).
2. Fill each new required field with **short text consistent with the radio you chose** (e.g. if methods were unsatisfactory, briefly say why). Do not paste the full author letter unless that field is clearly for it.
3. If the page shows validation errors, read them, fill the indicated fields, then try **Next >** again. Repeat until you reach preview/submit or the step completes.

**Confidential comments to editor:** Use only for serious issues (ethics, integrity, suspected misconduct). Otherwise leave empty. Do not duplicate the author letter there.

### Preview and submit

- Use the portal’s **Preview** (or equivalent) if offered, and confirm the text looks correct.
- **Before clicking final submit:** Tell the user a short summary—recommendation, major choices, and what you typed in required follow-up fields. Ask whether to submit or what to change.

**Final submit:** Click the button whose text is **Submit review report** (or the site’s equivalent final submit control) **only after** the user explicitly confirms.

Confirm to the user that submission completed (e.g. success message on page).

---

## File locations

| File | Path |
|------|------|
| Paper (markdown) | `~/Sync/review/paper.<document_id>/paper.md` |
| Working notes | `~/Sync/review/paper.<document_id>/review_notes.md` |
| Text for author box | `~/Sync/review/paper.<document_id>/review_text.txt` |

## Portal URLs

| Purpose | URL pattern |
|---------|-------------|
| Dashboard | `https://reviewer.springernature.com/dashboard/reviews` |
| Paper preview | `https://manuscript.springernature.com/review-submission/<id>/view` |
| Submit form | `https://reviewer-feedback.springernature.com/feedback/<id>/<token>/report` |

## Tips

- Prefer **named controls** (labels, button text, fieldset legends) over blind clicking.
- **Editor section:** first pass = map questions and set all radios, then **Next**; second pass = scroll again for new text fields and modals, fill them, then continue. If the page is dynamic, re-check after each major choice.
- Do not submit without fresh user confirmation after preview.
- Work in clear stages (dashboard → manuscript PDF → notes → form) instead of rushing everything at once.
