"""Confined production new-version transport for Stage 3B local review."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from .errors import (
    PublicationEngineError,
    ProductionFamilyError,
    ProductionRequestError,
    ProductionSafetyError,
)
from .production_boundary import (
    PRODUCTION_REQUIRED_SCOPES,
    PRODUCTION_TOKEN_ENV,
    RuntimeProductionCredentials,
    production_environment,
)
from .production_draft import (
    ProductionDraftPlan,
    ProductionDraftRecovery,
    ProductionFamilySnapshot,
    _record_id,
    _supported_doi,
    _verified_unpublished_draft,
)
from .production_validation import (
    ArchitectProductionVisualConfirmation,
    validate_production_metadata,
)

_NUMERIC_ID = re.compile(r"[0-9]+")
_EXACT_DOI_PATHS = ("doi", "metadata.doi", "pids.doi.identifier")
_CONCEPT_DOI_PATHS = (
    "conceptdoi",
    "metadata.conceptdoi",
    "parent.pids.doi.identifier",
)


class ProductionDraftTransport(Protocol):
    """Exact Stage 3B operations, with no generic request or action surface."""

    @property
    def new_version_created(self) -> bool: ...

    def read_family(self, plan: ProductionDraftPlan) -> dict[str, Any]: ...

    def open_new_version_draft(
        self, plan: ProductionDraftPlan
    ) -> ProductionDraftRecovery: ...

    def reload_bound_legacy_draft(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]: ...

    def reload_bound_draft(self, plan: ProductionDraftPlan) -> dict[str, Any]: ...

    def delete_inherited_archival_file(self, plan: ProductionDraftPlan) -> None: ...

    def upload_approved_archival_file(self, plan: ProductionDraftPlan) -> None: ...

    def save_approved_metadata(self, plan: ProductionDraftPlan) -> None: ...


@dataclass(frozen=True)
class ProductionDraftExecutionResult:
    """Safe review result for one unpublished production draft."""

    recovery: ProductionDraftRecovery
    new_version_created: bool
    exact_version_doi: str
    validation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        complete = self.validation.get("complete") is True
        return {
            "stage": "3B",
            "status": (
                "unpublished_production_draft_validated"
                if complete
                else "unpublished_production_draft_visual_verification_required"
            ),
            "draft_id": self.recovery.draft_id,
            "new_version_created": self.new_version_created,
            "second_draft_created": False,
            "exact_version_doi": self.exact_version_doi,
            "recovery": self.recovery.as_dict(),
            "validation": deepcopy(self.validation),
            "credential_boundary": {
                "runtime_environment_variable": PRODUCTION_TOKEN_ENV,
                "required_external_scopes": list(PRODUCTION_REQUIRED_SCOPES),
                "credential_value_persisted": False,
                "authorization_header_persisted": False,
            },
            "final_release_action_available": False,
            "standalone_deposit_available": False,
            "terminal_state": "stop_for_architect_review_before_publication",
        }


class ProductionDraftExecutor:
    """Continue one validated plan through a bound unpublished draft."""

    def __init__(self, transport: ProductionDraftTransport) -> None:
        self._transport = transport
        self._used = False
        self._recovery: ProductionDraftRecovery | None = None

    @property
    def recovery(self) -> ProductionDraftRecovery | None:
        return self._recovery

    def prepare(
        self,
        plan: ProductionDraftPlan,
        *,
        architect_visual_confirmation: ArchitectProductionVisualConfirmation | None = None,
    ) -> ProductionDraftExecutionResult:
        if self._used:
            raise ProductionSafetyError(
                "one production executor cannot initiate or resume a second draft"
            )
        if not isinstance(plan, ProductionDraftPlan):
            raise ProductionSafetyError(
                "production transport requires a validated production draft plan"
            )
        self._used = True

        observed_family = ProductionFamilySnapshot.from_object(
            self._transport.read_family(plan)
        )
        if observed_family.as_dict() != plan.family.as_dict():
            raise ProductionFamilyError(
                "production transport family read-back differs from the validated plan"
            )

        recovery = self._transport.open_new_version_draft(plan)
        self._recovery = recovery
        try:
            legacy_draft = self._transport.reload_bound_legacy_draft(plan)
            _require_bound_unpublished_draft(plan, recovery, legacy_draft)
            initial_draft = self._transport.reload_bound_draft(plan)
            _require_bound_unpublished_draft(plan, recovery, initial_draft)
            file_state = _classify_file_state(plan, initial_draft)

            if file_state == "inherited":
                self._transport.delete_inherited_archival_file(plan)
                self._transport.upload_approved_archival_file(plan)
            elif file_state == "empty":
                self._transport.upload_approved_archival_file(plan)

            self._transport.save_approved_metadata(plan)

            final_legacy_draft = self._transport.reload_bound_legacy_draft(plan)
            _require_bound_unpublished_draft(plan, recovery, final_legacy_draft)
            final_draft = self._transport.reload_bound_draft(plan)
            _require_bound_unpublished_draft(plan, recovery, final_draft)
            _require_approved_file(plan, final_draft)
            exact_version_doi = _supported_doi(
                final_draft,
                _EXACT_DOI_PATHS,
                "production draft exact-version DOI",
            )
            if exact_version_doi in {
                plan.family.concept_doi,
                plan.family.latest.exact_version_doi,
            }:
                raise ProductionFamilyError(
                    "production draft did not receive a distinct exact-version DOI"
                )
            report = validate_production_metadata(
                plan.metadata_payload,
                final_draft,
                draft_id=recovery.draft_id,
                architect_visual_confirmation=architect_visual_confirmation,
            )
            return ProductionDraftExecutionResult(
                recovery=recovery,
                new_version_created=self._transport.new_version_created,
                exact_version_doi=exact_version_doi,
                validation=report.as_dict(),
            )
        except PublicationEngineError as exc:
            exc.attach_recovery(recovery.as_dict())
            raise


class _RequestKind(str, Enum):
    READ_FAMILY_RECORD = "read_family_record"
    READ_FAMILY_MEMBERS = "read_family_members"
    READ_CURRENT_DEPOSITION = "read_current_deposition"
    INITIATE_NEW_VERSION = "initiate_new_version"
    READ_LEGACY_DRAFT = "read_legacy_draft"
    READ_DRAFT = "read_draft"
    DELETE_INHERITED_FILE = "delete_inherited_file"
    INITIALIZE_APPROVED_FILE = "initialize_approved_file"
    WRITE_APPROVED_FILE = "write_approved_file"
    COMPLETE_APPROVED_FILE = "complete_approved_file"
    SAVE_APPROVED_METADATA = "save_approved_metadata"


_ENDPOINT_RULES: dict[_RequestKind, tuple[str, re.Pattern[str]]] = {
    _RequestKind.READ_FAMILY_RECORD: ("GET", re.compile(r"/api/records/[0-9]+")),
    _RequestKind.READ_FAMILY_MEMBERS: (
        "GET",
        re.compile(r"/api/records/[0-9]+/versions"),
    ),
    _RequestKind.READ_CURRENT_DEPOSITION: (
        "GET",
        re.compile(r"/api/deposit/depositions/[0-9]+"),
    ),
    _RequestKind.INITIATE_NEW_VERSION: (
        "POST",
        re.compile(r"/api/deposit/depositions/[0-9]+/actions/newversion"),
    ),
    _RequestKind.READ_LEGACY_DRAFT: (
        "GET",
        re.compile(r"/api/deposit/depositions/[0-9]+"),
    ),
    _RequestKind.READ_DRAFT: (
        "GET",
        re.compile(r"/api/records/[0-9]+/draft"),
    ),
    _RequestKind.DELETE_INHERITED_FILE: (
        "DELETE",
        re.compile(r"/api/records/[0-9]+/draft/files/[^/?#]+"),
    ),
    _RequestKind.INITIALIZE_APPROVED_FILE: (
        "POST",
        re.compile(r"/api/records/[0-9]+/draft/files"),
    ),
    _RequestKind.WRITE_APPROVED_FILE: (
        "PUT",
        re.compile(r"/api/records/[0-9]+/draft/files/[^/?#]+/content"),
    ),
    _RequestKind.COMPLETE_APPROVED_FILE: (
        "POST",
        re.compile(r"/api/records/[0-9]+/draft/files/[^/?#]+/commit"),
    ),
    _RequestKind.SAVE_APPROVED_METADATA: (
        "PUT",
        re.compile(r"/api/records/[0-9]+/draft"),
    ),
}


@dataclass(frozen=True)
class _BoundProductionRequest:
    kind: _RequestKind
    method: str
    path: str
    json_body: object | None = None
    binary_body: bytes | None = None

    def __post_init__(self) -> None:
        rule = _ENDPOINT_RULES.get(self.kind)
        if rule is None or self.method != rule[0] or rule[1].fullmatch(self.path) is None:
            raise ProductionSafetyError(
                "production request falls outside the closed Stage 3B endpoint surface"
            )
        if self.json_body is not None and self.binary_body is not None:
            raise ProductionSafetyError(
                "production request cannot mix JSON and binary bodies"
            )

    @property
    def url(self) -> str:
        return f"{production_environment().origin}{self.path}"


class UrllibProductionDraftTransport:
    """Fixed-host transport whose public methods derive every ID from one plan."""

    def __init__(
        self,
        credentials: RuntimeProductionCredentials,
        *,
        timeout: float = 30.0,
    ) -> None:
        if not isinstance(credentials, RuntimeProductionCredentials):
            raise ProductionSafetyError(
                "production transport requires runtime production credentials"
            )
        self._credentials = credentials
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_RejectRedirects())
        self._active_plan: ProductionDraftPlan | None = None
        self._verified_plan_fingerprint: str | None = None
        self._current_deposition_verified = False
        self._bound_plan_fingerprint: str | None = None
        self._bound_draft_id: str | None = None
        self._recovery: ProductionDraftRecovery | None = None
        self._new_version_created = False
        self._legacy_draft_verified = False
        self._modern_draft_verified = False
        self._file_state: str | None = None
        self._approved_file_initialized = False
        self._approved_file_written = False

    @classmethod
    def from_environment(cls, *, timeout: float = 30.0) -> "UrllibProductionDraftTransport":
        """Construct the later live transport only from the separate runtime value."""
        return cls(RuntimeProductionCredentials.from_environment(), timeout=timeout)

    @property
    def new_version_created(self) -> bool:
        return self._new_version_created

    def read_family(self, plan: ProductionDraftPlan) -> dict[str, Any]:
        self._require_unbound_plan(plan)
        self._activate_plan(plan)
        source = _numeric_id(plan.source_record_id)
        record = self._send(
            _BoundProductionRequest(
                _RequestKind.READ_FAMILY_RECORD,
                "GET",
                f"/api/records/{source}",
            )
        )
        page = self._send(
            _BoundProductionRequest(
                _RequestKind.READ_FAMILY_MEMBERS,
                "GET",
                f"/api/records/{source}/versions",
            )
        )
        links = page.get("links")
        links = links if isinstance(links, dict) else {}
        if links.get("next") not in {None, ""}:
            raise ProductionFamilyError(
                "production family read-back requires unsupported pagination"
            )
        hits = page.get("hits")
        hits = hits if isinstance(hits, dict) else {}
        members = hits.get("hits")
        if not isinstance(members, list) or not members:
            raise ProductionFamilyError(
                "production family read-back contains no explicit members"
            )
        concept_doi = _supported_doi(
            record,
            _CONCEPT_DOI_PATHS,
            "production family concept DOI",
        )
        observation = {
            "concept_doi": concept_doi,
            "latest": record,
            "members": members,
        }
        observed_family = ProductionFamilySnapshot.from_object(observation)
        if observed_family.as_dict() != plan.family.as_dict():
            raise ProductionFamilyError(
                "production transport family read-back differs from the validated plan"
            )
        self._verified_plan_fingerprint = plan.manifest_fingerprint
        return observation

    def open_new_version_draft(
        self, plan: ProductionDraftPlan
    ) -> ProductionDraftRecovery:
        self._require_unbound_plan(plan)
        if self._verified_plan_fingerprint != plan.manifest_fingerprint:
            raise ProductionSafetyError(
                "production new-version initiation requires exact family read-back verification"
            )
        source = _numeric_id(plan.source_record_id)
        current = self._send(
            _BoundProductionRequest(
                _RequestKind.READ_CURRENT_DEPOSITION,
                "GET",
                f"/api/deposit/depositions/{source}",
            )
        )
        _require_current_deposition(plan, current)
        self._current_deposition_verified = True
        existing = _latest_draft_id(current, required=False)
        if existing is not None and existing != source:
            return self._bind(plan, existing, current)

        created = self._send(
            _BoundProductionRequest(
                _RequestKind.INITIATE_NEW_VERSION,
                "POST",
                f"/api/deposit/depositions/{source}/actions/newversion",
            )
        )
        draft_id = _new_version_draft_id(plan, created)
        if draft_id == source:
            raise ProductionSafetyError(
                "new-version response did not identify a distinct unpublished draft"
            )
        recovery = self._bind(plan, draft_id, created)
        self._new_version_created = True
        return recovery

    def reload_bound_legacy_draft(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]:
        draft_id = self._require_bound_plan(plan)
        value = self._send(
            _BoundProductionRequest(
                _RequestKind.READ_LEGACY_DRAFT,
                "GET",
                f"/api/deposit/depositions/{draft_id}",
            )
        )
        recovery = self._require_recovery()
        _require_bound_unpublished_draft(plan, recovery, value)
        self._legacy_draft_verified = True
        return value

    def reload_bound_draft(self, plan: ProductionDraftPlan) -> dict[str, Any]:
        draft_id = self._require_bound_plan(plan)
        value = self._send(
            _BoundProductionRequest(
                _RequestKind.READ_DRAFT,
                "GET",
                f"/api/records/{draft_id}/draft",
            )
        )
        recovery = self._require_recovery()
        _require_bound_unpublished_draft(plan, recovery, value)
        self._file_state = _classify_file_state(plan, value)
        self._modern_draft_verified = True
        return value

    def delete_inherited_archival_file(self, plan: ProductionDraftPlan) -> None:
        draft_id = self._require_write_ready(plan)
        if self._file_state != "inherited":
            raise ProductionSafetyError(
                "production file deletion requires the exact inherited archival file"
            )
        filename = _approved_filename(
            plan.registry_identity.get("zenodo_archival_filename"),
            label="inherited archival filename",
        )
        self._send(
            _BoundProductionRequest(
                _RequestKind.DELETE_INHERITED_FILE,
                "DELETE",
                f"/api/records/{draft_id}/draft/files/{quote(filename, safe='')}",
            ),
            allow_empty=True,
        )

    def upload_approved_archival_file(self, plan: ProductionDraftPlan) -> None:
        draft_id = self._require_write_ready(plan)
        if self._file_state != "empty":
            raise ProductionSafetyError(
                "production file upload requires an empty verified draft file collection"
            )
        filename = _approved_filename(
            plan.archival_copy.archival_filename,
            label="approved archival filename",
        )
        encoded = quote(filename, safe="")
        self._send(
            _BoundProductionRequest(
                _RequestKind.INITIALIZE_APPROVED_FILE,
                "POST",
                f"/api/records/{draft_id}/draft/files",
                json_body=[{"key": filename}],
            )
        )
        self._send(
            _BoundProductionRequest(
                _RequestKind.WRITE_APPROVED_FILE,
                "PUT",
                f"/api/records/{draft_id}/draft/files/{encoded}/content",
                binary_body=plan.archival_copy.payload,
            )
        )
        self._send(
            _BoundProductionRequest(
                _RequestKind.COMPLETE_APPROVED_FILE,
                "POST",
                f"/api/records/{draft_id}/draft/files/{encoded}/commit",
            )
        )

    def save_approved_metadata(self, plan: ProductionDraftPlan) -> None:
        draft_id = self._require_write_ready(plan)
        if self._file_state != "approved":
            raise ProductionSafetyError(
                "production metadata save requires the approved archival payload"
            )
        self._send(
            _BoundProductionRequest(
                _RequestKind.SAVE_APPROVED_METADATA,
                "PUT",
                f"/api/records/{draft_id}/draft",
                json_body=plan.metadata_payload,
            )
        )

    def _bind(
        self,
        plan: ProductionDraftPlan,
        draft_id: str,
        result: dict[str, Any],
    ) -> ProductionDraftRecovery:
        if self._bound_draft_id is not None:
            raise ProductionSafetyError(
                "production transport is already bound to one recovered draft"
            )
        draft_id = _numeric_id(draft_id)
        origin = production_environment().origin
        recovery = ProductionDraftRecovery(
            draft_id=draft_id,
            record_id=None,
            edit_url=f"{origin}/uploads/{draft_id}",
            preview_url=f"{origin}/records/{draft_id}?preview=1",
            creation_result=_safe_result(result),
        )
        self._bound_plan_fingerprint = plan.manifest_fingerprint
        self._bound_draft_id = draft_id
        self._recovery = recovery
        return recovery

    def _require_unbound_plan(self, plan: ProductionDraftPlan) -> None:
        if not isinstance(plan, ProductionDraftPlan):
            raise ProductionSafetyError(
                "production transport requires a validated production draft plan"
            )
        if self._bound_draft_id is not None:
            raise ProductionSafetyError(
                "production transport cannot select or create a second draft"
            )
        if (
            self._active_plan is not None
            and self._active_plan.manifest_fingerprint != plan.manifest_fingerprint
        ):
            raise ProductionSafetyError(
                "production transport cannot switch to a different validated plan"
            )

    def _activate_plan(self, plan: ProductionDraftPlan) -> None:
        if self._active_plan is None:
            self._active_plan = plan

    def _require_bound_plan(self, plan: ProductionDraftPlan) -> str:
        if (
            not isinstance(plan, ProductionDraftPlan)
            or self._bound_plan_fingerprint != plan.manifest_fingerprint
            or self._bound_draft_id is None
        ):
            raise ProductionSafetyError(
                "production draft operation differs from the bound validated plan"
            )
        return self._bound_draft_id

    def _require_recovery(self) -> ProductionDraftRecovery:
        if self._recovery is None:
            raise ProductionSafetyError(
                "production transport has no preserved draft recovery identity"
            )
        return self._recovery

    def _require_write_ready(self, plan: ProductionDraftPlan) -> str:
        draft_id = self._require_bound_plan(plan)
        if not self._legacy_draft_verified or not self._modern_draft_verified:
            raise ProductionSafetyError(
                "production draft mutation requires verified legacy and draft read-back"
            )
        return draft_id

    def _send(
        self,
        request_value: _BoundProductionRequest,
        *,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(request_value, _BoundProductionRequest):
            raise ProductionSafetyError(
                "production transport accepts only a confined request value"
            )
        self._validate_request_against_session(request_value)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._credentials.token}",
            "User-Agent": "zenetism-publication-engine-stage3b",
        }
        data: bytes | None = None
        if request_value.json_body is not None:
            data = json.dumps(request_value.json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif request_value.binary_body is not None:
            data = request_value.binary_body
            headers["Content-Type"] = "application/octet-stream"
        request = urllib.request.Request(
            request_value.url,
            data=data,
            headers=headers,
            method=request_value.method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise ProductionRequestError(
                f"production {request_value.method} {request_value.path} returned HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProductionRequestError(
                f"production {request_value.method} {request_value.path} could not be completed"
            ) from None
        if not raw and allow_empty:
            value: dict[str, Any] = {}
        else:
            try:
                decoded = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ProductionRequestError(
                    f"production {request_value.method} {request_value.path} returned invalid JSON"
                ) from None
            if not isinstance(decoded, dict):
                raise ProductionRequestError(
                    f"production {request_value.method} {request_value.path} returned a non-object JSON value"
                )
            value = decoded
        self._advance_request_state(request_value)
        return value

    def _validate_request_against_session(
        self, request_value: _BoundProductionRequest
    ) -> None:
        plan = self._active_plan
        if plan is None:
            raise ProductionSafetyError(
                "production request requires an active validated plan"
            )
        source = _numeric_id(plan.source_record_id)
        source_paths = {
            _RequestKind.READ_FAMILY_RECORD: f"/api/records/{source}",
            _RequestKind.READ_FAMILY_MEMBERS: f"/api/records/{source}/versions",
            _RequestKind.READ_CURRENT_DEPOSITION: (
                f"/api/deposit/depositions/{source}"
            ),
            _RequestKind.INITIATE_NEW_VERSION: (
                f"/api/deposit/depositions/{source}/actions/newversion"
            ),
        }
        expected_source_path = source_paths.get(request_value.kind)
        if expected_source_path is not None:
            if request_value.path != expected_source_path:
                raise ProductionSafetyError(
                    "production request record differs from the active validated plan"
                )
            if (
                request_value.kind
                in {
                    _RequestKind.READ_CURRENT_DEPOSITION,
                    _RequestKind.INITIATE_NEW_VERSION,
                }
                and self._verified_plan_fingerprint != plan.manifest_fingerprint
            ):
                raise ProductionSafetyError(
                    "production deposition request requires exact family verification"
                )
            if (
                request_value.kind is _RequestKind.INITIATE_NEW_VERSION
                and not self._current_deposition_verified
            ):
                raise ProductionSafetyError(
                    "production new-version request requires current-deposition verification"
                )
            return

        draft_id = self._bound_draft_id
        if draft_id is None:
            raise ProductionSafetyError(
                "production draft request requires a bound recovered draft"
            )
        approved_filename = _approved_filename(
            plan.archival_copy.archival_filename,
            label="approved archival filename",
        )
        inherited_filename = _approved_filename(
            plan.registry_identity.get("zenodo_archival_filename"),
            label="inherited archival filename",
        )
        approved_segment = quote(approved_filename, safe="")
        inherited_segment = quote(inherited_filename, safe="")
        draft_paths = {
            _RequestKind.READ_LEGACY_DRAFT: (
                f"/api/deposit/depositions/{draft_id}"
            ),
            _RequestKind.READ_DRAFT: f"/api/records/{draft_id}/draft",
            _RequestKind.DELETE_INHERITED_FILE: (
                f"/api/records/{draft_id}/draft/files/{inherited_segment}"
            ),
            _RequestKind.INITIALIZE_APPROVED_FILE: (
                f"/api/records/{draft_id}/draft/files"
            ),
            _RequestKind.WRITE_APPROVED_FILE: (
                f"/api/records/{draft_id}/draft/files/{approved_segment}/content"
            ),
            _RequestKind.COMPLETE_APPROVED_FILE: (
                f"/api/records/{draft_id}/draft/files/{approved_segment}/commit"
            ),
            _RequestKind.SAVE_APPROVED_METADATA: (
                f"/api/records/{draft_id}/draft"
            ),
        }
        if request_value.path != draft_paths.get(request_value.kind):
            raise ProductionSafetyError(
                "production request differs from the bound recovered draft operation"
            )
        mutation_kinds = {
            _RequestKind.DELETE_INHERITED_FILE,
            _RequestKind.INITIALIZE_APPROVED_FILE,
            _RequestKind.WRITE_APPROVED_FILE,
            _RequestKind.COMPLETE_APPROVED_FILE,
            _RequestKind.SAVE_APPROVED_METADATA,
        }
        if request_value.kind not in mutation_kinds:
            return
        self._require_write_ready(plan)
        if request_value.kind is _RequestKind.DELETE_INHERITED_FILE:
            if self._file_state != "inherited":
                raise ProductionSafetyError(
                    "production file deletion differs from the verified inherited file state"
                )
        elif request_value.kind is _RequestKind.INITIALIZE_APPROVED_FILE:
            if (
                self._file_state != "empty"
                or request_value.json_body != [{"key": approved_filename}]
            ):
                raise ProductionSafetyError(
                    "production file initialization differs from the approved payload"
                )
        elif request_value.kind is _RequestKind.WRITE_APPROVED_FILE:
            if (
                not self._approved_file_initialized
                or request_value.binary_body != plan.archival_copy.payload
            ):
                raise ProductionSafetyError(
                    "production file content differs from the initialized approved payload"
                )
        elif request_value.kind is _RequestKind.COMPLETE_APPROVED_FILE:
            if not self._approved_file_written:
                raise ProductionSafetyError(
                    "production file completion requires the approved payload write"
                )
        elif (
            self._file_state != "approved"
            or request_value.json_body != plan.metadata_payload
        ):
            raise ProductionSafetyError(
                "production metadata request differs from the approved package"
            )

    def _advance_request_state(self, request_value: _BoundProductionRequest) -> None:
        if request_value.kind is _RequestKind.DELETE_INHERITED_FILE:
            self._file_state = "empty"
        elif request_value.kind is _RequestKind.INITIALIZE_APPROVED_FILE:
            self._approved_file_initialized = True
        elif request_value.kind is _RequestKind.WRITE_APPROVED_FILE:
            self._approved_file_written = True
        elif request_value.kind is _RequestKind.COMPLETE_APPROVED_FILE:
            self._file_state = "approved"
            self._approved_file_initialized = False
            self._approved_file_written = False


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _require_current_deposition(
    plan: ProductionDraftPlan, value: object
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionSafetyError(
            "production current-version response must contain a JSON object"
        )
    if _record_id(value) != plan.source_record_id:
        raise ProductionFamilyError(
            "production current deposition differs from the validated latest record"
        )
    exact_doi = _supported_doi(
        value,
        _EXACT_DOI_PATHS,
        "production current exact-version DOI",
    )
    if exact_doi != plan.family.latest.exact_version_doi:
        raise ProductionFamilyError(
            "production current deposition exact-version DOI differs from the validated family"
        )
    concept_values = _available_supported_values(value, _CONCEPT_DOI_PATHS)
    if concept_values:
        concept_doi = _supported_doi(
            value,
            _CONCEPT_DOI_PATHS,
            "production current concept DOI",
        )
        if concept_doi != plan.family.concept_doi:
            raise ProductionFamilyError(
                "production current deposition belongs to a different concept-DOI family"
            )
    metadata = value.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    version = metadata.get("version")
    if version is not None and version != plan.family.latest.version_label:
        raise ProductionFamilyError(
            "production current deposition version differs from the validated family"
        )
    if not (
        value.get("submitted") is True
        or value.get("status") == "published"
        or value.get("state") in {"done", "published"}
    ):
        raise ProductionSafetyError(
            "production current deposition is not the verified published family member"
        )
    return value


def _require_bound_unpublished_draft(
    plan: ProductionDraftPlan,
    recovery: ProductionDraftRecovery,
    value: object,
) -> dict[str, Any]:
    draft = _verified_unpublished_draft(
        value,
        expected_concept_doi=plan.family.concept_doi,
    )
    if _record_id(draft) != recovery.draft_id:
        raise ProductionSafetyError(
            "production draft read-back differs from the recovered draft identity"
        )
    if recovery.draft_id == plan.source_record_id:
        raise ProductionSafetyError(
            "production new-version draft must differ from the published originating record"
        )
    metadata = draft.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    version = metadata.get("version")
    permitted_versions = {
        plan.family.latest.version_label,
        plan.intent.next_version,
    }
    if version is not None and version not in permitted_versions:
        raise ProductionFamilyError(
            "production draft version differs from the approved family continuation"
        )
    return draft


def _classify_file_state(plan: ProductionDraftPlan, draft: dict[str, Any]) -> str:
    files = draft.get("files")
    if not isinstance(files, dict):
        raise ProductionSafetyError(
            "production draft read-back is missing its file collection"
        )
    if files.get("enabled") is not True:
        raise ProductionSafetyError("production draft files must remain enabled")
    entries = files.get("entries")
    if not isinstance(entries, dict):
        raise ProductionSafetyError(
            "production draft file collection must contain explicit entries"
        )
    if not entries:
        return "empty"
    if len(entries) != 1:
        raise ProductionSafetyError(
            "production draft contains an ambiguous file collection"
        )
    key, entry = next(iter(entries.items()))
    if not isinstance(entry, dict) or entry.get("key") != key:
        raise ProductionSafetyError(
            "production draft file identity is malformed"
        )
    inherited = plan.registry_identity["zenodo_archival_filename"]
    approved = plan.archival_copy.archival_filename
    if key == inherited:
        if entry.get("checksum") != plan.registry_identity["zenodo_checksum"]:
            raise ProductionSafetyError(
                "inherited production file differs from the validated registry identity"
            )
        if entry.get("size") != _inherited_file_size(plan):
            raise ProductionSafetyError(
                "inherited production file byte size differs from the published baseline"
            )
        return "inherited"
    if key == approved:
        _require_approved_file_entry(plan, entry)
        return "approved"
    raise ProductionSafetyError(
        "production draft contains a file outside the approved family continuation"
    )


def _inherited_file_size(plan: ProductionDraftPlan) -> int:
    baseline_size = plan.registry_identity.get("zenodo_byte_size")
    if baseline_size is None:
        return plan.archival_copy.checksums.byte_size
    if re.fullmatch(r"[1-9][0-9]*", baseline_size) is None:
        raise ProductionSafetyError(
            "published-baseline byte size is missing or malformed"
        )
    return int(baseline_size)


def _require_approved_file(
    plan: ProductionDraftPlan, draft: dict[str, Any]
) -> None:
    if _classify_file_state(plan, draft) != "approved":
        raise ProductionSafetyError(
            "production draft does not contain the approved archival payload"
        )
    files = draft["files"]
    if files.get("default_preview") != plan.archival_copy.archival_filename:
        raise ProductionSafetyError(
            "production draft default Preview differs from the approved archival file"
        )
    if files.get("order") != [plan.archival_copy.archival_filename]:
        raise ProductionSafetyError(
            "production draft file order differs from the approved archival file"
        )


def _require_approved_file_entry(
    plan: ProductionDraftPlan, entry: dict[str, Any]
) -> None:
    expected_checksum = f"md5:{plan.archival_copy.checksums.md5}"
    if entry.get("checksum") != expected_checksum:
        raise ProductionSafetyError(
            "production draft archival checksum differs from the approved payload"
        )
    if entry.get("size") != plan.archival_copy.checksums.byte_size:
        raise ProductionSafetyError(
            "production draft archival byte size differs from the approved payload"
        )


def _latest_draft_id(value: dict[str, Any], *, required: bool) -> str | None:
    links = value.get("links")
    links = links if isinstance(links, dict) else {}
    latest_draft = links.get("latest_draft")
    if latest_draft is None or latest_draft == "":
        if required:
            raise ProductionSafetyError(
                "new-version response is missing the supported latest_draft relation"
            )
        return None
    if not isinstance(latest_draft, str):
        raise ProductionSafetyError(
            "production latest_draft relation must be an HTTPS URL"
        )
    parsed = urlsplit(latest_draft)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProductionSafetyError(
            "production latest_draft relation contains an invalid port"
        ) from exc
    match = re.fullmatch(r"/api/deposit/depositions/([0-9]+)", parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "zenodo.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ProductionSafetyError(
            "production latest_draft relation falls outside the fixed production draft endpoint"
        )
    return _numeric_id(match.group(1))


def _new_version_draft_id(
    plan: ProductionDraftPlan, value: dict[str, Any]
) -> str:
    linked = _latest_draft_id(value, required=False)
    direct: str | None = None
    if (
        value.get("submitted") is False
        and value.get("state") in {None, "unsubmitted"}
        and value.get("is_published") in {None, False}
    ):
        try:
            draft = _verified_unpublished_draft(
                value,
                expected_concept_doi=plan.family.concept_doi,
            )
            direct = _record_id(draft)
        except (ProductionFamilyError, ProductionSafetyError):
            raise ProductionSafetyError(
                "new-version response contains an invalid direct draft identity"
            ) from None
    if linked is not None and direct is not None and linked != direct:
        raise ProductionSafetyError(
            "new-version response contains conflicting draft identities"
        )
    result = linked or direct
    if result is None:
        raise ProductionSafetyError(
            "new-version response is missing a supported draft identity or latest_draft relation"
        )
    return result


def _safe_result(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: deepcopy(value[key])
        for key in (
            "id",
            "recid",
            "conceptrecid",
            "created",
            "modified",
            "updated",
            "status",
            "state",
            "submitted",
        )
        if isinstance(value.get(key), (str, int, bool))
    }
    latest_draft = _latest_draft_id(value, required=False)
    if latest_draft is not None:
        result["latest_draft"] = (
            f"{production_environment().api_base}/deposit/depositions/{latest_draft}"
        )
    return result


def _available_supported_values(
    value: dict[str, Any], paths: tuple[str, ...]
) -> list[object]:
    result: list[object] = []
    for path in paths:
        current: object = value
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            if current is not None:
                result.append(current)
    return result


def _numeric_id(value: object) -> str:
    if isinstance(value, bool):
        raise ProductionSafetyError(
            "production record identifier contains unsupported characters"
        )
    text = str(value) if value is not None else ""
    if _NUMERIC_ID.fullmatch(text) is None:
        raise ProductionSafetyError(
            "production record identifier contains unsupported characters"
        )
    return text


def _approved_filename(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or "?" in value
        or "#" in value
    ):
        raise ProductionSafetyError(f"{label} is not a safe single filename")
    return value
