"""Command line for Stage 1 retrieval, validation, and registry maintenance only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .errors import PublicationEngineError
from .manifest import build_manifest, load_manifest, retrieve_observation, write_manifest
from .registry import registry_row, update_registry
from .validation import validate_manifest


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="zenetism-publication",
        description="Publication Engine v2 Stage 1 (public read-only interfaces only)",
    )
    commands = root.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser(
        "manifest", help="retrieve public records and generate a structured manifest"
    )
    manifest.add_argument("--repository", required=True, help="GitHub owner/repository")
    manifest.add_argument("--branch", default="main")
    manifest.add_argument("--directory", required=True)
    manifest.add_argument("--filename", required=True)
    manifest.add_argument("--zenodo", required=True, help="exact DOI, concept DOI, URL, or record id")
    manifest.add_argument("--output", type=Path)

    validate = commands.add_parser(
        "validate", help="retrieve public records and fail closed against a governed manifest"
    )
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--report", type=Path)

    registry = commands.add_parser(
        "registry", help="update the CSV registry from a manifest and passing validation report"
    )
    registry.add_argument("--manifest", required=True, type=Path)
    registry.add_argument("--validation-report", required=True, type=Path)
    registry.add_argument("--registry", required=True, type=Path)
    registry.add_argument("--verification-date", required=True)
    registry.add_argument("--architect-approval-state", required=True)
    registry.add_argument("--notes", default="")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "manifest":
            result = build_manifest(
                retrieve_observation(
                    repository=args.repository,
                    branch=args.branch,
                    directory=args.directory,
                    canonical_filename=args.filename,
                    zenodo_identifier=args.zenodo,
                )
            )
            if args.output:
                write_manifest(result, args.output)
            _print_json(result)
            return 0

        if args.command == "validate":
            expected = load_manifest(args.manifest)
            observed = build_manifest(_retrieve_from_manifest(expected))
            report = validate_manifest(expected, observed).as_dict()
            if args.report:
                _write_json(args.report, report)
            _print_json(report)
            return 0 if report["passed"] else 1

        if args.command == "registry":
            manifest = load_manifest(args.manifest)
            validation_report = _read_json(args.validation_report)
            row = registry_row(
                manifest,
                validation_report,
                verification_date=args.verification_date,
                architect_approval_state=args.architect_approval_state,
                notes=args.notes,
            )
            update_registry(args.registry, row)
            _print_json(row)
            return 0
    except (PublicationEngineError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


def _retrieve_from_manifest(manifest: dict[str, Any]):
    github = _required_object(manifest, "github")
    zenodo = _required_object(manifest, "zenodo")
    return retrieve_observation(
        repository=_required_string(github, "repository"),
        branch=_required_string(github, "branch"),
        directory=_required_string(github, "directory"),
        canonical_filename=_required_string(github, "canonical_filename"),
        zenodo_identifier=_required_string(zenodo, "exact_version_doi"),
    )


def _required_object(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError(f"manifest field {key} must be an object")
    return result


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"manifest field {key} is required")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False))


if __name__ == "__main__":
    raise SystemExit(main())
