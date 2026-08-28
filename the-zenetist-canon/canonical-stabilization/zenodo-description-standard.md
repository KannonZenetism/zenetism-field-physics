# The Zenodo Description Standard
## Fixed Form for Deposit Descriptions

**Authorship:** ⚫↺KAI↺⚫ Aelion Kannon  
**Classification:** Canonical Stabilization Infrastructure — Publication Formatting Standard  
**Status:** Active Canonical Reference — harmonized to Publication Engine v2  
**Prepared:** by ⚫↺KAI↺⚫ Aelion Kannon, with ⚮ Liora drafting assistance  
**Principle:** Different deposits require different treatment; the treatment differences live in *which slots are filled*, never in freestyle variation. Three named forms cover all cases. Every description is assembled from the same slots in the same order.  

---

## The Slots (fixed order)

1. **Identity line** — one sentence, always first, no glyphs (this line is what search engines and Zenodo listings show): *what this document is, in one breath*
2. **Class line** — `Document class:` followed by one of the six Corpus Atlas classes — Canon · Registry · Infrastructure · Bridge · Archival Stratum · Record — plus the applicable discipline where relevant
3. **Abstract** — one paragraph, two to five sentences, prose only: no bullets, no bolding, no glyphs. State what the document establishes in the canonical vocabulary current on the deposit date
4. **Contents block** — *only* for multi-part deposits (volumes, series, registries): `Contents:` followed by a short bulleted list of parts. Omit entirely otherwise
5. **Relations block** — *only* when relations exist: `Supersedes:` / `Companion to:` / `Part of:`, entries separated by semicolons. Entry form follows a fixed preference: the backticked canonical filename is the general form; a plain work title appears only where the referent is a multi-file work with no single canonical file to cite (Field Physics: The Architecture of Resonance — the fourteen-file work); a DOI where the DOI relation itself is the claim. A single-file document is never cited by title where its filename is available. Omit otherwise
6. **Provenance line** — one sentence beginning `Canonical file:` and naming the canonical filename only, the filename alone in inline code (`Canonical file:` itself is ordinary prose; the precise GitHub directory belongs in the Zenodo Repository URL field, per Publication Engine v2 §§16–17) and — only where verified for the exact applicable hash — the attestation note specified by the Attestation Convention
7. **Attribution close** — fixed text, identical on every deposit:

   > Authored by Aelion Kannon (⚫↺KAI↺⚫) as part of Zenetism: Structural Metaphysics, Field Physics, Lattice Mathematics, Structural Forensics, Structural Physics, and Structural Neuroscience. Attribution required per the deposit license.

## The Three Forms

- **Short form** (single essay, extension, note): slots 1, 2, 3, 6, 7. Target: fewer than 120 words. A deposit requiring a Relations block takes Standard form
- **Standard form** (protocols, registries, major documents): slots 1–3, 5 where applicable, 6, 7. Target: 120–220 words
- **Series form** (multi-volume deposits, registries with volumes, milestone snapshots): slots 1–4, 5 where applicable, 6, 7. Target: 220–350 words. Snapshot deposits state the frozen date in the identity line ("...as of July 2026")

No deposit exceeds 350 words. Length variance outside the three bands is drift, not treatment.

## Formatting Conventions

- Straight quotes and apostrophes; spaced em dashes; spaced slashes in structural pairs; no terminal-period drift in any list
- Bolding only for the designated block labels (`Document class:`, `Contents:`, `Supersedes:`, `Companion to:`, `Part of:`); never for emphasis inside the abstract
- In deposit descriptions, bullets appear only inside the Contents block; nowhere else
- Filenames appear in inline code wherever named (Zenodo renders these as inline-code highlighting); `Canonical file:` and the block labels themselves are never rendered as code
- Glyphs: none in the identity line or abstract; the seal glyph appears only inside the fixed attribution close
- Vocabulary: canonical terminology current on the deposit date — a deposit description is a dated public statement of the system's state and must not reintroduce retired terms

## Relations Convention

The Relations slot records lateral canonical relation, not bibliography. A file does not become an entry merely because the deposited work cites or consulted it.

**Materiality test.** Include a file only where it materially determines the deposited work's interpretation, placements, terminology, or structural reading. Four classes qualify:

- **Direct interpretive companions** — another canonical work that the deposit explicitly continues, completes, contrasts with, or structurally pairs with
- **Registry seats** — MFLR or SPR volumes where the deposit materially depends on their figure placements, operators, or classification framework
- **Canonical distinction seats** — a specialized canonical file whose doctrine materially determines the reading, such as hypostasis / office / bearer distinctions or continuum / cascade / conflation distinctions
- **Immediate cycle companions** — line-by-line or orientation readings belonging to the same textual cycle, where the deposit explicitly operates as part of that cycle

**Registry volumes and distinction files are not appended by default.** They appear where the individual deposit leans on them. Mechanical appending turns the Relations slot into a growing dependency list and empties it of meaning.

**Label selection:**

- `Companion to:` — lateral canonical relation, as above
- `Supersedes:` — the deposit replaces a distinct earlier work or a deprecated canonical treatment; never merely the next Zenodo version of the same canonical file
- `Part of:` — hierarchical or collection relation, where the deposit is formally a component of a named series, multipart work, or larger deposited unit

**Entry form** follows slot 5. Zenodo archival `_vN` filenames never appear in a relation line: the version suffix belongs to the archival payload, while the relation names the canonical file. The provenance line identifies the deposited work itself; the Relations slot identifies other canonical works related to it.

Where no material relation exists, omit the slot rather than inventing one.

## Keywords Convention

Every deposit carries the fixed core set — *Zenetism, Aelion Kannon, Structural Metaphysics* — plus the applicable discipline and the document's own coined terms (*subversal*, *centropy*, *bifurcal*, *acclivous*, and related terms where applicable). This is not decoration: **indexed coined terms on dated deposits are baseline anchors** — each is a searchable, timestamped occurrence that the Footprint Audit Protocol's pre-anchor baseline can measure against. The keyword field is quiet forensic infrastructure.

**Keyword form:**

- **Casing follows canonical prose casing exactly** — each keyword is cased as the canon writes it in a running sentence, with the Canonical Lexicon as the reference: *Zenetism*, *Aion*, *Structural Metaphysics*, *Hollow Nest Recursion* (proper names and named operators capitalized); *centropy*, *bifurcal*, *acclivous*, *subversal*, *emanation* (concept-terms lowercase). Never write in all caps; never title-case a common noun; no keyword-specific casing conventions exist — the canon's casing is the standard
- **Slashes are spaced in paired or alternative keywords** per the prose guide — *Soul / Mind*, *acclivous / declivous*, *centropic / entropic* — and remain collapsed only where the collapsed form is itself the canonical token (*I/O* and related forms)
- **Each keyword is a term, not a sentence** — no terminal punctuation, no verbs

## Attestation Convention

An attestation sentence is a factual claim about a specific hash, never boilerplate. "Deposit hash" means the SHA-256 hash of the uploaded file exactly as deposited; for multi-file deposits, it means each deposited file's own hash. Include an attestation sentence only after confirming that a `.ots` proof exists for the exact hash named. Three situations require three treatments:

- **Deposit hash individually stamped:** "The deposit hash carries an OpenTimestamps attestation."
- **Containing folder or archive hash stamped, deposit hash not individually stamped:** state the actual containing structure
  - Folder: "This file is contained in a folder whose hash carries an OpenTimestamps attestation."
  - Archive: "This file is contained in an archive whose hash carries an OpenTimestamps attestation."
  - Multi-file deposit: replace "This file is" with "These files are" in the applicable sentence
- **No attestation for this deposit:** omit the sentence entirely. The Zenodo DOI timestamp stands as the provenance anchor on its own

A proof for a folder or archive attests the folder or archive hash, not the deposit hash. The individually stamped sentence is false when only the containing structure's hash is attested.

Deposits published before the per-file stamping practice began may be stamped later. An OpenTimestamps proof attests existence from the moment of stamping forward and cannot backdate, so the DOI carries the earlier date while the new proof carries the hash — both claims remain honest, with each performing its own function. Zenodo permits description edits without minting a new DOI, so existing descriptions carrying an unconditional sentence can be corrected in place after each deposit's actual attestation state is checked.

The worked example that follows shows the individually stamped case.

## Worked Example (Standard form — the Canonical Lexicon)

> The Canonical Lexicon is the current-state reference to Zenetist vocabulary: every core term of the system rendered in post-stabilization canonical form, with pointers to each term's canonical seat.
>
> **Document class:** Infrastructure — Canonical Stabilization (cross-discipline).
>
> The Lexicon consolidates the vocabulary of the six Zenetist disciplines as stabilized through July 2026: the ground registers (Zenon, Aion, Khaon), the hypostases and arcs, the layered Soul / Mind architecture, motion and orientation terms, the diagnostic vocabulary of coherence and its counterfeits, and the register principles for canonical prose. It is the dated state-of-vocabulary reference that supplements the founding glossary (MP11 §26.1), which remains the canonical seat in the founding voice.
>
> **Companion to:** `terminological-lockdown-protocol.md` (with Addendum I); `MP11-codex-of-principles-ch26.md`.
>
> Canonical file: `canonical-lexicon.md`. The deposit hash carries an OpenTimestamps attestation.
>
> Authored by Aelion Kannon (⚫↺KAI↺⚫) as part of Zenetism: Structural Metaphysics, Field Physics, Lattice Mathematics, Structural Forensics, Structural Physics, and Structural Neuroscience. Attribution required per the deposit license.

---

**⚫↺KAI↺⚫**  
*Structural Metaphysics · Field Physics · Lattice Mathematics · Structural Forensics · Structural Physics · Structural Neuroscience*

**Collaborators:** 🔦 Lumen · ⚮ Liora · ⧃ Kael · 💎 Clarion · ⟡ Aetherion
