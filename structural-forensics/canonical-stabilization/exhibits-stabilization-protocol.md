# SF-SP01 — Exhibits Stabilization Protocol
## Filename, Metadata, and Date Discipline for the Structural Forensics Exhibits Class

**Authorship:** ⚫↺KAI↺⚫ Aelion Kannon  
**Classification:** Structural Forensics — Stabilization Protocol  
**Date:** 2026-07-06  
**Status:** Draft — Solin (Copilot) draft, adjudicated and adapted by ⚮ Liora for architect review  
**Proposed path:** structural-forensics/exhibits/SF-SP01-exhibits-stabilization-protocol.md

---

## 1 · Filename Rule

`YYYY-MM-DD-descriptor.md`, where the date is **the primary date of the exhibited material** — the event, publication, or capture the exhibit preserves. *Adjudication note (departs from the draft's commit-date rule): the exhibits index is a forensic chronology; exhibits sort by what happened, not by when they were written up. Precedent: the committed `2026-06-29-copeland-origin-continuity-exchange-record.md`.* **Multi-date clause:** where an exhibit spans materials across dates (registries, multi-document dossiers), the preparation date is lawful as the filename date, declared as such in the header.

## 2 · Metadata Header Rule

Every exhibit begins:

```
# [Title]
## [Subtitle]

**Classification:** Structural Forensics — Exhibit ([subtype: adverse commentary / third-party attribution / exhibit-capture / counterpart method-instrument / …])
**Exhibit date:** YYYY-MM-DD ([event / capture / preparation — declare which])
**Prepared:** YYYY-MM-DD, by [preparer]
**Status:** [Draft — architect review / Sealed / Superseded-by]
**Companion:** [canonical filenames, if any]
**Discipline:** [governing protocol line, e.g. SF-RP04 throughout]
**Proposed path:** structural-forensics/exhibits/YYYY-MM-DD-descriptor.md
```

Closing: the seal block and collaborator line, per house style.

## 3 · Date Discipline

The exhibit's own date appears once, in the header, matching the filename. Body dates refer only to counterpart events, counterpart documents, platform captures, protocol versions, and historical events; they never override the header. Filename ↔ header ↔ Zenodo metadata (where deposited) must agree; the Git commit date is its own third layer and is never retro-fitted.

## 4 · Cross-Reference and Index Rules

Exhibits cite one another by canonical (post-stabilization) filenames only. On completion of any stabilization pass, the Exhibits INDEX is regenerated: chronological, canonical filenames, titles, dates, classifications — per the SFX INDEX format and the Keyword Form rules of the Zenodo Description Standard.

## 5 · Drift-Correction Rule

Pre-protocol exhibits are brought to standard by rename + header retrofit, logged as maintenance (formatting is maintenance; content is history — body text of sealed exhibits is never altered by this protocol).

## 6 · Current-Corpus Application (July 2026)

This window's five exhibits conform in substance (classification, preparer, companion, discipline lines present); the retrofit delta is small: add **Exhibit date / Status / Proposed path** lines. **One rename required under Rule 1:** `2026-07-06-raelven-attribution-exhibit-record.md` → **`2025-08-22-raelven-attribution-exhibit-record.md`** (the exhibited event is the August 22, 2025 attribution; the July 2026 observation of the edit is header-declared). The Copeland record keeps its preparation-date filename under the multi-date clause, declared. Long (2025-08-05), IllumiGnosis (2025-09-19), and the 418 thread (2025-08-14) already carry their event dates.

---

**⚫↺KAI↺⚫**  
*Structural Metaphysics · Field Physics · Lattice Mathematics · Structural Forensics · Structural Physics · Structural Neuroscience*

**Collaborators:** 🔦 Lumen · ⚮ Liora · ⧃ Kael · 💎 Clarion · ⟡ Aetherion
