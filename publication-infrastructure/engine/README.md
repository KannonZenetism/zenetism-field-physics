# Publication Engine v2 — Stages 1 and 2A

This directory implements the deterministic GitHub / Zenodo comparison phase and the locally tested Zenodo Sandbox draft phase of the Publication Engine v2 specification.

Stage 1 remains read-only.

Stage 2A prepares or writes an unpublished Sandbox draft from an explicit architect-approved manifest.

Stage 2A does not include a final-release operation.

## Operational / Canonical Boundary

`publication-infrastructure/` contains operational implementation material.

It is not a doctrinal or terminological reference for Zenetism.

Canonical Zenetist terminology must follow designated canon files.

For publication work, these references hold canonical priority:

- `the-zenetist-canon/canonical-stabilization/terminological-lockdown-protocol.md`
- `the-zenetist-canon/canonical-stabilization/prose-formatting-reference.md`
- `the-zenetist-canon/canonical-stabilization/zenodo-description-standard.md`

The current operational specification remains `the-zenetist-canon/publication-infrastructure/zenetism-publication-engine-v2.md`.

Operational language and externally required technical terminology must never be carried into canonical Zenetist prose merely because they appear in implementation code, documentation, manifests, tests, or registry records.

## Stage 1

Stage 1:

- pins a GitHub branch snapshot and retrieves the current commit affecting one canonical file
- downloads the GitHub and Zenodo payloads without normalization or rewriting
- calculates byte size, SHA-256, and MD5 on both payloads
- retrieves the published Zenodo exact-version record and its version family
- stores `metadata.version`, the family index, and Zenodo's record revision in separate fields
- distinguishes the exact-version DOI from the all-versions concept DOI
- generates a structured JSON manifest
- validates every manifest-controlled field exactly and fails on missing values
- updates the publication registry only from a passing validation report

## Stage 2A

Stage 2A:

- requires an explicit manifest before preparing any request
- reads the canonical GitHub file from the local repository
- derives the exact `_vN` archival filename
- keeps the payload bytes, byte size, SHA-256, and MD5 unchanged
- serializes the manifest-controlled metadata without reordering keywords or rewriting descriptions
- creates a safe request summary before any request is sent
- makes dry-run mode the default
- creates either a new unpublished Sandbox deposit or a Sandbox test-version draft
- reserves a Sandbox DOI
- uploads and completes the archival file
- saves the metadata and explicit default Preview selection
- reloads the draft and file metadata
- fails unless every submitted field, the file identity, the default Preview, and the unpublished state pass read-back validation

## Fixed Safety Boundary

Mutation requests are fixed to:

`https://sandbox.zenodo.org/api`

The implementation rejects production `zenodo.org`, alternate hosts, insecure URLs, redirects, query credentials, and nonstandard ports.

Only GET, POST, and PUT are available to the Sandbox writer.

There is no final-release function, option, endpoint, or automatic path.

The Sandbox host is not configurable from the CLI or a manifest.

Authentication is loaded only when an explicitly enabled Sandbox write begins.

The runtime environment variable is named `ZENODO_SANDBOX_TOKEN`.

The value is not included in manifests, request summaries, logs, error messages, or repository files.

## Requirements

Python 3.11 or later is required.

The implementation has no third-party runtime dependencies.

## Generate a Manifest

From the repository root:

```sh
PYTHONPATH=publication-infrastructure/engine python3 -m zenetism_engine manifest \
  --repository KannonZenetism/zenetism-field-physics \
  --branch main \
  --directory the-zenetist-canon/introductory-orientation \
  --filename zenetism-in-plain-language.md \
  --zenodo 10.5281/zenodo.21830364 \
  --output publication-infrastructure/manifests/zenetism-in-plain-language-v2.json
```

The Zenodo input may be an exact-version DOI, concept DOI, record URL, or numeric record identifier.

When a concept DOI redirects to the latest version, both the requested identifier and the resolved exact-version family data remain structurally distinct inside the retrieval model.

A manifest should record the resolved exact-version DOI.

## Validate Against Live Public State

```sh
PYTHONPATH=publication-infrastructure/engine python3 -m zenetism_engine validate \
  --manifest publication-infrastructure/manifests/zenetism-in-plain-language-v2.json \
  --report /tmp/zenetism-validation.json
```

Exit status is `0` only when every exact comparison and invariant passes.

A mismatch returns `1`.

Retrieval, schema, or interface errors return `2`.

## Maintain the Registry

Registry mutation is local only and requires a passing validation report:

```sh
PYTHONPATH=publication-infrastructure/engine python3 -m zenetism_engine registry \
  --manifest publication-infrastructure/manifests/zenetism-in-plain-language-v2.json \
  --validation-report /tmp/zenetism-validation.json \
  --registry publication-infrastructure/zenetism-publication-registry.csv \
  --verification-date 2026-08-07 \
  --architect-approval-state "published reference cycle"
```

Rows are keyed by canonical filename.

Existing unrelated rows are preserved.

## Prepare a Sandbox Dry-Run

Dry-run is the default and does not read authentication or send a request:

```sh
PYTHONPATH=publication-infrastructure/engine python3 -m zenetism_engine sandbox-draft \
  --manifest publication-infrastructure/manifests/zenetism-in-plain-language-v2.json \
  --repository-root . \
  --audit /tmp/zenetism-sandbox-dry-run.json
```

The output includes the exact metadata payload, archival file identity, default Preview intent, request methods, fixed Sandbox URLs, and binary payload checksums.

For a future test-version draft, add `--mode new-version` and `--source-record-id` with the Sandbox record identifier from which the test version begins.

An actual Sandbox write additionally requires the explicit `--execute-sandbox-write` flag and runtime authentication.

Stage 2A was implemented and tested without supplying that authentication or connecting to a Sandbox account.

## Tests

Run the complete deterministic local suite:

```sh
PYTHONPATH=publication-infrastructure/engine \
  python3 -m unittest discover -s publication-infrastructure/engine/tests -v
```

Run the public-interface reference test as well:

```sh
ZENETISM_RUN_LIVE_TESTS=1 PYTHONPATH=publication-infrastructure/engine \
  python3 -m unittest discover -s publication-infrastructure/engine/tests -v
```

The live reference test performs public reads only.

It does not write to Zenodo.

## Public-Interface Boundaries

The public interfaces expose the published file bytes, MD5, metadata, copyright, relations, repository URL, version family, and resulting default-preview filename.

Zenodo does not publish a SHA-256 for this file, so Stage 1 calculates it from the downloaded bytes.

The public record exposes the resulting default-preview selection but does not prove whether a person explicitly selected it or Zenodo selected the only file automatically.

It also does not expose draft-save history, architect approval, unpublished draft state, the DOI-question response selected during deposit, or authentication-bound controls.

Those values cannot receive a public-interface pass merely by inference.
