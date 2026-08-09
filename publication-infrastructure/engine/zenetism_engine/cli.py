"""Interface for Stage 1, Sandbox drafts, and local Stage 3A planning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .errors import PublicationEngineError
from .manifest import build_manifest, load_manifest, retrieve_observation, write_manifest
from .production_draft import ProductionDraftPlanner, load_json_object
from .registry import registry_row, update_registry
from .sandbox_verification import load_architect_visual_confirmation
from .sandbox_writer import SandboxDraftWriter
from .validation import validate_manifest


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="zenetism-publication",
        description=(
            "Publication Engine v2 public reads, Sandbox drafts, and local-only "
            "Stage 3A production-draft planning"
        ),
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
        "validate", help="retrieve public records and fail closed against an approved manifest"
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

    sandbox = commands.add_parser(
        "sandbox-draft",
        help="plan an unpublished Sandbox draft; no request is sent unless explicitly enabled",
    )
    sandbox.add_argument("--manifest", required=True, type=Path)
    sandbox.add_argument("--repository-root", required=True, type=Path)
    sandbox.add_argument("--mode", choices=("create", "new-version"), default="create")
    sandbox.add_argument("--source-record-id")
    sandbox.add_argument(
        "--execute-sandbox-write",
        action="store_true",
        help="send the planned requests to the fixed Zenodo Sandbox host",
    )
    sandbox.add_argument("--audit", type=Path)

    resume = commands.add_parser(
        "sandbox-resume",
        help=(
            "plan continuation of one explicit existing unpublished Sandbox draft; "
            "no request is sent unless explicitly enabled"
        ),
    )
    resume.add_argument("--manifest", required=True, type=Path)
    resume.add_argument("--repository-root", required=True, type=Path)
    resume.add_argument("--sandbox-draft-id", required=True)
    resume.add_argument(
        "--visual-confirmation",
        type=Path,
        help="draft-specific architect confirmation for API-unavailable UI fields",
    )
    resume.add_argument(
        "--execute-sandbox-write",
        action="store_true",
        help=(
            "verify and continue only the explicit draft on the fixed Zenodo Sandbox host"
        ),
    )
    resume.add_argument("--audit", type=Path)

    production = commands.add_parser(
        "production-draft-plan",
        help=(
            "build a local new-version production-draft plan; no credential is read "
            "and no request can be sent"
        ),
    )
    production.add_argument("--manifest", required=True, type=Path)
    production.add_argument("--repository-root", required=True, type=Path)
    production.add_argument("--registry", required=True, type=Path)
    production.add_argument("--family-observation", required=True, type=Path)
    production.add_argument("--intent", required=True, type=Path)
    production.add_argument("--audit", type=Path)
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

        if args.command == "sandbox-draft":
            result = SandboxDraftWriter().run(
                load_manifest(args.manifest),
                repository_root=args.repository_root,
                mode=args.mode,
                source_record_id=args.source_record_id,
                dry_run=not args.execute_sandbox_write,
            ).as_dict()
            if args.audit:
                _write_json(args.audit, result)
            _print_json(result)
            return _sandbox_result_status(result)

        if args.command == "sandbox-resume":
            confirmation = (
                load_architect_visual_confirmation(args.visual_confirmation)
                if args.visual_confirmation
                else None
            )
            result = SandboxDraftWriter().run(
                load_manifest(args.manifest),
                repository_root=args.repository_root,
                mode="resume",
                sandbox_draft_id=args.sandbox_draft_id,
                dry_run=not args.execute_sandbox_write,
                architect_visual_confirmation=confirmation,
            ).as_dict()
            if args.audit:
                _write_json(args.audit, result)
            _print_json(result)
            return _sandbox_result_status(result)

        if args.command == "production-draft-plan":
            result = ProductionDraftPlanner().plan(
                load_manifest(args.manifest),
                repository_root=args.repository_root,
                registry_path=args.registry,
                family_observation=load_json_object(
                    args.family_observation,
                    label="production family observation",
                ),
                intent=load_json_object(
                    args.intent,
                    label="production draft intent",
                ),
            ).as_dict()
            if args.audit:
                _write_json(args.audit, result)
            _print_json(result)
            return 0
    except (PublicationEngineError, OSError, ValueError, KeyError) as exc:
        diagnostic: dict[str, Any] = {"error": str(exc)}
        if isinstance(exc, PublicationEngineError) and exc.recovery is not None:
            diagnostic["recovery"] = exc.recovery
        print(json.dumps(diagnostic, ensure_ascii=False), file=sys.stderr)
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


def _sandbox_result_status(value: dict[str, Any]) -> int:
    if value.get("dry_run") is True:
        return 0
    validation = value.get("validation")
    return 0 if isinstance(validation, dict) and validation.get("complete") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
