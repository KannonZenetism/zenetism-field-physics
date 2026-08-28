# Zenetism Publication Engine
## GitHub / Zenodo Publication Specification — Version 2

**Authorship:** ⚫↺KAI↺⚫ Aelion Kannon  
**Classification:** Publication Infrastructure — Validated Implementation Specification  
**Status:** Operational — validated through first complete production cycle  
**Repository role:** Durable implementation reference for Work / Codex publication automation  
**Validated reference cycle:** `zenetism-in-plain-language.md` → Zenodo v2  

---

# 1. Purpose

The Zenetism Publication Engine coordinates publication between:

- GitHub — canonical working repository
- Zenodo — DOI-bearing archival and versioned publication surface
- the public Zenetism Site — discovery and navigation layer
- later outward-facing surfaces where separately approved

The engine exists to reduce repetitive publication labor while preserving architect-held determination over:

- doctrine
- canonical wording
- version decisions
- metadata
- attribution
- provenance
- publication timing
- and final public release

The engine must never make publication administration more labor-intensive than direct manual deposit.

Automation is successful only when it reduces architect intervention to review of meaningful differences, held-open decisions, and final publication approval.

---

# 2. Repository Placement and Canonical References

This specification resides at:

`publication-infrastructure/zenetism-publication-engine-v2.md`

The following references hold canonical priority in their existing locations:

- `the-zenetist-canon/canonical-stabilization/terminological-lockdown-protocol.md`
- `the-zenetist-canon/canonical-stabilization/prose-formatting-reference.md`
- `the-zenetist-canon/canonical-stabilization/zenodo-description-standard.md`

Do not duplicate these files inside `publication-infrastructure/`.

Future operational files may include:

- `publication-infrastructure/zenetism-publication-registry.csv`
- `publication-infrastructure/zenodo-record-manifests/`
- implementation code and validation tests created by Codex

No credential, token, password, authentication cookie, or private secret may be committed anywhere in the repository.

---

# 3. Precedence and Priority

Where instructions appear to conflict, apply this order:

1. the architect's most recent explicit determination
2. the Terminological Lockdown Protocol
3. the Prose Formatting Reference
4. the Zenodo Description Standard
5. this Publication Engine specification
6. inherited Zenodo metadata or platform defaults

Do not silently reconcile a real conflict.

Inherited Zenodo metadata never takes precedence merely because Zenodo copied it into a new-version draft.

---

# 4. Surface Roles

## 4.1 GitHub

GitHub holds the canonical current working file.

The canonical GitHub filename normally remains unversioned:

`filename.md`

GitHub carries:

- current document bytes
- canonical repository placement
- commit history
- current canonical filename
- corpus relationships

A Zenodo version must never silently modify the GitHub payload.

If the canonical file itself requires correction, that correction is a separate approved GitHub action and must occur before the Zenodo candidate checksum is locked.

## 4.2 Zenodo

Zenodo carries:

- versioned archival files
- exact version DOIs
- the all-versions concept DOI
- publication metadata
- public citation metadata
- per-record provenance and relations

Zenodo does not replace GitHub as the canonical working repository.

## 4.3 Public Zenetism Site

Canonical public Site:

https://zenetism.aelionkannon.chatgpt.site

The Site is the public discovery and navigation layer.

When a Zenodo record is related to the Site, apply the clean URL without referral parameters.

Current relation convention:

- Relation: `IsDocumentedBy`
- Scheme: URL
- Related resource type: Other
- Identifier: `https://zenetism.aelionkannon.chatgpt.site`

Do not place referral-bearing forms such as `?utm_source=chatgpt.com` into Zenodo metadata.

## 4.4 Architect

The architect retains final determination over:

- whether a GitHub difference warrants publication
- whether a new Zenodo version should be created
- held-open terminology or doctrine
- publication date
- version label
- contributor roster
- description
- keywords
- relations
- final publication

The engine prepares and validates.

The architect publishes.

---

# 5. No Autonomous Editorial Revision

The Publication Engine may:

- retrieve files
- compare files
- calculate checksums
- retrieve public metadata
- determine technical mismatches
- prepare metadata packages
- create unpublished drafts when approved
- validate saved drafts
- generate publication registries
- perform read-only post-publication verification

The engine may not:

- rewrite canonical doctrine independently
- silently correct a GitHub file during Zenodo publication
- adjudicate held-open doctrine
- convert a bridge document into technical-register prose
- change status or publication dates merely because a new Zenodo version is created
- infer contributors from a standard collaborator seal
- publish without architect approval

A publication task is not a manuscript-revision task unless the architect explicitly combines them.

---

# 6. Core Identity Principle

A publication record is anchored by:

- canonical GitHub repository
- canonical GitHub path
- canonical GitHub filename
- GitHub commit
- payload checksum
- Zenodo concept DOI
- Zenodo exact-version DOI
- Zenodo archival filename
- Zenodo archival checksum

These identifiers must remain distinguishable.

Do not confuse:

- GitHub canonical filename with Zenodo archival filename
- exact-version DOI with concept DOI
- Zenodo metadata revision count with document version number
- technical creation/modification timestamps with bibliographic publication date

---

# 7. Zenodo Archival Filename Convention

GitHub canonical filenames remain unversioned unless the architect separately changes the canonical filename.

Zenodo archival files carry the Zenodo version suffix immediately before the extension.

Pattern:

`filename_vN.md`

Examples:

- GitHub canonical: `zenetism-in-plain-language.md`
- Zenodo v2: `zenetism-in-plain-language_v2.md`
- Zenodo v3: `zenetism-in-plain-language_v3.md`
- Zenodo v4: `zenetism-in-plain-language_v4.md`

The archival rename must not alter the payload.

Before upload and after upload:

- calculate SHA-256
- calculate MD5 where available
- confirm byte size
- confirm payload identity

Upload-copy suffixes such as `(1)`, `(5)`, or `(9)` are attachment artifacts and must never enter public filenames.

---

# 8. Default File Preview Convention

Every Zenodo deposit containing a previewable Markdown file must explicitly select the intended archival file in Zenodo's Preview / default-display selector.

Apply this even when only one file exists.

Do not rely on Zenodo's automatic first-file behavior.

After saving the draft:

1. verify the Preview selector is set
2. reload the draft
3. verify that the selection persists
4. open the rendered Preview
5. verify that the intended Markdown file displays automatically

Failure of the Preview selection is a draft-validation failure.

---

# 9. Version-Family Convention

When updating an existing Zenodo publication family, begin from the published record's:

**New version**

action.

Do not create a standalone deposit when the intended result is another version of an existing record.

The New version workflow must preserve:

- historical prior versions
- the existing concept DOI
- Zenodo's automatic version-family relations

Do not manually duplicate Zenodo's system-generated `IsVersionOf` relation.

Historical records remain unchanged unless the architect separately approves a metadata correction to them.

---

# 10. DOI Convention

For a new Zenodo-minted object, answer:

**Do you already have a DOI for this upload?**

with:

**No, I need one.**

Select **Yes, I already have one** only when the exact uploaded object already possesses a DOI assigned outside the current Zenodo deposit workflow.

Never enter:

- the previous Zenodo version DOI
- the concept DOI

as the existing DOI of a new version.

Zenodo assigns or reserves the new exact-version DOI.

The concept DOI remains the all-versions identifier.

---

# 11. Publication-Date Convention

The bibliographic publication date is not automatically replaced by the date on which a later Zenodo version is uploaded.

Default Zenetism convention:

- preserve the work's established first-publication date across ordinary Zenodo versions
- allow Zenodo's technical creation/modification timestamps and version DOI history to carry the later archival chronology
- do not add a revised date solely because a new Zenodo version is created

A revised date or changed bibliographic publication date requires an explicit architect determination and ordinarily corresponds to a materially reworked publication.

The engine must never accept Zenodo's new-draft default date without comparison relative to the approved manifest.

---

# 12. Version Field

Every new Zenodo file version must carry its explicit document version in Zenodo's Version field:

- `v1`
- `v2`
- `v3`
- and so forth

Do not confuse Zenodo's internal metadata revision counter with this field.

If a historical record lacks a Version field, do not automatically initiate a corpus-wide repair.

Local discovery of an older metadata convention does not license mass revision.

---

# 13. Creator Convention

Until a separately approved Zenodo-wide creator migration occurs, preserve the established Zenetism creator-entry convention:

**Family name:** Aelion Kannon  
**Given names:** blank

Free-text authorship remains:

**Aelion Kannon**

After every draft save, verify:

- creator form contents
- rendered creator
- actual Citation block

The desired public citation name is:

**Aelion Kannon**

Do not alter approximately historical records merely to normalize person-field structure unless the architect explicitly approves a Zenodo-wide metadata project.

---

# 14. Contributors

Deposit-specific contributors must be explicitly approved.

Do not infer Zenodo contributor status merely because a name appears in a standard closing collaborator seal.

For the validated reference cycle, the approved deposit-specific contributors were:

- ⚮ Liora — Researcher
- 🔦 Lumen — Researcher

Other deposits may have different contributor determinations.

The manifest must state the approved roster for each record.

---

# 15. Copyright

Populate Zenodo's Copyright field when available.

Apply the architect-approved copyright string.

For the validated reference cycle:

`2026 Aelion Kannon`

Do not automatically update the copyright year merely because a later Zenodo version is uploaded.

Do not insert the copyright string into the description as a substitute for the dedicated metadata field.

---

# 16. Repository URL

The Zenodo Repository URL must point to the precise GitHub directory containing the canonical file.

Do not reduce this field to the repository root when a stable precise directory exists.

Validated reference example:

https://github.com/KannonZenetism/zenetism-field-physics/tree/main/the-zenetist-canon/introductory-orientation

The canonical file itself remains identified separately in the description.

---

# 17. Canonical File Line

Current architect determination for Zenodo implementation:

The provenance line identifies the canonical filename only.

Pattern:

Canonical file: `filename.md`.

Only the filename itself is inline code.

Do not place the whole repository-relative path in this line.

Do not render `Canonical file:` as code.

The rendered Zenodo description must show:

- ordinary prose for `Canonical file:`
- the filename as Zenodo inline-code highlighting
- no visible literal backtick characters

Implementation should apply Zenodo-supported inline-code semantics, such as the resulting `<code>` element.

The precise GitHub directory belongs in the Repository URL field.

This architect determination supersedes the Zenodo Description Standard's earlier full-repository-path wording. The Description Standard was harmonized to this determination.

---

# 18. Description Standard

Continue to apply:

`the-zenetist-canon/canonical-stabilization/zenodo-description-standard.md`

Description forms remain:

- Short form
- Standard form
- Series form

Do not expand a Short-form description merely to make it resemble a longer protocol or registry deposit.

Required rendering conventions include:

- identity line first
- `Document class:` rendered bold
- abstract in prose
- no decorative bold inside the abstract
- Canonical file line
- fixed attribution close
- straight quotation marks
- spaced em dashes
- spaced structural slashes
- no unnecessary glyphs in the identity line or abstract

The public Site URL is not inserted into the description when it is already carried as the approved record relation.

---

# 19. Keywords

Every deposit must carry the exact architect-approved keyword set for that document.

Do not trust keywords inherited from the previous Zenodo version.

Validation must compare:

- keyword count
- exact term
- exact order
- exact casing
- slash spacing

Apply the Zenodo Description Standard's canonical-casing convention.

Core discovery terms commonly include:

- Zenetism
- Aelion Kannon
- Structural Metaphysics

Add disciplines and document-specific terms only where appropriate to the document.

A new-version draft that silently drops keywords fails validation.

---

# 20. Route Determination

## 20.1 No change

Choose no change when:

- the Zenodo payload corresponds to the intended GitHub payload
- and the metadata is current enough that no architect-approved revision is required

## 20.2 Metadata-only revision

Choose metadata-only revision when:

- the deposited file remains the intended published artifact
- no file replacement is required
- only metadata requires correction

A metadata-only revision must not disguise a file mismatch.

## 20.3 New version

Choose New version when:

- the architect intends Zenodo to carry a GitHub payload different from the currently published Zenodo file
- a new archival file must replace the prior public articulation
- or the current deposited file no longer represents the intended publication

The engine must not independently decide that a payload difference is too minor to matter.

If intent is unclear, hold for architect determination.

---

# 21. Approved Manifest

Every production action must derive from one explicit record manifest.

The implementation may store manifests as YAML, JSON, or another structured format.

Minimum conceptual schema:

```yaml
record_key: zenetism-in-plain-language

github:
  repository: KannonZenetism/zenetism-field-physics
  branch: main
  directory: the-zenetist-canon/introductory-orientation
  canonical_filename: zenetism-in-plain-language.md
  commit: <commit>
  sha256: <sha256>
  md5: <md5>

zenodo:
  concept_doi: <concept-doi>
  previous_version_doi: <previous-version-doi>
  target_version: v2
  archival_filename: zenetism-in-plain-language_v2.md
  publication_date: 2026-07-03
  resource_type: Report
  access: Open
  license: CC BY 4.0
  copyright: 2026 Aelion Kannon

creator:
  family_name: Aelion Kannon
  given_names: ""

contributors:
  - name: <approved contributor>
    role: Researcher

repository_url: <precise-directory-url>

description:
  form: Short
  rendered_html: <approved-description>

keywords:
  - <approved ordered keyword>

site_relation:
  relation: IsDocumentedBy
  scheme: URL
  resource_type: Other
  identifier: https://zenetism.aelionkannon.chatgpt.site

preview:
  explicit_default_file: true

publication:
  architect_publish_required: true
```

The approved manifest, not Zenodo's inherited draft state, anchors production.

---

# 22. Fail-Closed Validation

Production validation must be exact.

After writing metadata:

1. Save the draft.
2. Reload the draft.
3. Read the saved values back.
4. Compare every manifest-bound field relative to the approved manifest.
5. Inspect rendered Preview behavior.
6. Stop if any manifest-bound value differs.

Do not accept "save succeeded" as proof that the draft is correct.

A mismatch in any of the following blocks publication:

- payload checksum
- archival filename
- version
- publication date
- creator
- contributors
- copyright
- repository URL
- description
- rendered inline-code filename
- keyword set
- related identifiers
- Preview selection
- DOI handling
- version-family identity

No Publish action may occur while any manifest-bound field is unresolved.

---

# 23. Inherited-Metadata Warning

Zenodo New version drafts may inherit prior metadata or platform defaults that do not match the current approved package.

Never assume inherited values are correct.

The first validated production cycle demonstrated the need to reassert and verify:

- publication date
- Version
- description
- keywords
- default Preview selection
- repository URL
- creator convention
- copyright
- related identifiers

The engine must overwrite inherited/default values from the approved manifest where necessary and verify the result after reload.

---

# 24. Workflow

## Phase 1 — Read-Only Comparison

Retrieve:

- current GitHub file
- current GitHub commit
- file checksum
- current Zenodo record
- current Zenodo file
- version DOI
- concept DOI
- metadata

Determine:

- no change
- metadata-only revision
- new version
- architect-held case

No external change occurs.

Architect-facing output should be concise.

Detailed machine diagnostics may be retained separately when needed.

## Phase 2 — Sandbox Validation

Sandbox is required when:

- first validating the engine
- engine code materially changes
- a new Zenodo metadata pattern is introduced
- a new relation type is introduced
- a new file type or rendering pattern is introduced
- the architect requests Sandbox verification

After the Codex implementation has been validated relative to the reference cycle, routine records using an already validated schema may skip Sandbox only with architect approval.

Sandbox never substitutes for production version-family verification.

## Phase 3 — Production Draft

After explicit approval:

1. begin from New version where applicable
2. preserve the concept DOI
3. reserve the new Zenodo DOI
4. upload the `_vN` archival copy
5. apply the approved manifest
6. explicitly set Preview
7. save
8. reload
9. validate every manifest-bound field
10. open rendered Preview
11. stop

Do not publish.

## Architect Publication Gate

The architect performs the irreversible final publication action after review.

Default determination:

**Automation does not click Publish.**

## Phase 4 — Post-Publication Verification

Read-only verification must confirm:

- exact-version DOI registers and resolves
- concept DOI remains the all-versions identifier
- historical versions remain available
- Versions panel is correct
- archival filename is correct
- live downloaded payload checksum matches the approved candidate
- default Preview survives publication
- Version survives publication
- publication date survives publication
- creator and Citation render correctly
- copyright survives publication
- repository URL survives publication
- description and inline-code rendering survive publication
- keyword set survives publication
- Site relation survives publication
- no unexpected deposit metadata was introduced

Do not edit during Phase 4.

---

# 25. Codex Implementation Target

Version 2 should now move the repetitive mechanics from browser choreography into deterministic software wherever Zenodo and GitHub interfaces permit.

Codex should build:

1. GitHub candidate retrieval
2. commit and checksum capture
3. Zenodo record retrieval
4. version-family discovery
5. structured comparison
6. approved manifest generation
7. Zenodo draft metadata writing
8. archival `_vN` file preparation
9. file upload
10. draft read-back
11. manifest-to-draft validation
12. publication registry maintenance
13. post-publication read-only validation

Browser / Work interaction should be reserved for:

- authentication boundaries
- functions not exposed reliably through the technical interface
- rendered visual verification
- architect review

The engine should not require the architect to manually inspect ordinary metadata fields.

---

# 26. Publication Registry

Create a durable registry after implementation begins.

Recommended path:

`publication-infrastructure/zenetism-publication-registry.csv`

Minimum fields:

- canonical filename
- title
- corpus classification
- GitHub directory
- GitHub commit
- GitHub SHA-256
- GitHub MD5
- concept DOI
- latest version label
- latest version DOI
- Zenodo archival filename
- Zenodo checksum
- publication date
- metadata status
- file status
- Site relation status
- last verification date
- architect approval state
- notes

The registry is operational infrastructure, not canonical doctrine.

---

# 27. No Automatic Corpus-Wide Repair

Discovery of a local inconsistency does not license rewriting historical Zenodo records.

Examples include:

- creator-field conventions
- missing Version fields on old deposits
- old keyword sets
- DOI-form choices
- description-format differences
- historical filenames

Record the discrepancy.

Do not propagate a correction across the archive without a separately approved Zenodo-wide project.

This protects historical provenance and avoids unnecessary revision churn.

---

# 28. Validated Reference Cycle

The first complete validated production cycle is:

**Canonical GitHub file:**  
`the-zenetist-canon/introductory-orientation/zenetism-in-plain-language.md`

**Canonical GitHub filename:**  
`zenetism-in-plain-language.md`

**Published Zenodo archival filename:**  
`zenetism-in-plain-language_v2.md`

**Historical v1 DOI:**  
`10.5281/zenodo.21174439`

**Published v2 DOI:**  
`10.5281/zenodo.21830364`

**All-versions concept DOI:**  
`10.5281/zenodo.21174438`

**Published v2 size:**  
13,414 bytes

**Published v2 SHA-256:**  
`174a984a83ff342af0cb14e64fb61215e05ec31e865ae7592142eb87fd48c1f8`

**Published v2 MD5:**  
`ea3b7e4230d7c43940657c6a1116075c`

Validated behaviors:

- New version preserved the concept DOI family.
- Zenodo minted a distinct v2 DOI.
- The GitHub payload and Zenodo v2 payload are byte-identical.
- `_v2` was added only to the archival filename.
- July 3 2026 remained the bibliographic publication date.
- Version rendered as v2.
- Aelion Kannon rendered correctly in the Citation block.
- Copyright rendered as 2026 Aelion Kannon.
- The precise GitHub directory was retained.
- The canonical filename alone rendered as inline code.
- All approved keywords survived publication.
- The clean Site relation survived publication.
- The archival file remained explicitly selected as the default Preview.
- Historical v1 remained unchanged.

This cycle is the reference test vector for the Codex implementation.

---

# 29. Success Conditions

The Publication Engine succeeds when the architect can provide or approve a publication candidate and receive, with minimal intervention:

1. an accurate route determination
2. a concise summary of meaningful differences
3. a correctly prepared unpublished Zenodo draft
4. exact automated validation
5. a final architect review surface
6. read-only post-publication verification
7. a current publication registry entry

The engine fails its purpose if routine publication requires the architect to manually inspect and repair every inherited Zenodo field.

The system exists to preserve creative capacity and keep publication infrastructure oriented to the work itself.

---

**⚫↺KAI↺⚫**  
*Structural Metaphysics · Field Physics · Lattice Mathematics · Structural Forensics · Structural Physics · Structural Neuroscience*

**Collaborators:** 🔦 Lumen · ⚮ Liora · ⧃ Kael · 💎 Clarion · ⟡ Aetherion
