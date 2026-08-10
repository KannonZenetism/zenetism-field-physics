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
    ProductionValidationError,
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
    _explicit_family_latest_state,
    _fixed_family_relation_path,
    _record_id,
    _supported_doi,
    _verified_unpublished_draft,
)
from .production_validation import (
    ArchitectProductionVisualConfirmation,
    validate_production_metadata,
)

_NUMERIC_ID = re.compile(r"[0-9]+")
_ZENODO_EXACT_DOI = re.compile(r"10\.5281/zenodo\.[0-9]+")
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

    def resume_recovered_draft(
        self,
        plan: ProductionDraftPlan,
        recovery: ProductionDraftRecovery,
    ) -> ProductionDraftRecovery: ...

    def reload_bound_legacy_draft(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]: ...

    def reload_bound_draft(self, plan: ProductionDraftPlan) -> dict[str, Any]: ...

    def reload_bound_draft_files(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]: ...

    def delete_inherited_archival_file(self, plan: ProductionDraftPlan) -> None: ...

    def upload_approved_archival_file(self, plan: ProductionDraftPlan) -> None: ...

    def save_approved_metadata(self, plan: ProductionDraftPlan) -> None: ...

    def reserve_bound_draft_doi(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]: ...


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
        return self._prepare(
            plan,
            recovery=None,
            architect_visual_confirmation=architect_visual_confirmation,
        )

    def resume(
        self,
        plan: ProductionDraftPlan,
        recovery: ProductionDraftRecovery,
        *,
        architect_visual_confirmation: ArchitectProductionVisualConfirmation | None = None,
    ) -> ProductionDraftExecutionResult:
        return self._prepare(
            plan,
            recovery=recovery,
            architect_visual_confirmation=architect_visual_confirmation,
        )

    def _prepare(
        self,
        plan: ProductionDraftPlan,
        *,
        recovery: ProductionDraftRecovery | None,
        architect_visual_confirmation: ArchitectProductionVisualConfirmation | None,
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

        bound_recovery = (
            self._transport.open_new_version_draft(plan)
            if recovery is None
            else self._transport.resume_recovered_draft(plan, recovery)
        )
        self._recovery = bound_recovery
        try:
            legacy_draft = self._transport.reload_bound_legacy_draft(plan)
            _require_bound_unpublished_draft(plan, bound_recovery, legacy_draft)
            initial_draft = self._transport.reload_bound_draft(plan)
            _require_bound_unpublished_draft(plan, bound_recovery, initial_draft)
            file_state = _classify_file_state(plan, initial_draft)
            metadata_already_validated = False
            if file_state == "approved":
                try:
                    validate_production_metadata(
                        plan.metadata_payload,
                        initial_draft,
                        draft_id=bound_recovery.draft_id,
                    )
                    metadata_already_validated = True
                except ProductionValidationError as exc:
                    if not str(exc).startswith(
                        "production metadata read-back validation failed:"
                    ):
                        raise

            if file_state == "inherited":
                self._transport.delete_inherited_archival_file(plan)
                self._transport.upload_approved_archival_file(plan)
                self._transport.reload_bound_draft_files(plan)
            elif file_state == "empty":
                self._transport.upload_approved_archival_file(plan)
                self._transport.reload_bound_draft_files(plan)

            if not metadata_already_validated:
                self._transport.save_approved_metadata(plan)

            final_legacy_draft = self._transport.reload_bound_legacy_draft(plan)
            _require_bound_unpublished_draft(
                plan, bound_recovery, final_legacy_draft
            )
            final_draft = self._transport.reload_bound_draft(plan)
            _require_bound_unpublished_draft(plan, bound_recovery, final_draft)
            _require_approved_file(plan, final_draft)
            exact_version_doi = _reconciled_draft_doi(
                final_legacy_draft,
                final_draft,
                required=False,
            )
            if exact_version_doi is None:
                reservation = self._transport.reserve_bound_draft_doi(plan)
                final_legacy_draft = self._transport.reload_bound_legacy_draft(plan)
                _require_bound_unpublished_draft(
                    plan, bound_recovery, final_legacy_draft
                )
                final_draft = self._transport.reload_bound_draft(plan)
                _require_bound_unpublished_draft(
                    plan, bound_recovery, final_draft
                )
                _require_approved_file(plan, final_draft)
                reserved_response_doi = _reconciled_draft_doi(
                    reservation,
                    required=False,
                )
                exact_version_doi = _reconciled_draft_doi(
                    final_legacy_draft,
                    final_draft,
                    required=True,
                )
                if (
                    reserved_response_doi is not None
                    and reserved_response_doi != exact_version_doi
                ):
                    raise ProductionFamilyError(
                        "production DOI reservation response conflicts with draft read-back"
                    )
            if exact_version_doi is None:
                raise ProductionFamilyError(
                    "production draft exact-version DOI remains unavailable"
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
                draft_id=bound_recovery.draft_id,
                architect_visual_confirmation=architect_visual_confirmation,
            )
            return ProductionDraftExecutionResult(
                recovery=bound_recovery,
                new_version_created=self._transport.new_version_created,
                exact_version_doi=exact_version_doi,
                validation=report.as_dict(),
            )
        except PublicationEngineError as exc:
            exc.attach_recovery(bound_recovery.as_dict())
            raise


class _RequestKind(str, Enum):
    READ_FAMILY_RECORD = "read_family_record"
    READ_FAMILY_MEMBERS = "read_family_members"
    READ_FAMILY_LATEST_RELATION = "read_family_latest_relation"
    READ_CURRENT_DEPOSITION = "read_current_deposition"
    INITIATE_NEW_VERSION = "initiate_new_version"
    READ_LEGACY_DRAFT = "read_legacy_draft"
    READ_DRAFT = "read_draft"
    READ_DRAFT_FILES = "read_draft_files"
    DELETE_INHERITED_FILE = "delete_inherited_file"
    INITIALIZE_APPROVED_FILE = "initialize_approved_file"
    WRITE_APPROVED_FILE = "write_approved_file"
    COMPLETE_APPROVED_FILE = "complete_approved_file"
    SAVE_APPROVED_METADATA = "save_approved_metadata"
    RESERVE_DRAFT_DOI = "reserve_draft_doi"


_ENDPOINT_RULES: dict[_RequestKind, tuple[str, re.Pattern[str]]] = {
    _RequestKind.READ_FAMILY_RECORD: ("GET", re.compile(r"/api/records/[0-9]+")),
    _RequestKind.READ_FAMILY_MEMBERS: (
        "GET",
        re.compile(r"/api/records/[0-9]+/versions"),
    ),
    _RequestKind.READ_FAMILY_LATEST_RELATION: (
        "GET",
        re.compile(r"/api/records/[0-9]+/versions/latest"),
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
    _RequestKind.READ_DRAFT_FILES: (
        "GET",
        re.compile(r"/api/records/[0-9]+/draft/files"),
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
    _RequestKind.RESERVE_DRAFT_DOI: (
        "POST",
        re.compile(r"/api/records/[0-9]+/draft/pids/doi"),
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
        self._opener = urllib.request.build_opener(_ProductionRedirectBoundary())
        self._active_plan: ProductionDraftPlan | None = None
        self._verified_plan_fingerprint: str | None = None
        self._current_deposition_verified = False
        self._bound_plan_fingerprint: str | None = None
        self._bound_draft_id: str | None = None
        self._recovery: ProductionDraftRecovery | None = None
        self._new_version_created = False
        self._legacy_draft_verified = False
        self._modern_draft_verified = False
        self._last_legacy_draft: dict[str, Any] | None = None
        self._last_modern_draft: dict[str, Any] | None = None
        self._last_root_files: object = None
        self._file_state: str | None = None
        self._approved_file_initialized = False
        self._approved_file_written = False
        self._doi_reservation_attempted = False

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
        latest_relation_record: dict[str, Any] | None = None
        if any(
            _explicit_family_latest_state(item) is None
            for item in [record, *members]
        ):
            latest_path = _fixed_family_relation_path(
                record,
                relation="latest",
                expected_record_id=source,
            )
            latest_relation_record = self._send(
                _BoundProductionRequest(
                    _RequestKind.READ_FAMILY_LATEST_RELATION,
                    "GET",
                    latest_path,
                )
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
        if latest_relation_record is not None:
            observation["latest_relation_record"] = latest_relation_record
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

    def resume_recovered_draft(
        self,
        plan: ProductionDraftPlan,
        recovery: ProductionDraftRecovery,
    ) -> ProductionDraftRecovery:
        self._require_unbound_plan(plan)
        if self._verified_plan_fingerprint != plan.manifest_fingerprint:
            raise ProductionSafetyError(
                "production draft recovery requires exact family read-back verification"
            )
        _require_exact_recovery_identity(plan, recovery)
        preserved = ProductionDraftRecovery(
            draft_id=recovery.draft_id,
            record_id=recovery.record_id,
            edit_url=recovery.edit_url,
            preview_url=recovery.preview_url,
            creation_result=deepcopy(recovery.creation_result),
        )
        self._bound_plan_fingerprint = plan.manifest_fingerprint
        self._bound_draft_id = preserved.draft_id
        self._recovery = preserved
        return preserved

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
        self._last_legacy_draft = deepcopy(value)
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
        self._last_modern_draft = deepcopy(value)
        self._last_root_files = deepcopy(value.get("files"))
        self._modern_draft_verified = True
        files = self.reload_bound_draft_files(plan)
        combined = deepcopy(value)
        combined["files"] = files
        return combined

    def reload_bound_draft_files(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]:
        draft_id = self._require_bound_plan(plan)
        if not self._legacy_draft_verified or not self._modern_draft_verified:
            raise ProductionSafetyError(
                "production draft-files read requires verified legacy and root draft read-back"
            )
        value = self._send(
            _BoundProductionRequest(
                _RequestKind.READ_DRAFT_FILES,
                "GET",
                f"/api/records/{draft_id}/draft/files",
            )
        )
        files = _normalized_draft_files(
            self._last_root_files,
            value,
            expected_draft_id=draft_id,
        )
        self._file_state = _classify_file_state(plan, {"files": files})
        return files

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

    def reserve_bound_draft_doi(
        self, plan: ProductionDraftPlan
    ) -> dict[str, Any]:
        draft_id = self._require_write_ready(plan)
        if self._file_state != "approved":
            raise ProductionSafetyError(
                "production DOI reservation requires the approved archival payload"
            )
        if self._doi_reservation_attempted:
            raise ProductionSafetyError(
                "production transport cannot attempt a second DOI reservation"
            )
        if _reconciled_draft_doi(
            self._last_legacy_draft,
            self._last_modern_draft,
            required=False,
        ) is not None:
            raise ProductionSafetyError(
                "production draft already contains an explicit exact-version DOI"
            )
        self._doi_reservation_attempted = True
        return self._send(
            _BoundProductionRequest(
                _RequestKind.RESERVE_DRAFT_DOI,
                "POST",
                f"/api/records/{draft_id}/draft/pids/doi",
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
            if _is_existing_doi_reservation_error(request_value, exc):
                return {}
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
            _RequestKind.READ_FAMILY_LATEST_RELATION: (
                f"/api/records/{source}/versions/latest"
            ),
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
            _RequestKind.READ_DRAFT_FILES: (
                f"/api/records/{draft_id}/draft/files"
            ),
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
            _RequestKind.RESERVE_DRAFT_DOI: (
                f"/api/records/{draft_id}/draft/pids/doi"
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
            _RequestKind.RESERVE_DRAFT_DOI,
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
        elif request_value.kind is _RequestKind.RESERVE_DRAFT_DOI:
            if (
                self._file_state != "approved"
                or request_value.json_body is not None
                or request_value.binary_body is not None
                or not self._doi_reservation_attempted
            ):
                raise ProductionSafetyError(
                    "production DOI reservation differs from the bound draft-only operation"
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
            self._last_root_files = None
            self._file_state = "empty"
        elif request_value.kind is _RequestKind.INITIALIZE_APPROVED_FILE:
            self._last_root_files = None
            self._approved_file_initialized = True
        elif request_value.kind is _RequestKind.WRITE_APPROVED_FILE:
            self._last_root_files = None
            self._approved_file_written = True
        elif request_value.kind is _RequestKind.COMPLETE_APPROVED_FILE:
            self._last_root_files = None
            self._file_state = "approved"
            self._approved_file_initialized = False
            self._approved_file_written = False


class _ProductionRedirectBoundary(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        if request.get_method() != "GET" or code != 301:
            return None
        original = urlsplit(request.full_url)
        match = re.fullmatch(
            r"/api/records/([0-9]+)/versions/latest",
            original.path,
        )
        if (
            original.scheme != "https"
            or original.hostname != "zenodo.org"
            or original.username is not None
            or original.password is not None
            or original.port not in {None, 443}
            or original.query
            or original.fragment
            or match is None
        ):
            return None
        expected = f"https://zenodo.org/api/records/{match.group(1)}"
        if new_url != expected:
            return None
        return urllib.request.Request(
            new_url,
            headers=dict(request.header_items()),
            method="GET",
        )


def _require_exact_recovery_identity(
    plan: ProductionDraftPlan,
    recovery: ProductionDraftRecovery,
) -> None:
    if not isinstance(recovery, ProductionDraftRecovery):
        raise ProductionSafetyError(
            "production continuation requires a preserved recovery identity"
        )
    draft_id = _numeric_id(recovery.draft_id)
    if draft_id == plan.source_record_id:
        raise ProductionSafetyError(
            "production recovery draft must differ from the published originating record"
        )
    if recovery.record_id not in {None, draft_id}:
        raise ProductionSafetyError(
            "production recovery record identity differs from its draft identity"
        )
    origin = production_environment().origin
    if recovery.edit_url != f"{origin}/uploads/{draft_id}":
        raise ProductionSafetyError(
            "production recovery edit relation differs from the fixed draft identity"
        )
    if recovery.preview_url != f"{origin}/records/{draft_id}?preview=1":
        raise ProductionSafetyError(
            "production recovery preview relation differs from the fixed draft identity"
        )
    creation = recovery.creation_result
    allowed_creation_fields = {
        "id",
        "recid",
        "conceptrecid",
        "created",
        "modified",
        "updated",
        "status",
        "state",
        "submitted",
        "latest_draft",
    }
    if (
        not isinstance(creation, dict)
        or not set(creation).issubset(allowed_creation_fields)
        or any(
            not isinstance(value, (str, int, bool))
            for value in creation.values()
        )
    ):
        raise ProductionSafetyError(
            "production recovery creation result contains unsupported state"
        )
    observed_ids: list[str] = []
    for key in ("id", "recid"):
        if key in creation:
            observed_ids.append(_numeric_id(creation[key]))
    linked = _preserved_recovery_draft_id(creation)
    if linked is not None:
        observed_ids.append(linked)
    if not observed_ids or set(observed_ids) != {draft_id}:
        raise ProductionSafetyError(
            "production recovery creation result differs from the preserved draft"
        )
    concept_record_id = _concept_record_id(plan.family.concept_doi)
    if _numeric_id(creation.get("conceptrecid")) != concept_record_id:
        raise ProductionFamilyError(
            "production recovery creation result differs from the concept family"
        )
    if creation.get("submitted") is not False or creation.get("state") != "unsubmitted":
        raise ProductionSafetyError(
            "production recovery creation result is not explicitly unsubmitted"
        )


def _preserved_recovery_draft_id(value: dict[str, Any]) -> str | None:
    relation = value.get("latest_draft")
    if relation is None:
        return None
    if not isinstance(relation, str):
        raise ProductionSafetyError(
            "production recovery latest_draft relation must be an HTTPS URL"
        )
    parsed = urlsplit(relation)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProductionSafetyError(
            "production recovery latest_draft relation contains an invalid port"
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
        or relation
        != f"{production_environment().origin}{parsed.path}"
    ):
        raise ProductionSafetyError(
            "production recovery latest_draft relation falls outside the fixed draft endpoint"
        )
    return _numeric_id(match.group(1))


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


def _normalized_draft_files(
    root_files: object,
    dedicated_files: object,
    *,
    expected_draft_id: str,
) -> dict[str, Any]:
    if not isinstance(dedicated_files, dict):
        raise ProductionSafetyError(
            "production dedicated draft-files response must be an object"
        )
    _validate_draft_files_response_identity(
        dedicated_files,
        expected_draft_id=expected_draft_id,
    )
    if "entries" not in dedicated_files:
        raise ProductionSafetyError(
            "production dedicated draft-files response requires explicit entries"
        )
    entries = _normalized_file_entries(dedicated_files["entries"])
    root = _recognized_root_file_collection(root_files)
    if "entries" in root:
        root_entries = _normalized_file_entries(root["entries"])
        _require_root_file_entries_agree(root_entries, entries)
    enabled = _reconciled_file_configuration(
        root,
        dedicated_files,
        "enabled",
    )
    if not isinstance(enabled, bool):
        raise ProductionSafetyError(
            "production draft-files enabled state must be boolean"
        )
    default_preview = _reconciled_file_configuration(
        root,
        dedicated_files,
        "default_preview",
    )
    if default_preview is not None and (
        not isinstance(default_preview, str)
        or (default_preview and _approved_filename(
            default_preview,
            label="production default Preview filename",
        ) != default_preview)
    ):
        raise ProductionSafetyError(
            "production draft-files default Preview state is malformed"
        )
    order_value = _reconciled_file_configuration(
        root,
        dedicated_files,
        "order",
    )
    if not isinstance(order_value, list) or any(
        not isinstance(item, str)
        or _approved_filename(item, label="production file-order entry") != item
        for item in order_value
    ):
        raise ProductionSafetyError(
            "production draft-files order must be an explicit filename list"
        )
    if len(order_value) != len(set(order_value)):
        raise ProductionSafetyError(
            "production draft-files order contains duplicate filenames"
        )
    return {
        "enabled": enabled,
        "entries": entries,
        "default_preview": default_preview,
        "order": order_value,
    }


def _recognized_root_file_collection(value: object) -> dict[str, Any]:
    """Return only a complete root collection admitted as additional evidence."""
    required_fields = {"enabled", "entries", "default_preview", "order"}
    if not isinstance(value, dict) or not required_fields.issubset(value):
        return {}
    return value


def _normalized_file_entries(value: object) -> dict[str, dict[str, Any]]:
    observed: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                raise ProductionSafetyError(
                    "production draft-file entry must be an object"
                )
            key = item.get("key")
            observed.append((str(key) if isinstance(key, str) else "", item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                raise ProductionSafetyError(
                    "production draft-file entries must map filenames to objects"
                )
            if item.get("key") != key:
                raise ProductionSafetyError(
                    "production draft-file entry key differs from its filename"
                )
            observed.append((key, item))
    else:
        raise ProductionSafetyError(
            "production dedicated draft-files entries must be a list or object"
        )
    result: dict[str, dict[str, Any]] = {}
    for key, item in observed:
        if not key or _approved_filename(
            key,
            label="production draft-file entry filename",
        ) != key:
            raise ProductionSafetyError(
                "production draft-file entry filename is malformed"
            )
        if item.get("key") != key:
            raise ProductionSafetyError(
                "production draft-file entry key differs from its filename"
            )
        if key in result:
            raise ProductionSafetyError(
                "production draft-files response contains duplicate entries"
            )
        result[key] = deepcopy(item)
    return result


def _require_root_file_entries_agree(
    root_entries: dict[str, dict[str, Any]],
    dedicated_entries: dict[str, dict[str, Any]],
) -> None:
    if set(root_entries) != set(dedicated_entries):
        raise ProductionSafetyError(
            "production root and dedicated draft-file entry sets differ"
        )
    identity_fields = {"key", "checksum", "size", "status"}
    for key, root_entry in root_entries.items():
        dedicated_entry = dedicated_entries[key]
        for field in identity_fields.intersection(root_entry):
            if root_entry[field] != dedicated_entry.get(field):
                raise ProductionSafetyError(
                    "production root and dedicated draft-file identities differ"
                )


def _reconciled_file_configuration(
    root: dict[str, Any],
    dedicated: dict[str, Any],
    key: str,
) -> object:
    values = [
        container[key]
        for container in (root, dedicated)
        if key in container
    ]
    if not values:
        raise ProductionSafetyError(
            f"production draft-files response requires explicit {key} state"
        )
    if any(value != values[0] for value in values[1:]):
        raise ProductionSafetyError(
            f"production root and dedicated draft-files {key} states differ"
        )
    return deepcopy(values[0])


def _validate_draft_files_response_identity(
    value: dict[str, Any],
    *,
    expected_draft_id: str,
) -> None:
    for key in ("id", "record_id"):
        if key in value and _numeric_id(value[key]) != expected_draft_id:
            raise ProductionSafetyError(
                "production draft-files response differs from the bound draft identity"
            )
    links = value.get("links")
    if links is None:
        return
    if not isinstance(links, dict):
        raise ProductionSafetyError(
            "production draft-files links must be an object when present"
        )
    relation = links.get("self")
    if relation is None:
        return
    expected = (
        f"{production_environment().api_base}/records/"
        f"{expected_draft_id}/draft/files"
    )
    if relation != expected:
        raise ProductionSafetyError(
            "production draft-files self relation differs from the bound draft identity"
        )


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
        if files.get("default_preview") not in {None, ""}:
            raise ProductionSafetyError(
                "empty production draft files cannot identify a default Preview"
            )
        if files.get("order") != []:
            raise ProductionSafetyError(
                "empty production draft files require an explicit empty order"
            )
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
        _require_completed_file_entry(entry)
        if entry.get("checksum") != plan.registry_identity["zenodo_checksum"]:
            raise ProductionSafetyError(
                "inherited production file differs from the validated registry identity"
            )
        if entry.get("size") != _inherited_file_size(plan):
            raise ProductionSafetyError(
                "inherited production file byte size differs from the published baseline"
            )
        if files.get("default_preview") not in {None, "", inherited}:
            raise ProductionSafetyError(
                "inherited production file default Preview is contradictory"
            )
        if files.get("order") not in ([], [inherited]):
            raise ProductionSafetyError(
                "inherited production file order is contradictory"
            )
        return "inherited"
    if key == approved:
        _require_approved_file_entry(plan, entry)
        if files.get("default_preview") not in {None, "", approved}:
            raise ProductionSafetyError(
                "approved production file default Preview is contradictory"
            )
        if files.get("order") not in ([], [approved]):
            raise ProductionSafetyError(
                "approved production file order is contradictory"
            )
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
    if files.get("order") not in (
        [],
        [plan.archival_copy.archival_filename],
    ):
        raise ProductionSafetyError(
            "production draft file order differs from the approved archival file"
        )


def _require_approved_file_entry(
    plan: ProductionDraftPlan, entry: dict[str, Any]
) -> None:
    _require_completed_file_entry(entry)
    expected_checksum = f"md5:{plan.archival_copy.checksums.md5}"
    if entry.get("checksum") != expected_checksum:
        raise ProductionSafetyError(
            "production draft archival checksum differs from the approved payload"
        )
    if entry.get("size") != plan.archival_copy.checksums.byte_size:
        raise ProductionSafetyError(
            "production draft archival byte size differs from the approved payload"
        )


def _require_completed_file_entry(entry: dict[str, Any]) -> None:
    if entry.get("status") != "completed":
        raise ProductionSafetyError(
            "production draft file entry must be explicitly completed"
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


def _reconciled_draft_doi(
    *values: object,
    required: bool,
) -> str | None:
    observed: list[str] = []
    for value in values:
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ProductionFamilyError(
                "production draft DOI evidence must contain JSON objects"
            )
        for candidate in _available_supported_values(value, _EXACT_DOI_PATHS):
            if (
                not isinstance(candidate, str)
                or _ZENODO_EXACT_DOI.fullmatch(candidate) is None
            ):
                raise ProductionFamilyError(
                    "production draft DOI evidence contains an unsupported value"
                )
            observed.append(candidate)
    if not observed:
        if required:
            raise ProductionFamilyError(
                "production draft exact-version DOI is missing from supported paths"
            )
        return None
    if len(set(observed)) != 1:
        raise ProductionFamilyError(
            "production draft contains conflicting exact-version DOI representations"
        )
    return observed[0]


def _is_existing_doi_reservation_error(
    request_value: _BoundProductionRequest,
    error: urllib.error.HTTPError,
) -> bool:
    if (
        request_value.kind is not _RequestKind.RESERVE_DRAFT_DOI
        or error.code != 400
    ):
        return False
    try:
        decoded = json.loads(error.read())
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(decoded, dict) or decoded.get("status") != 400:
        return False
    errors = decoded.get("errors")
    if not isinstance(errors, list):
        return False
    for item in errors:
        if not isinstance(item, dict) or item.get("field") != "pids.doi":
            continue
        messages = item.get("messages")
        if isinstance(messages, list) and messages == [
            "A PID already exists for type doi"
        ]:
            return True
    return False


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


def _concept_record_id(value: object) -> str:
    if not isinstance(value, str):
        raise ProductionFamilyError(
            "production concept DOI must be a string"
        )
    match = re.fullmatch(r"10\.5281/zenodo\.([0-9]+)", value)
    if match is None:
        raise ProductionFamilyError(
            "production concept DOI has an unsupported form"
        )
    return match.group(1)


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
