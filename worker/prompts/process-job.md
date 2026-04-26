# Per-job prompt

This file is referenced from `.claude/commands/process-job-listings.md`. It describes what to do for a **single** listing. The loop and the git/PR scaffolding live in the slash command.

## Inputs

You have been given the path to a file in `jobs/inbox/<jobId>-<slug>.json`. The JSON contains at minimum:

- `jobId`, `url`, `title`, `company`, `location`
- `work_arrangement`, `work_type`, `salary`, `posted_at`
- `teaser`, `bullets` (array of short lines), `description` (plain text body)
- `language` (optional, default `"en"`) - `"ko"` for Korean listings from
  Wanted or Jumpit. Missing = English.

Treat `description` as the primary source of truth for the posting. Use `teaser` and `bullets` as a secondary signal only.

**Language routing**: if `language == "ko"`, the entire workflow below runs
through the Korean pipeline - Korean guide, Korean CVs, Korean cover letter
directory. Substitutions below are called out inline.

## Steps

1. **Read the source-of-truth files before writing anything.** In order:
   - English listings: `cover-letters/CLAUDE.md`, `professional-writing-guide.md`, `cv/CLAUDE.md`.
   - Korean listings (`language == "ko"`): `tailored-cvs/ko/CLAUDE.md`, `professional-writing-guide-ko.md`, the base `cv/ko/<role>-cv.md` you'll tailor from. Korean applications produce a tailored 이력서, NOT a cover letter.
   - Both: `linkedin-profile.md` and `in-progress-projects.md` - the only sources of Michael's claims. Do not invent experience.

2. **Produce the application artefact**:
   - English: write a cover letter at `cover-letters/<company-slug>-<role-slug>.md`, ASCII-safe, structure per `cover-letters/CLAUDE.md`. Include `<!-- jobId: <jobId> -->` on the second line (immediately after the H1 title) so the apply page can link back to the original posting.
   - Korean: create two files per `tailored-cvs/ko/CLAUDE.md`:
     1. `tailored-cvs/ko/<company-slug>-<role-slug>.json` — JSON sidecar with all CV data, `jobId`, and `base`.
     2. Generate the docx: `python3 scripts/fill-ko-cv-docx.py --from-json tailored-cvs/ko/<slug>.json`
        This creates `tailored-cvs/ko/<slug>.docx`.
   - Do not overwrite an existing `.json` or `.docx` — if either already exists for this company+role, stop and report back so the slash command can skip this listing.

3. **CV handling**:
   - English: pick the best-matching CV from `cv/` per `cover-letters/CLAUDE.md`; if none fits, create a new one under `cv/` per `cv/CLAUDE.md` and update `file-locations.md`.
   - Korean: the tailored 이력서 IS the CV output (no separate recommendation). Pick the best-matching BASE from `cv/ko/` (dotnet / android / ai-engineer / engineering-lead / unity) per `tailored-cvs/ko/CLAUDE.md` and fill its factual content into the JSON sidecar, reordering and emphasising for the posting. If no base CV fits, create a new one under `cv/ko/` per `cv/ko/CLAUDE.md` and update `file-locations.md`.

4. **Update the spreadsheet** at `cover-letters/job-listing-analysis.csv` per the "Spreadsheet tracking" section in `cover-letters/CLAUDE.md`. Create the file if it does not exist. Route to the correct quarter based on the listing's `posted_at` date (or today's date if `posted_at` is empty). Populate the `Language` column with `en` or `ko` based on the listing.

5. **Move the JSON** from `jobs/inbox/` to `jobs/processed/` using `git mv`. Do not rename it.

## What to return to the slash command

When this per-job work is done, the slash command will commit, push, and open a PR. Provide it with:

- The cover letter path.
- The recommended CV path and a one-line reason.
- The CSV row(s) you appended.
- The branch name it should push.

## Non-goals

- Do not edit other cover letters, other CVs, or unrelated CSV rows. One listing = one PR scope.
- Do not change `jobs/seen.json` or `jobs/rejected.json` - those are owned by the scraper and the reviewer respectively.
- Do not alter `search-criteria.yml`.
