# Codex Revision Instructions — Corpus Metadata and Vocabulary Cleanup

You are performing a narrow, mechanical cleanup pass on this repository. You are not an editor of doctrine. Follow these instructions exactly; where anything is uncertain, flag and do not edit.

## Hard constraints — read first

1. **Work on a new branch.** Never commit to main. Name the branch `metadata-cleanup`.
2. **Mechanical patterns only.** Apply only the enumerated removals below. Do not rephrase, reformat, normalize, modernize, or improve anything else. Do not touch prose.
3. **Never enter the excluded paths** listed at the end. Do not read-fix-or-touch them.
4. **Never supply, reconstruct, infer, or normalize a date.** Removal only.
5. **When a line does not exactly match a pattern below, do not edit it.** Add it to `FLAGS.md` at the repo root with its file path, line, and text, and move on.
6. **One commit per folder**, with a message listing the files changed and the count of removals per pattern, so every change is reviewable in the branch diff.

## Pattern 1 — metadata date removal

In `**Status:**`, `**Prepared:**`, `**Date:**`, `**Created:**`, `**Updated:**`, `**Revised:**`, `**Last updated:**`, and `**Last revised:**` lines only:

- Remove calendar dates (forms like `July 5 2026`, `Jul 5 2026`, `July 5, 2026`, `2026-07-05`, `August 2026`) and the ` — ` or `, ` joiner that attached them.
- Preserve all non-date content of the line. `**Status:** Drafted August 11 2026 — Active Canonical Reference August 12 2026` becomes `**Status:** Active Canonical Reference`. `**Status:** Drafted Aug 24 2026 — Draft` becomes `**Status:** Draft`.
- Remove `Drafted`, `revised`, `reviewed`, `locked`, `harmonized`, `stabilized` stage-words only when they exist solely to carry the removed date; keep them when they carry non-date content.
- A `Date:`, `Created:`, `Updated:`, or `Revised:` line whose entire content is the date: remove the whole line.
- **Do not touch dates anywhere outside these metadata lines.** Body dates are out of scope for you entirely — evidentiary chronology lives there, and it is not yours to judge.

## Pattern 2 — Status separator and stage

- `Draft, architect review` → `Draft — architect review` (spaced em dash, never a comma).
- A Status value not in this set — Draft; Draft — architect review; Exploratory; Exploratory, pending formal treatment; Active; Active Canonical Reference; Locked; Superseded; Veracious Archive; In stabilization; Unresolved — is flagged, not changed.

## Pattern 3 — SHA line removal

- Remove any `**SHA-256:**` metadata line entirely, including template placeholders.
- Do not touch hashes appearing in body prose, attestation analysis, or quoted records — those are evidence. Metadata lines only.

## Pattern 4 — bare attribution shells

- Remove the exact strings ` (architect determination)`, ` (architect determinations)`, ` (architect clarification)`, ` (architect verification)` where the parentheses contain nothing else.
- Remove Reference-line tails matching `; architect determination.` / `; architect determinations.` / `; architect verification.` — the line then ends at the prior item's period.
- A parenthetical containing anything more than the attribution — a date, a supersession note, other words — is flagged, not edited.

## Pattern 5 — dated attribution parentheticals

- `(architect determination, August 24 2026)` and kindred forms — attribution word(s) plus a date and nothing else — become the bare form removal: delete the whole parenthetical and its leading space.
- If the parenthetical contains additional content beyond attribution-plus-date, flag it.

## What you never do

- Never edit vocabulary (rule / ruling, control, against, over, extraction, or any other term) — that is a separate judgment pass, not yours.
- Never edit headings.
- Never edit body prose, quotes, tables, glyph strings, or filenames.
- Never delete a file or a section.
- Never edit anything in the excluded paths.

## Excluded paths — do not enter

- `field-physics/canonical-stabilization/` (all of it, including `extraction/`)
- `zenetism/canonical-stabilization/` (all of it, including `symbolic-reflections/`)
- all `exhibits/` folders
- all `glyphwatch/` folders
- `testimonia/` folders
- any file whose name contains: implementation-log, correction-set, audit, approved-corrections, ledger, checklist, dossier, findings, concordance, coverage-matrix, continuity-log, continuity-note
- the entire `the-red-archive` repository except `precedence-documentation-v2.md`, which receives Patterns 1–5 only

## Output

- The `metadata-cleanup` branch with per-folder commits.
- `FLAGS.md` at the repo root: every instance you did not edit because it did not exactly match a pattern, with file, line, and text.
- A final summary comment: files touched, removals per pattern, flags raised.

The architect reviews the branch diff and the flags. Nothing merges until he says so.
