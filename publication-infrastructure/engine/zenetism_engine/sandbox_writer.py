"""Sandbox-only draft planning, recovery, continuation, and exact validation."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote, urlsplit

from .archival import prepare_archival_copy
from .errors import (
    DraftValidationError,
    PublicationEngineError,
    SandboxRequestError,
    SandboxSafetyError,
)
from .sandbox_boundary import (
    SANDBOX_API_BASE,
    SANDBOX_ORIGIN,
    RuntimeSandboxCredentials,
    require_sandbox_request_url,
)
from .sandbox_metadata import SandboxDraftPackage, serialize_sandbox_draft
from .sandbox_verification import (
    FAILED,
    PASSED_API,
    PASSED_VISUAL,
    VISUAL_VERIFICATION_REQUIRED,
    ArchitectVisualConfirmation,
    FieldVerification,
    VerificationReport,
)

_RECORD_ID_RE = re.compile(r"[A-Za-z0-9-]+")
_REQUEST_METHODS = frozenset({"GET", "POST", "PUT"})
_DRAFT_ID_TOKEN = "{sandbox_draft_id}"
_SUPPORTED_DOI_PATHS = ("doi", "metadata.doi", "pids.doi.identifier")


class SandboxTransport(Protocol):
    """Minimal transport surface needed for an unpublished Sandbox draft."""

    def request(
        self,
        method: str,
        url: str,
        *,
        credentials: RuntimeSandboxCredentials,
        json_body: object | None = None,
        binary_body: bytes | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DraftRequest:
    method: str
    path: str
    purpose: str
    json_body: object | None = None
    binary_summary: dict[str, Any] | None = None
    condition: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "method": self.method,
            "url": f"{SANDBOX_API_BASE}{self.path}",
            "purpose": self.purpose,
        }
        if self.json_body is not None:
            result["json_body"] = deepcopy(self.json_body)
        if self.binary_summary is not None:
            result["binary_body"] = deepcopy(self.binary_summary)
        if self.condition is not None:
            result["condition"] = self.condition
        return result


@dataclass(frozen=True)
class SandboxDraftPlan:
    mode: str
    source_record_id: str | None
    sandbox_draft_id: str | None
    package: SandboxDraftPackage
    requests: tuple[DraftRequest, ...]

    def audit_summary(self) -> dict[str, Any]:
        result = {
            "operation": "prepare_unpublished_sandbox_draft",
            "mode": self.mode,
            "sandbox_api_base": SANDBOX_API_BASE,
            "authentication": "runtime environment only; value omitted",
            "final_release_action_available": False,
            "package": self.package.audit_summary(),
            "requests": [item.as_dict() for item in self.requests],
        }
        if self.sandbox_draft_id is not None:
            result["sandbox_draft_id"] = self.sandbox_draft_id
        return result


@dataclass(frozen=True)
class SandboxDraftRecovery:
    """Non-sensitive identity sufficient to resume one created Sandbox draft."""

    draft_id: str
    record_id: str | None
    edit_url: str
    preview_url: str
    creation_result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "record_id": self.record_id,
            "edit_url": self.edit_url,
            "preview_url": self.preview_url,
            "creation_result": deepcopy(self.creation_result),
        }


@dataclass(frozen=True)
class SandboxDraftResult:
    dry_run: bool
    audit: dict[str, Any]
    draft: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.dry_run:
            status = "dry_run_only"
        elif self.validation is not None and self.validation.get("complete") is True:
            status = "unpublished_sandbox_draft_validated"
        else:
            status = "unpublished_sandbox_draft_visual_verification_required"
        result = {
            "dry_run": self.dry_run,
            "status": status,
            "audit": deepcopy(self.audit),
        }
        if self.draft is not None:
            result["draft"] = deepcopy(self.draft)
        if self.validation is not None:
            result["validation"] = deepcopy(self.validation)
        return result


class UrllibSandboxTransport:
    """Fixed-host transport with no redirect following and no write retries."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_RejectRedirects())

    def request(
        self,
        method: str,
        url: str,
        *,
        credentials: RuntimeSandboxCredentials,
        json_body: object | None = None,
        binary_body: bytes | None = None,
    ) -> dict[str, Any]:
        method = _require_method(method)
        safe_url = require_sandbox_request_url(url)
        if json_body is not None and binary_body is not None:
            raise SandboxSafetyError("a Sandbox request cannot mix JSON and binary bodies")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {credentials.token}",
            "User-Agent": "zenetism-publication-engine-stage2b",
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif binary_body is not None:
            data = binary_body
            headers["Content-Type"] = "application/octet-stream"

        request = urllib.request.Request(safe_url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} returned HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} could not be completed"
            ) from None
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} returned invalid JSON"
            ) from None
        if not isinstance(value, dict):
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} returned a non-object JSON value"
            )
        return value


class SandboxDraftWriter:
    """Prepare or execute one manifest-controlled, unpublished Sandbox draft."""

    def __init__(
        self,
        *,
        transport: SandboxTransport | None = None,
        credential_loader: Callable[[], RuntimeSandboxCredentials] | None = None,
    ) -> None:
        self._transport = transport or UrllibSandboxTransport()
        self._credential_loader = (
            credential_loader or RuntimeSandboxCredentials.from_environment
        )

    def plan(
        self,
        manifest: object,
        *,
        repository_root: str | Path,
        mode: str = "create",
        source_record_id: str | None = None,
        sandbox_draft_id: str | None = None,
    ) -> SandboxDraftPlan:
        mode, source_record_id, sandbox_draft_id = _require_mode(
            mode, source_record_id, sandbox_draft_id
        )
        archival_copy = prepare_archival_copy(manifest, repository_root=repository_root)
        package = serialize_sandbox_draft(manifest, archival_copy)
        return SandboxDraftPlan(
            mode=mode,
            source_record_id=source_record_id,
            sandbox_draft_id=sandbox_draft_id,
            package=package,
            requests=_planned_requests(mode, source_record_id, sandbox_draft_id, package),
        )

    def run(
        self,
        manifest: object,
        *,
        repository_root: str | Path,
        mode: str = "create",
        source_record_id: str | None = None,
        sandbox_draft_id: str | None = None,
        dry_run: bool = True,
        architect_visual_confirmation: ArchitectVisualConfirmation | None = None,
    ) -> SandboxDraftResult:
        plan = self.plan(
            manifest,
            repository_root=repository_root,
            mode=mode,
            source_record_id=source_record_id,
            sandbox_draft_id=sandbox_draft_id,
        )
        audit = plan.audit_summary()
        audit["dry_run"] = dry_run
        if dry_run:
            audit["requests_sent"] = 0
            return SandboxDraftResult(dry_run=True, audit=audit)
        return self._execute(
            plan,
            audit,
            architect_visual_confirmation=architect_visual_confirmation,
        )

    def _execute(
        self,
        plan: SandboxDraftPlan,
        audit: dict[str, Any],
        *,
        architect_visual_confirmation: ArchitectVisualConfirmation | None,
    ) -> SandboxDraftResult:
        credentials = self._credential_loader()
        transport = self._transport
        package = plan.package
        source_concept_doi: str | None = None
        requests_sent = 0

        def send(
            method: str,
            path: str,
            *,
            json_body: object | None = None,
            binary_body: bytes | None = None,
        ) -> dict[str, Any]:
            nonlocal requests_sent
            result = _send(
                transport,
                credentials,
                method,
                path,
                json_body=json_body,
                binary_body=binary_body,
            )
            requests_sent += 1
            audit["requests_sent"] = requests_sent
            return result

        if plan.mode == "new-version":
            source_path = f"/records/{_record_segment(plan.source_record_id)}"
            source = send("GET", source_path)
            source_concept_doi = _required_path(source, "parent.pids.doi.identifier", str)
            started = send("POST", f"{source_path}/versions")
        elif plan.mode == "resume":
            draft_id = _record_segment(plan.sandbox_draft_id)
            draft_path = f"/records/{draft_id}/draft"
            started = send("GET", draft_path)
        else:
            started = send(
                "POST",
                "/records",
                json_body=package.create_payload,
            )

        recovery = _draft_recovery(
            started,
            expected_draft_id=plan.sandbox_draft_id if plan.mode == "resume" else None,
        )
        audit["recovery"] = recovery.as_dict()
        draft_id = recovery.draft_id
        draft_path = f"/records/{draft_id}/draft"

        try:
            existing_doi: str | None = None
            if plan.mode == "resume":
                validate_resume_draft(started, expected_draft_id=draft_id)
                existing_doi = sandbox_doi_from_response(started, required=False)
                source_concept_doi = _optional_path(
                    started, "parent.pids.doi.identifier"
                )
                if not isinstance(source_concept_doi, str):
                    source_concept_doi = None

            if existing_doi is None:
                reserved = send("POST", f"{draft_path}/pids/doi")
                reserved_doi = sandbox_doi_from_response(reserved)
                audit["doi_reservation"] = "reserved_during_current_execution"
            else:
                reserved_doi = existing_doi
                audit["doi_reservation"] = "preserved_existing_reservation"

            send(
                "POST",
                f"{draft_path}/files",
                json_body=[{"key": package.archival_copy.archival_filename}],
            )
            filename = quote(package.archival_copy.archival_filename, safe="")
            file_path = f"{draft_path}/files/{filename}"
            send(
                "PUT",
                f"{file_path}/content",
                binary_body=package.archival_copy.payload,
            )
            send("POST", f"{file_path}/commit")
            send("PUT", draft_path, json_body=package.saved_payload)
            reloaded = send("GET", draft_path)
            reloaded_files = send("GET", f"{draft_path}/files")
            reloaded_file = send("GET", file_path)
            validation = validate_saved_draft(
                package,
                reloaded,
                reloaded_file,
                file_collection=reloaded_files,
                expected_draft_id=draft_id,
                reserved_doi=reserved_doi,
                source_concept_doi=source_concept_doi,
                architect_visual_confirmation=architect_visual_confirmation,
            )
            audit["saved_draft_id"] = draft_id
            audit["validation_passed"] = validation["complete"]
            audit["visual_verification_required"] = validation[
                "visual_verification_required"
            ]
            return SandboxDraftResult(
                dry_run=False,
                audit=audit,
                draft=_safe_draft_summary(package, reloaded),
                validation=validation,
            )
        except PublicationEngineError as exc:
            exc.attach_recovery(recovery.as_dict())
            raise


def validate_saved_draft(
    package: SandboxDraftPackage,
    draft: object,
    file_record: object,
    *,
    file_collection: object | None = None,
    expected_draft_id: str | None = None,
    reserved_doi: str | None = None,
    source_concept_doi: str | None = None,
    architect_visual_confirmation: ArchitectVisualConfirmation | None = None,
) -> dict[str, Any]:
    """Validate a reloaded unpublished draft through explicit channels."""
    if not isinstance(draft, dict) or not isinstance(file_record, dict):
        raise DraftValidationError("Sandbox read-back must contain JSON objects")
    if file_collection is not None and not isinstance(file_collection, dict):
        raise DraftValidationError(
            "Sandbox file-collection read-back must contain a JSON object"
        )

    report, doi = _verification_report(
        package,
        draft,
        file_record,
        file_collection=file_collection,
        expected_draft_id=expected_draft_id,
        reserved_doi=reserved_doi,
        source_concept_doi=source_concept_doi,
        architect_visual_confirmation=architect_visual_confirmation,
    )
    failures = [
        item.detail or f"{item.field} failed"
        for item in report.fields
        if item.state == FAILED
    ]
    if report.has_failures:
        raise DraftValidationError(
            "Sandbox draft read-back validation failed: " + "; ".join(failures)
        )

    archival = package.archival_copy
    result = report.as_dict()
    result.update({
        "draft_state": "unpublished",
        "metadata_exact": report.complete,
        "archival_filename": archival.archival_filename,
        "byte_size": archival.checksums.byte_size,
        "sha256": archival.checksums.sha256,
        "md5": archival.checksums.md5,
        "default_preview": archival.archival_filename,
        "reserved_doi": doi,
        "concept_doi_preserved": True,
    })
    return result


def _verification_report(
    package: SandboxDraftPackage,
    draft: dict[str, Any],
    file_record: dict[str, Any],
    *,
    file_collection: dict[str, Any] | None,
    expected_draft_id: str | None,
    reserved_doi: str | None,
    source_concept_doi: str | None,
    architect_visual_confirmation: ArchitectVisualConfirmation | None,
) -> tuple[VerificationReport, str | None]:
    fields: list[FieldVerification] = []
    expected_metadata = package.saved_payload["metadata"]

    try:
        observed_draft_id = _draft_id(draft)
    except SandboxRequestError as exc:
        observed_draft_id = None
        fields.append(
            _failed_field("draft.id", expected_draft_id, None, str(exc))
        )
    else:
        expected_id = expected_draft_id or observed_draft_id
        fields.append(
            _exact_field(
                "draft.id",
                expected_id,
                observed_draft_id,
                detail="draft identifier differs from the created draft identifier",
            )
        )

    unpublished_failures: list[str] = []
    _append_unpublished_failures(draft, unpublished_failures)
    state_observed = {
        key: draft.get(key)
        for key in ("status", "state", "submitted", "is_published")
        if key in draft
    }
    if unpublished_failures:
        fields.append(
            _failed_field(
                "draft.state",
                "unpublished_unsubmitted",
                state_observed,
                "; ".join(unpublished_failures),
            )
        )
    else:
        fields.append(
            FieldVerification(
                field="draft.state",
                state=PASSED_API,
                channel="api",
                expected="unpublished_unsubmitted",
                observed=state_observed,
            )
        )

    try:
        doi = sandbox_doi_from_response(draft)
    except SandboxRequestError as exc:
        doi = None
        fields.append(_failed_field("doi", reserved_doi, None, str(exc)))
    else:
        if reserved_doi is not None and doi != reserved_doi:
            fields.append(
                _failed_field(
                    "doi",
                    reserved_doi,
                    doi,
                    "reloaded DOI differs from the reserved DOI",
                )
            )
        elif doi in package.existing_dois_not_supplied:
            fields.append(
                _failed_field(
                    "doi",
                    "a new Sandbox DOI",
                    doi,
                    "reserved DOI duplicates a prior exact-version or concept DOI",
                )
            )
        else:
            fields.append(
                FieldVerification(
                    field="doi",
                    state=PASSED_API,
                    channel="api",
                    expected=reserved_doi or doi,
                    observed=doi,
                )
            )

    if source_concept_doi is not None:
        fields.append(
            _verify_supported_api_field(
                "parent.pids.doi.identifier",
                source_concept_doi,
                ((draft, "parent.pids.doi.identifier", _identity),),
                mismatch_detail=(
                    "draft concept DOI differs from the originating version family"
                ),
            )
        )

    fields.extend(
        [
            _verify_supported_api_field(
                "access",
                _normalize_access(package.saved_payload["access"]),
                (
                    (draft, "access", _normalize_access),
                    (draft, "metadata.access_right", _normalize_access),
                ),
            ),
            _verify_supported_api_field(
                "metadata.resource_type",
                _normalize_resource_type(expected_metadata["resource_type"]),
                ((draft, "metadata.resource_type", _normalize_resource_type),),
            ),
            _verify_supported_api_field(
                "metadata.title",
                expected_metadata["title"],
                ((draft, "metadata.title", _identity),),
            ),
            _verify_supported_api_field(
                "metadata.publication_date",
                expected_metadata["publication_date"],
                ((draft, "metadata.publication_date", _identity),),
            ),
            _verify_supported_api_field(
                "metadata.creators",
                _normalize_people(expected_metadata["creators"]),
                ((draft, "metadata.creators", _normalize_people),),
            ),
            _verify_supported_api_field(
                "metadata.contributors",
                _normalize_contributors(expected_metadata["contributors"]),
                ((draft, "metadata.contributors", _normalize_contributors),),
            ),
            _verify_supported_api_field(
                "metadata.description",
                expected_metadata["description"],
                ((draft, "metadata.description", _identity),),
            ),
            _verify_supported_api_field(
                "metadata.subjects",
                _normalize_subjects(expected_metadata["subjects"]),
                (
                    (draft, "metadata.subjects", _normalize_subjects),
                    (draft, "metadata.keywords", _normalize_subjects),
                ),
            ),
            _verify_supported_api_field(
                "metadata.version",
                expected_metadata["version"],
                ((draft, "metadata.version", _identity),),
            ),
            _verify_supported_api_field(
                "metadata.rights",
                _normalize_identifiers(expected_metadata["rights"]),
                (
                    (draft, "metadata.rights", _normalize_identifiers),
                    (draft, "metadata.license", _normalize_identifiers),
                ),
            ),
            _verify_supported_api_field(
                "metadata.languages",
                _normalize_identifiers(expected_metadata["languages"]),
                (
                    (draft, "metadata.languages", _normalize_identifiers),
                    (draft, "metadata.language", _normalize_identifiers),
                ),
            ),
            _verify_supported_api_field(
                "metadata.related_identifiers",
                _normalize_related_identifiers(
                    expected_metadata["related_identifiers"]
                ),
                (
                    (
                        draft,
                        "metadata.related_identifiers",
                        _normalize_related_identifiers,
                    ),
                ),
            ),
            _verify_supported_api_field(
                "custom_fields.code:codeRepository",
                package.saved_payload["custom_fields"]["code:codeRepository"],
                (
                    (draft, "custom_fields.code:codeRepository", _identity),
                    (draft, "metadata.custom.code:codeRepository", _identity),
                ),
            ),
        ]
    )

    expected_copyright = expected_metadata["copyright"]
    fields.append(
        _verify_copyright(
            draft,
            expected=expected_copyright,
            draft_id=observed_draft_id,
            confirmation=architect_visual_confirmation,
        )
    )

    file_sources: list[tuple[object, str, Callable[[Any], Any]]] = [
        (draft, "files.enabled", _identity)
    ]
    preview_sources: list[tuple[object, str, Callable[[Any], Any]]] = [
        (draft, "files.default_preview", _identity)
    ]
    if file_collection is not None:
        file_sources.append((file_collection, "enabled", _identity))
        preview_sources.append((file_collection, "default_preview", _identity))
    fields.extend(
        [
            _verify_supported_api_field(
                "files.enabled",
                True,
                tuple(file_sources),
            ),
            _verify_supported_api_field(
                "files.default_preview",
                package.archival_copy.archival_filename,
                tuple(preview_sources),
            ),
            _verify_supported_api_field(
                "file.key",
                package.archival_copy.archival_filename,
                ((file_record, "key", _identity),),
                mismatch_detail="file.key differs from the archival filename",
            ),
            _verify_supported_api_field(
                "file.size",
                package.archival_copy.checksums.byte_size,
                ((file_record, "size", _identity),),
                mismatch_detail="file.size differs from the canonical payload",
            ),
            _verify_supported_api_field(
                "file.checksum",
                f"md5:{package.archival_copy.checksums.md5}",
                ((file_record, "checksum", _identity),),
                mismatch_detail="file.checksum differs from the canonical payload",
            ),
            _verify_supported_api_field(
                "file.status",
                "completed",
                ((file_record, "status", _identity),),
                mismatch_detail="file.status must be completed",
            ),
        ]
    )
    return VerificationReport(tuple(fields)), doi


def _verify_supported_api_field(
    field: str,
    expected: Any,
    sources: tuple[tuple[object, str, Callable[[Any], Any]], ...],
    *,
    mismatch_detail: str | None = None,
) -> FieldVerification:
    observed: list[tuple[str, Any]] = []
    for container, path, normalizer in sources:
        present, raw = _path_value(container, path)
        if not present:
            continue
        try:
            normalized = normalizer(raw)
        except (KeyError, TypeError, ValueError):
            return _failed_field(
                field,
                expected,
                raw,
                f"{field} has an unsupported API representation at $.{path}",
            )
        observed.append((f"$.{path}", normalized))

    if not observed:
        return _failed_field(
            field,
            expected,
            None,
            f"{field} is missing from every supported API representation",
        )
    if any(value != expected for _, value in observed):
        rendered = (
            observed[0][1]
            if len(observed) == 1
            else {path: value for path, value in observed}
        )
        return _failed_field(
            field,
            expected,
            rendered,
            mismatch_detail or f"{field} differs",
        )
    rendered = (
        observed[0][1]
        if len(observed) == 1
        else {path: value for path, value in observed}
    )
    return FieldVerification(
        field=field,
        state=PASSED_API,
        channel="api",
        expected=expected,
        observed=rendered,
    )


def _verify_copyright(
    draft: dict[str, Any],
    *,
    expected: Any,
    draft_id: str | None,
    confirmation: ArchitectVisualConfirmation | None,
) -> FieldVerification:
    present, api_value = _path_value(draft, "metadata.copyright")
    if present:
        return _exact_field("metadata.copyright", expected, api_value)
    if confirmation is None:
        return FieldVerification(
            field="metadata.copyright",
            state=VISUAL_VERIFICATION_REQUIRED,
            channel="visual",
            expected=expected,
            observed=None,
            detail=(
                "metadata.copyright is unavailable through the supported Sandbox "
                "API read-back and requires explicit architect visual confirmation"
            ),
        )
    if draft_id is None:
        return _failed_field(
            "metadata.copyright",
            expected,
            None,
            "architect visual confirmation cannot be matched without a draft identifier",
            channel="visual",
        )
    try:
        confirmed, visual_value = confirmation.value_for(
            "metadata.copyright", expected_draft_id=draft_id
        )
    except DraftValidationError as exc:
        return _failed_field(
            "metadata.copyright", expected, None, str(exc), channel="visual"
        )
    if not confirmed:
        return FieldVerification(
            field="metadata.copyright",
            state=VISUAL_VERIFICATION_REQUIRED,
            channel="visual",
            expected=expected,
            observed=None,
            detail="architect visual confirmation does not include metadata.copyright",
        )
    if visual_value != expected:
        return _failed_field(
            "metadata.copyright",
            expected,
            visual_value,
            "architect-confirmed metadata.copyright differs",
            channel="visual",
        )
    return FieldVerification(
        field="metadata.copyright",
        state=PASSED_VISUAL,
        channel="visual",
        expected=expected,
        observed=visual_value,
        detail="explicit architect visual confirmation",
    )


def _exact_field(
    field: str,
    expected: Any,
    observed: Any,
    *,
    detail: str | None = None,
) -> FieldVerification:
    if type(expected) is not type(observed) or expected != observed:
        return _failed_field(field, expected, observed, detail or f"{field} differs")
    return FieldVerification(
        field=field,
        state=PASSED_API,
        channel="api",
        expected=expected,
        observed=observed,
    )


def _failed_field(
    field: str,
    expected: Any,
    observed: Any,
    detail: str,
    *,
    channel: str = "api",
) -> FieldVerification:
    return FieldVerification(
        field=field,
        state=FAILED,
        channel=channel,
        expected=expected,
        observed=observed,
        detail=detail,
    )


def _identity(value: Any) -> Any:
    return deepcopy(value)


def _normalize_access(value: Any) -> tuple[str, str]:
    if isinstance(value, str) and value.casefold() == "open":
        return ("public", "public")
    if isinstance(value, dict):
        record = value.get("record")
        files = value.get("files")
        if isinstance(record, str) and isinstance(files, str):
            return (record.casefold(), files.casefold())
    raise ValueError("unsupported access representation")


def _normalize_resource_type(value: Any) -> str:
    if not isinstance(value, dict):
        raise ValueError("resource type must be an object")
    identifier = value.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier.casefold()
    type_value = value.get("type")
    subtype = value.get("subtype")
    if isinstance(type_value, str) and isinstance(subtype, str):
        return f"{type_value}-{subtype}".casefold()
    raise ValueError("unsupported resource type representation")


def _normalize_people(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("people must be a list")
    return [_render_person(item) for item in value]


def _render_person(value: Any) -> str:
    if not isinstance(value, dict):
        raise ValueError("person must be an object")
    name = value.get("name")
    if isinstance(name, str) and name:
        return name
    person = value.get("person_or_org")
    if not isinstance(person, dict):
        raise ValueError("person_or_org is missing")
    family = person.get("family_name")
    given = person.get("given_name", "")
    if not isinstance(family, str) or not family or not isinstance(given, str):
        raise ValueError("person name is malformed")
    return family if not given else f"{family}, {given}"


def _normalize_contributors(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("contributors must be a list")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("contributor must be an object")
        role = item.get("role")
        if isinstance(role, dict):
            role = role.get("id")
        if role is None:
            role = item.get("type")
        if not isinstance(role, str) or not role:
            raise ValueError("contributor role is missing")
        result.append({"name": _render_person(item), "role": role.casefold()})
    return result


def _normalize_subjects(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("subjects must be a list")
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, dict) and isinstance(item.get("subject"), str):
            result.append(item["subject"])
        else:
            raise ValueError("subject is malformed")
    return result


def _normalize_identifiers(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value.casefold()]
    if isinstance(value, dict):
        identifier = value.get("id")
        if isinstance(identifier, str) and identifier:
            return [identifier.casefold()]
    if not isinstance(value, list):
        raise ValueError("identifier collection must be a list")
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item.casefold())
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            result.append(item["id"].casefold())
        else:
            raise ValueError("identifier is malformed")
    return result


def _normalize_related_identifiers(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("related identifiers must be a list")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("related identifier must be an object")
        relation = item.get("relation_type", item.get("relation"))
        resource_type = item.get("resource_type")
        if isinstance(relation, dict):
            relation = relation.get("id")
        if isinstance(resource_type, dict):
            resource_type = resource_type.get("id")
        identifier = item.get("identifier")
        scheme = item.get("scheme")
        if not all(
            isinstance(candidate, str) and candidate
            for candidate in (identifier, scheme, relation, resource_type)
        ):
            raise ValueError("related identifier is malformed")
        result.append(
            {
                "identifier": identifier,
                "scheme": scheme.casefold(),
                "relation_type": relation.casefold(),
                "resource_type": resource_type.casefold(),
            }
        )
    return result


def validate_resume_draft(
    draft: object, *, expected_draft_id: str
) -> dict[str, Any]:
    """Fail unless one explicit existing draft is safe for Stage 2B continuation."""
    if not isinstance(draft, dict):
        raise DraftValidationError("Sandbox resume read-back must contain a JSON object")
    failures: list[str] = []
    try:
        observed_draft_id = _draft_id(draft)
    except SandboxRequestError as exc:
        failures.append(str(exc))
    else:
        if observed_draft_id != expected_draft_id:
            failures.append("resume draft identifier differs from the explicit draft identifier")
    _append_unpublished_failures(draft, failures)

    try:
        file_count = _draft_file_count(draft)
    except SandboxRequestError as exc:
        failures.append(str(exc))
        file_count = -1
    if file_count > 0:
        failures.append("resume draft must contain zero files before continuation")

    try:
        existing_doi = sandbox_doi_from_response(draft, required=False)
    except SandboxRequestError as exc:
        failures.append(str(exc))
        existing_doi = None

    if failures:
        raise DraftValidationError(
            "Sandbox resume validation failed: " + "; ".join(failures)
        )
    return {
        "passed": True,
        "draft_id": expected_draft_id,
        "draft_state": "unpublished_unsubmitted",
        "file_count": 0,
        "reserved_doi": existing_doi,
    }


def sandbox_doi_from_response(
    value: object, *, required: bool = True
) -> str | None:
    """Read supported Sandbox DOI representations and reject disagreement."""
    if not isinstance(value, dict):
        raise SandboxRequestError("Sandbox DOI response must contain a JSON object")
    observed: list[tuple[str, str]] = []
    for path in _SUPPORTED_DOI_PATHS:
        present, candidate = _path_value(value, path)
        if not present or candidate is None:
            continue
        if not isinstance(candidate, str) or not candidate or candidate != candidate.strip():
            raise SandboxRequestError(
                f"Sandbox DOI field $.{path} must contain a non-empty string"
            )
        observed.append((path, candidate))

    if not observed:
        if required:
            supported = ", ".join(f"$.{path}" for path in _SUPPORTED_DOI_PATHS)
            raise SandboxRequestError(
                f"Sandbox response is missing a supported DOI field: {supported}"
            )
        return None

    identifiers = {candidate for _, candidate in observed}
    if len(identifiers) != 1:
        paths = ", ".join(f"$.{path}" for path, _ in observed)
        raise SandboxRequestError(
            f"Sandbox response contains conflicting DOI values at {paths}"
        )
    return observed[0][1]


def _draft_recovery(
    value: dict[str, Any], *, expected_draft_id: str | None = None
) -> SandboxDraftRecovery:
    draft_id = _draft_id(value)
    if expected_draft_id is not None and draft_id != _record_segment(expected_draft_id):
        raise SandboxRequestError(
            "Sandbox draft response differs from the explicit draft identifier"
        )
    record_id = _optional_record_id(value.get("recid"))
    edit_url = f"{SANDBOX_ORIGIN}/uploads/{draft_id}"
    preview_url = f"{SANDBOX_ORIGIN}/records/{draft_id}?preview=1"
    creation_result: dict[str, Any] = {}
    for key in (
        "id",
        "recid",
        "conceptrecid",
        "created",
        "updated",
        "status",
        "state",
        "submitted",
    ):
        candidate = value.get(key)
        if isinstance(candidate, (str, int, bool)) and not isinstance(candidate, float):
            creation_result[key] = candidate
    creation_result["links"] = {
        "self": f"{SANDBOX_API_BASE}/records/{draft_id}/draft",
        "self_html": edit_url,
        "preview_html": preview_url,
    }
    return SandboxDraftRecovery(
        draft_id=draft_id,
        record_id=record_id,
        edit_url=edit_url,
        preview_url=preview_url,
        creation_result=creation_result,
    )


def _draft_id(value: dict[str, Any]) -> str:
    candidate = value.get("id")
    if candidate is None:
        candidate = value.get("recid")
    try:
        return _record_segment(candidate)
    except SandboxSafetyError:
        raise SandboxRequestError(
            "Sandbox response is missing a valid draft identifier"
        ) from None


def _optional_record_id(value: object) -> str | None:
    if value is None:
        return None
    try:
        return _record_segment(value)
    except SandboxSafetyError:
        raise SandboxRequestError(
            "Sandbox response contains an invalid record identifier"
        ) from None


def _append_unpublished_failures(
    draft: dict[str, Any], failures: list[str]
) -> None:
    if draft.get("status") not in {"draft", "new_version_draft"}:
        failures.append("draft.status must identify an unpublished draft")

    published_present = "is_published" in draft
    if published_present and draft.get("is_published") is not False:
        failures.append("draft.is_published must be explicitly false when present")

    state_present = "state" in draft
    if state_present and draft.get("state") != "unsubmitted":
        failures.append("draft.state must be unsubmitted when present")

    submitted_present = "submitted" in draft
    if submitted_present and draft.get("submitted") is not False:
        failures.append("draft.submitted must be explicitly false when present")

    if not published_present and not (
        state_present
        and draft.get("state") == "unsubmitted"
        and submitted_present
        and draft.get("submitted") is False
    ):
        failures.append(
            "draft must provide explicit unpublished or unsubmitted state markers"
        )


def _draft_file_count(draft: dict[str, Any]) -> int:
    present, files = _path_value(draft, "files")
    if not present:
        raise SandboxRequestError("Sandbox resume response is missing draft.files")
    if isinstance(files, list):
        return len(files)
    if isinstance(files, dict):
        entries_present, entries = _path_value(files, "entries")
        if entries_present and isinstance(entries, (dict, list)):
            return len(entries)
    raise SandboxRequestError(
        "Sandbox resume response contains an unsupported draft.files representation"
    )


def _path_value(value: object, path: str) -> tuple[bool, Any]:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _planned_requests(
    mode: str,
    source_record_id: str | None,
    sandbox_draft_id: str | None,
    package: SandboxDraftPackage,
) -> tuple[DraftRequest, ...]:
    draft_token = (
        _record_segment(sandbox_draft_id) if mode == "resume" else _DRAFT_ID_TOKEN
    )
    draft_path = f"/records/{draft_token}/draft"
    filename = quote(package.archival_copy.archival_filename, safe="")
    file_path = f"{draft_path}/files/{filename}"
    requests: list[DraftRequest] = []
    if mode == "new-version":
        source = _record_segment(source_record_id)
        requests.extend(
            [
                DraftRequest("GET", f"/records/{source}", "read originating version family"),
                DraftRequest(
                    "POST", f"/records/{source}/versions", "create unpublished test-version draft"
                ),
            ]
        )
    else:
        if mode == "resume":
            requests.append(
                DraftRequest(
                    "GET",
                    draft_path,
                    "verify the explicit existing unpublished Sandbox draft",
                )
            )
        else:
            requests.append(
                DraftRequest(
                    "POST",
                    "/records",
                    "create unpublished Sandbox deposit",
                    package.create_payload,
                )
            )
    requests.extend(
        [
            DraftRequest(
                "POST",
                f"{draft_path}/pids/doi",
                "reserve Sandbox DOI",
                condition=(
                    "only when the verified resume draft has no reserved DOI"
                    if mode == "resume"
                    else None
                ),
            ),
            DraftRequest(
                "POST",
                f"{draft_path}/files",
                "initialize archival file",
                [{"key": package.archival_copy.archival_filename}],
            ),
            DraftRequest(
                "PUT",
                f"{file_path}/content",
                "upload byte-identical archival payload",
                binary_summary={
                    "byte_size": package.archival_copy.checksums.byte_size,
                    "sha256": package.archival_copy.checksums.sha256,
                    "md5": package.archival_copy.checksums.md5,
                },
            ),
            DraftRequest("POST", f"{file_path}/commit", "complete archival file upload"),
            DraftRequest(
                "PUT",
                draft_path,
                "save approved metadata and explicit default Preview",
                package.saved_payload,
            ),
            DraftRequest("GET", draft_path, "reload saved draft"),
            DraftRequest(
                "GET",
                f"{draft_path}/files",
                "read saved file collection and default Preview",
            ),
            DraftRequest("GET", file_path, "read saved archival file metadata"),
        ]
    )
    return tuple(requests)


def _send(
    transport: SandboxTransport,
    credentials: RuntimeSandboxCredentials,
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    binary_body: bytes | None = None,
) -> dict[str, Any]:
    method = _require_method(method)
    url = require_sandbox_request_url(f"{SANDBOX_API_BASE}{path}")
    try:
        result = transport.request(
            method,
            url,
            credentials=credentials,
            json_body=json_body,
            binary_body=binary_body,
        )
    except SandboxRequestError:
        raise
    except Exception:
        raise SandboxRequestError(
            f"Sandbox {method} {_safe_path(url)} could not be completed"
        ) from None
    if not isinstance(result, dict):
        raise SandboxRequestError(
            f"Sandbox {method} {_safe_path(url)} returned a non-object JSON value"
        )
    return result


def _require_method(value: str) -> str:
    method = value.upper()
    if method not in _REQUEST_METHODS:
        raise SandboxSafetyError(f"Sandbox request method is not permitted: {method}")
    return method


def _require_mode(
    mode: str,
    source_record_id: str | None,
    sandbox_draft_id: str | None,
) -> tuple[str, str | None, str | None]:
    if mode not in {"create", "new-version", "resume"}:
        raise SandboxSafetyError("mode must be create, new-version, or resume")
    if mode == "new-version":
        if sandbox_draft_id is not None:
            raise SandboxSafetyError(
                "--sandbox-draft-id is valid only in resume mode"
            )
        return mode, _record_segment(source_record_id), None
    if mode == "resume":
        if source_record_id is not None:
            raise SandboxSafetyError(
                "--source-record-id is valid only in new-version mode"
            )
        return mode, None, _record_segment(sandbox_draft_id)
    if source_record_id is not None:
        raise SandboxSafetyError("--source-record-id is valid only in new-version mode")
    if sandbox_draft_id is not None:
        raise SandboxSafetyError("--sandbox-draft-id is valid only in resume mode")
    return mode, None, None


def _record_segment(value: object) -> str:
    if isinstance(value, bool):
        raise SandboxSafetyError("Sandbox record id contains unsupported characters")
    text = str(value) if value is not None else ""
    if not _RECORD_ID_RE.fullmatch(text):
        raise SandboxSafetyError("Sandbox record id contains unsupported characters")
    return text


def _required_path(value: dict[str, Any], path: str, expected_type: object) -> Any:
    result = _optional_path(value, path)
    if not isinstance(result, expected_type):
        raise SandboxRequestError(f"Sandbox response is missing required field {path}")
    return result


def _optional_path(value: object, path: str) -> Any:
    present, result = _path_value(value, path)
    return result if present else None


def _safe_draft_summary(
    package: SandboxDraftPackage, draft: dict[str, Any]
) -> dict[str, Any]:
    """Return validated fields without authentication-bound details."""
    doi = sandbox_doi_from_response(draft)
    return {
        "id": _draft_id(draft),
        "record_id": _optional_record_id(draft.get("recid")),
        "status": draft.get("status"),
        "state": draft.get("state"),
        "is_published": draft.get("is_published"),
        "submitted": draft.get("submitted"),
        "doi": doi,
        "pids": {"doi": {"identifier": doi}},
        "parent": {
            "pids": {
                "doi": {"identifier": _optional_path(draft, "parent.pids.doi.identifier")}
            }
        },
        "expected_default_preview": package.archival_copy.archival_filename,
    }


def _safe_path(url: str) -> str:
    return urlsplit(url).path


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        raise SandboxSafetyError("Sandbox request redirect was rejected")
