# Publication Engine v2 — Stage 1

This directory implements the deterministic, read-only GitHub / Zenodo phase of the Zenetism Publication Engine v2 specification.

Stage 1:

- pins a GitHub branch snapshot and retrieves the current commit affecting one canonical file
- downloads the GitHub and Zenodo payloads without normalization or rewriting
- calculates byte size, SHA-256, and MD5 on both payloads
- retrieves the published Zenodo exact-version record and its version family
- stores `metadata.version`, the family index, and Zenodo's record revision in separate fields
- distinguishes the exact-version DOI from the all-versions concept DOI
- generates a structured JSON manifest
- validates every governed field exactly and fails on missing values
- updates the publication registry only from a passing validation report

There is no Publish command, Zenodo draft mutation, upload behavior, deletion behavior, token handling, Site mutation, or Substack interaction.

## Requirements

Python 3.11 or later. The implementation has no third-party runtime dependencies.

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

The Zenodo input may be an exact-version DOI, concept DOI, record URL, or numeric record identifier. When a concept DOI redirects to the latest version, both the requested identifier and the resolved exact-version family data remain structurally distinct inside the retrieval model. A governed manifest should record the resolved exact-version DOI.

## Validate Against Live Public State

```sh
PYTHONPATH=publication-infrastructure/engine python3 -m zenetism_engine validate \
  --manifest publication-infrastructure/manifests/zenetism-in-plain-language-v2.json \
  --report /tmp/zenetism-validation.json
```

Exit status is `0` only when every exact comparison and invariant passes. A mismatch returns `1`. Retrieval, schema, or command errors return `2`.

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

Rows are keyed by canonical filename. Existing unrelated rows are preserved.

## Tests

Run deterministic local tests:

```sh
PYTHONPATH=publication-infrastructure/engine \
  python3 -m unittest discover -s publication-infrastructure/engine/tests -v
```

Run the public-interface reference test as well:

```sh
ZENETISM_RUN_LIVE_TESTS=1 PYTHONPATH=publication-infrastructure/engine \
  python3 -m unittest discover -s publication-infrastructure/engine/tests -v
```

## Public-Interface Boundaries

The public interfaces expose the published file bytes, MD5, metadata, copyright, relations, repository URL, version family, and resulting default-preview filename. Zenodo does not publish a SHA-256 for this file, so Stage 1 calculates it from the downloaded bytes.

The public record exposes the resulting default-preview selection but does not prove whether a person explicitly selected it or Zenodo selected the only file automatically. It also does not expose draft-save history, architect approval, unpublished draft state, the DOI-question response used during deposit, or authentication-bound controls. Those values cannot receive a public-interface pass merely by inference.
