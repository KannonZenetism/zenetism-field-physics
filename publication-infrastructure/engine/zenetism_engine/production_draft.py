"""Plan-only production draft safety architecture for Stage 3A."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archival import ArchivalCopy, prepare_archival_copy, require_approved_manifest
from .errors import (
    ProductionFamilyError,
    ProductionPlanError,
    ProductionSafetyError,
)
from .naming import VERSION_RE, archival_filename
from .production_boundary import production_environment
from .sandbox_metadata import serialize_sandbox_draft

_PRODUCTION_RECORD_ID = re.compile(r"[0-9]+")
_EXACT_DOI_PATHS = (
    "doi",
    "metadata.doi",
    "pids.doi.identifier",
    "exact_version_doi",
)
_CONCEPT_DOI_PATHS = (
    "conceptdoi",
    "metadata.conceptdoi",
    "parent.pids.doi.identifier",
    "concept_doi",
)
_REGISTRY_APPROVAL_STATE = "published reference cycle"


@dataclass(frozen=True)
class ProductionDraftIntent:
    """Architect-approved next-version intent with no record-selection field."""

    route: str
    record_key: str
    next_version: str

    @classmethod
    def from_object(cls, value: object) -> "ProductionDraftIntent":
        if not isinstance(value, dict):
            raise ProductionPlanError("production draft intent must be a JSON object")
        allowed = {"route", "record_key", "next_version"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ProductionSafetyError(
                "production draft intent contains unsupported selection fields: "
                + ", ".join(unexpected)
            )
        route = _required_text(value, "route", "production draft intent")
        if route != "new-version":
            raise ProductionSafetyError(
                "production draft intent must require the new-version route"
            )
        next_version = _required_text(
            value, "next_version", "production draft intent"
        )
        if VERSION_RE.fullmatch(next_version) is None:
            raise ProductionPlanError("production next_version must match vN")
        return cls(
            route=route,
            record_key=_required_text(value, "record_key", "production draft intent"),
            next_version=next_version,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "route": self.route,
            "record_key": self.record_key,
            "next_version": self.next_version,
        }


@dataclass(frozen=True)
class ProductionFamilyMember:
    """One verified member of the production concept-DOI family."""

    record_id: str
    exact_version_doi: str
    concept_doi: str
    version_label: str
    family_index: int
    is_latest: bool

    @classmethod
    def from_object(cls, value: object) -> "ProductionFamilyMember":
        if not isinstance(value, dict):
            raise ProductionFamilyError("production family member must be an object")
        versions = value.get("versions")
        versions = versions if isinstance(versions, dict) else {}
        metadata = value.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        version_label = metadata.get("version", value.get("version_label"))
        if not isinstance(version_label, str) or VERSION_RE.fullmatch(version_label) is None:
            raise ProductionFamilyError(
                "production family member requires an explicit vN version label"
            )
        family_index = versions.get("index", value.get("family_index"))
        if not isinstance(family_index, int) or isinstance(family_index, bool):
            raise ProductionFamilyError(
                "production family member requires an integer family index"
            )
        is_latest = versions.get("is_latest", value.get("is_latest"))
        if not isinstance(is_latest, bool):
            raise ProductionFamilyError(
                "production family member requires an explicit latest-state marker"
            )
        return cls(
            record_id=_record_id(value),
            exact_version_doi=_supported_doi(
                value, _EXACT_DOI_PATHS, "production exact-version DOI"
            ),
            concept_doi=_supported_doi(
                value, _CONCEPT_DOI_PATHS, "production concept DOI"
            ),
            version_label=version_label,
            family_index=family_index,
            is_latest=is_latest,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "exact_version_doi": self.exact_version_doi,
            "concept_doi": self.concept_doi,
            "version_label": self.version_label,
            "family_index": self.family_index,
            "is_latest": self.is_latest,
        }


@dataclass(frozen=True)
class ProductionFamilySnapshot:
    """Unambiguous read-only observation of one production version family."""

    concept_doi: str
    latest: ProductionFamilyMember
    members: tuple[ProductionFamilyMember, ...]
    inherited_metadata: dict[str, Any]

    @classmethod
    def from_object(cls, value: object) -> "ProductionFamilySnapshot":
        if not isinstance(value, dict):
            raise ProductionFamilyError(
                "production family observation must contain a JSON object"
            )
        latest_value = value.get("latest")
        latest = ProductionFamilyMember.from_object(latest_value)
        members_value = value.get("members")
        if not isinstance(members_value, list) or not members_value:
            raise ProductionFamilyError(
                "production family observation requires explicit family members"
            )
        members = tuple(ProductionFamilyMember.from_object(item) for item in members_value)
        concept_doi = _supported_doi(
            value, ("concept_doi",), "production family concept DOI"
        )
        _reject_ambiguous_members(members)
        latest_members = [item for item in members if item.is_latest]
        if len(latest_members) != 1:
            raise ProductionFamilyError(
                "production family observation must identify exactly one latest member"
            )
        if latest_members[0] != latest:
            raise ProductionFamilyError(
                "production latest record conflicts with the marked latest family member"
            )
        if any(item.concept_doi != concept_doi for item in members):
            raise ProductionFamilyError(
                "production family members contain contradictory concept DOI values"
            )
        if latest.concept_doi != concept_doi:
            raise ProductionFamilyError(
                "production latest record belongs to a different concept-DOI family"
            )
        inherited_metadata = (
            deepcopy(latest_value.get("metadata"))
            if isinstance(latest_value, dict)
            and isinstance(latest_value.get("metadata"), dict)
            else {}
        )
        return cls(
            concept_doi=concept_doi,
            latest=latest,
            members=tuple(sorted(members, key=lambda item: item.family_index)),
            inherited_metadata=inherited_metadata,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "concept_doi": self.concept_doi,
            "latest": self.latest.as_dict(),
            "members": [item.as_dict() for item in self.members],
        }


@dataclass(frozen=True)
class ProductionDraftOperation:
    """One closed, non-executable production-draft planning station."""

    station: str
    purpose: str
    path: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"station": self.station, "purpose": self.purpose}
        if self.path is not None:
            result["path"] = self.path
        return result


@dataclass(frozen=True)
class ProductionDraftPlan:
    """Complete local plan ending at an unpublished architect-review draft."""

    manifest_fingerprint: str
    intent: ProductionDraftIntent
    registry_identity: dict[str, str]
    family: ProductionFamilySnapshot
    source_record_id: str
    archival_copy: ArchivalCopy
    metadata_payload: dict[str, Any]
    inherited_metadata_differences: tuple[str, ...]
    operations: tuple[ProductionDraftOperation, ...]

    def as_dict(self) -> dict[str, Any]:
        environment = production_environment()
        return {
            "stage": "3A",
            "status": "local_plan_only",
            "environment": environment.as_dict(),
            "production_network_enabled": False,
            "credentials_requested": False,
            "credentials_loaded": False,
            "final_release_action_available": False,
            "standalone_deposit_available": False,
            "manifest_fingerprint": self.manifest_fingerprint,
            "intent": self.intent.as_dict(),
            "registry_identity": deepcopy(self.registry_identity),
            "family": self.family.as_dict(),
            "source_record_id": self.source_record_id,
            "new_version_path": (
                f"/deposit/depositions/{self.source_record_id}/actions/newversion"
            ),
            "archival_copy": self.archival_copy.audit_summary(),
            "metadata_policy": "replace_inherited_values_from_approved_manifest",
            "metadata_payload": deepcopy(self.metadata_payload),
            "doi_policy": {
                "reserve_new_exact_version_doi": True,
                "existing_exact_or_concept_doi_supplied": False,
                "supported_response_paths": [
                    "$.doi",
                    "$.metadata.doi",
                    "$.pids.doi.identifier",
                ],
                "conflicting_values": "fail_closed",
            },
            "inherited_metadata_differences": list(
                self.inherited_metadata_differences
            ),
            "verification_channels": {
                "api_visible_fields": "exact_read_back_required",
                "api_unavailable_ui_fields": "visual_verification_required",
            },
            "registry_state": {
                "canonical_filename": self.registry_identity["canonical_filename"],
                "concept_doi": self.family.concept_doi,
                "previous_exact_version_doi": self.family.latest.exact_version_doi,
                "intended_next_version": self.intent.next_version,
                "archival_filename": self.archival_copy.archival_filename,
                "state": "unpublished_production_draft_planned",
                "site_update_package_ready": False,
            },
            "future_credential_boundary": {
                "runtime_environment_variable": "ZENODO_PRODUCTION_TOKEN",
                "required_external_scopes": ["deposit:write", "deposit:actions"],
                "local_planning_reads_environment": False,
                "persistence_permitted": False,
                "publication_permission_permitted": False,
            },
            "operations": [item.as_dict() for item in self.operations],
            "terminal_state": "stop_for_architect_review_before_publication",
        }


class ProductionDraftPlanner:
    """Build a production new-version plan without transport or credentials."""

    def plan(
        self,
        manifest: object,
        *,
        repository_root: str | Path,
        registry_path: str | Path,
        family_observation: object,
        intent: object,
    ) -> ProductionDraftPlan:
        approved = require_approved_manifest(manifest)
        approved_intent = ProductionDraftIntent.from_object(intent)
        record_key = _required_text(approved, "record_key", "approved manifest")
        if approved_intent.record_key != record_key:
            raise ProductionPlanError(
                "production draft intent record_key differs from the approved manifest"
            )
        registry_identity = _exact_registry_identity(approved, registry_path)
        family = ProductionFamilySnapshot.from_object(family_observation)
        _validate_family_identity(approved, family)
        _validate_next_version(approved, approved_intent)

        prospective = _prospective_manifest(approved, approved_intent.next_version)
        archival_copy = prepare_archival_copy(
            prospective, repository_root=repository_root
        )
        metadata_package = serialize_sandbox_draft(prospective, archival_copy)
        inherited_differences = _metadata_differences(
            metadata_package.saved_payload["metadata"], family.inherited_metadata
        )
        source_record_id = _required_text(
            _required_object(approved, "zenodo", "approved manifest"),
            "record_id",
            "approved manifest zenodo",
        )
        source_record_id = _production_record_segment(source_record_id)
        operations = (
            ProductionDraftOperation(
                "verify_approved_identity",
                "verify manifest, registry, candidate, and production family identity",
            ),
            ProductionDraftOperation(
                "create_new_version_draft",
                "begin one unpublished draft in the verified production family",
                f"/deposit/depositions/{source_record_id}/actions/newversion",
            ),
            ProductionDraftOperation(
                "preserve_recovery_identity",
                "preserve safe draft recovery data immediately after creation",
            ),
            ProductionDraftOperation(
                "reserve_new_exact_version_doi",
                "reserve a new exact-version DOI without supplying a prior DOI",
            ),
            ProductionDraftOperation(
                "replace_inherited_metadata",
                "write the manifest-controlled metadata package",
            ),
            ProductionDraftOperation(
                "upload_exact_archival_payload",
                "carry the byte-identical _vN archival payload",
            ),
            ProductionDraftOperation(
                "reload_and_validate",
                "require exact API read-back and explicit visual verification where needed",
            ),
            ProductionDraftOperation(
                "stop_for_architect_review",
                "end with an unpublished draft requiring architect action outside Stage 3A",
            ),
        )
        return ProductionDraftPlan(
            manifest_fingerprint=_manifest_fingerprint(approved),
            intent=approved_intent,
            registry_identity=registry_identity,
            family=family,
            source_record_id=source_record_id,
            archival_copy=archival_copy,
            metadata_payload=deepcopy(metadata_package.saved_payload),
            inherited_metadata_differences=inherited_differences,
            operations=operations,
        )


@dataclass(frozen=True)
class ProductionDraftRecovery:
    """Safe identity for resuming one simulated unpublished production draft."""

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


class LocalProductionDraftSession:
    """In-memory Stage 3A recovery simulation with no request interface."""

    def __init__(self, plan: ProductionDraftPlan) -> None:
        self.plan = plan
        self._recovery: ProductionDraftRecovery | None = None
        self._creation_count = 0

    @property
    def creation_count(self) -> int:
        return self._creation_count

    @property
    def recovery(self) -> ProductionDraftRecovery | None:
        return self._recovery

    def preserve_created_draft(self, response: object) -> ProductionDraftRecovery:
        if self._recovery is not None:
            raise ProductionSafetyError(
                "a production draft is already preserved for this local session"
            )
        if not isinstance(response, dict):
            raise ProductionSafetyError(
                "production draft creation response must be an object"
            )
        draft = response
        draft_id = _record_id(draft)
        record_id = _optional_record_id(draft.get("recid"))
        origin = production_environment().origin
        safe_result = {
            key: deepcopy(draft[key])
            for key in (
                "id",
                "recid",
                "conceptrecid",
                "created",
                "updated",
                "status",
                "state",
                "submitted",
            )
            if isinstance(draft.get(key), (str, int, bool))
        }
        recovery = ProductionDraftRecovery(
            draft_id=draft_id,
            record_id=record_id,
            edit_url=f"{origin}/uploads/{draft_id}",
            preview_url=f"{origin}/records/{draft_id}?preview=1",
            creation_result=safe_result,
        )
        self._recovery = recovery
        self._creation_count = 1
        return recovery

    def fail_after_creation(self, response: object) -> None:
        recovery = self.preserve_created_draft(response)
        failure = ProductionPlanError(
            "simulated production draft failure after recovery preservation"
        )
        failure.attach_recovery(recovery.as_dict())
        raise failure

    def resume(self, response: object, *, draft_id: str) -> dict[str, Any]:
        if self._recovery is None:
            raise ProductionSafetyError(
                "production resume requires an immediately preserved draft identity"
            )
        explicit_id = _production_record_segment(draft_id)
        if explicit_id != self._recovery.draft_id:
            raise ProductionSafetyError(
                "production resume draft differs from the preserved draft identity"
            )
        draft = _verified_unpublished_draft(
            response,
            expected_concept_doi=self.plan.family.concept_doi,
        )
        if _record_id(draft) != explicit_id:
            raise ProductionSafetyError(
                "production resume response differs from the explicit draft identity"
            )
        return {
            "draft_id": explicit_id,
            "state": "unpublished_unsubmitted",
            "creation_count": self._creation_count,
            "second_draft_created": False,
        }


def load_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    """Load one local Stage 3A planning object."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProductionPlanError(f"{label} must contain a JSON object")
    return value


def _exact_registry_identity(
    manifest: dict[str, Any], registry_path: str | Path
) -> dict[str, str]:
    path = Path(registry_path)
    if not path.is_file():
        raise ProductionPlanError("production planning requires the publication registry")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = [dict(item) for item in csv.DictReader(stream)]
    github = _required_object(manifest, "github", "approved manifest")
    canonical_filename = _required_text(
        github, "canonical_filename", "approved manifest github"
    )
    matches = [item for item in rows if item.get("canonical_filename") == canonical_filename]
    if not matches:
        raise ProductionPlanError(
            "publication registry has no exact row for the approved manifest"
        )
    if len(matches) != 1:
        raise ProductionPlanError(
            "publication registry contains ambiguous rows for the approved manifest"
        )
    row = matches[0]
    zenodo = _required_object(manifest, "zenodo", "approved manifest")
    expected = {
        "canonical_filename": canonical_filename,
        "github_directory": _required_text(
            github, "directory", "approved manifest github"
        ),
        "github_commit": _required_text(github, "commit", "approved manifest github"),
        "github_sha256": _required_text(github, "sha256", "approved manifest github"),
        "github_md5": _required_text(github, "md5", "approved manifest github"),
        "concept_doi": _required_text(zenodo, "concept_doi", "approved manifest zenodo"),
        "latest_version_label": _required_text(
            zenodo, "target_version", "approved manifest zenodo"
        ),
        "latest_version_doi": _required_text(
            zenodo, "exact_version_doi", "approved manifest zenodo"
        ),
        "zenodo_archival_filename": _required_text(
            zenodo, "archival_filename", "approved manifest zenodo"
        ),
        "zenodo_checksum": _required_text(
            zenodo, "archival_checksum", "approved manifest zenodo"
        ),
        "publication_date": _required_text(
            zenodo, "publication_date", "approved manifest zenodo"
        ),
        "metadata_status": "validated",
        "file_status": "matching",
        "site_relation_status": "validated",
        "architect_approval_state": _REGISTRY_APPROVAL_STATE,
    }
    mismatches = [key for key, value in expected.items() if row.get(key) != value]
    if mismatches:
        raise ProductionPlanError(
            "publication registry differs from the approved manifest: "
            + ", ".join(mismatches)
        )
    return {key: row[key] for key in expected}


def _validate_family_identity(
    manifest: dict[str, Any], family: ProductionFamilySnapshot
) -> None:
    zenodo = _required_object(manifest, "zenodo", "approved manifest")
    expected_concept = _required_text(
        zenodo, "concept_doi", "approved manifest zenodo"
    )
    expected_exact = _required_text(
        zenodo, "exact_version_doi", "approved manifest zenodo"
    )
    expected_record = _production_record_segment(
        _required_text(zenodo, "record_id", "approved manifest zenodo")
    )
    expected_version = _required_text(
        zenodo, "target_version", "approved manifest zenodo"
    )
    if family.concept_doi != expected_concept:
        raise ProductionFamilyError(
            "production concept DOI differs from the approved manifest"
        )
    if family.latest.exact_version_doi != expected_exact:
        raise ProductionFamilyError(
            "production latest exact-version DOI differs from the approved manifest"
        )
    if family.latest.record_id != expected_record:
        raise ProductionFamilyError(
            "production latest record identity differs from the approved manifest"
        )
    if family.latest.version_label != expected_version:
        raise ProductionFamilyError(
            "production latest version differs from the approved manifest"
        )

    manifest_members = zenodo.get("version_family")
    if not isinstance(manifest_members, list) or not manifest_members:
        raise ProductionFamilyError(
            "approved manifest is missing required production family identity"
        )
    expected_members: list[tuple[str, str, str, int, bool]] = []
    expected_identities: dict[tuple[str, str, str, int], bool] = {}
    for item in manifest_members:
        if not isinstance(item, dict):
            raise ProductionFamilyError(
                "approved manifest production family member must be an object"
            )
        index = item.get("family_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ProductionFamilyError(
                "approved manifest production family index is missing"
            )
        is_latest = item.get("is_latest")
        if not isinstance(is_latest, bool):
            raise ProductionFamilyError(
                "approved manifest production family latest-state marker is missing"
            )
        identity = (
            _production_record_segment(
                _required_text(item, "record_id", "manifest family member")
            ),
            _required_text(item, "exact_version_doi", "manifest family member"),
            _required_text(item, "version_label", "manifest family member"),
            index,
        )
        if identity in expected_identities:
            if expected_identities[identity] != is_latest:
                raise ProductionFamilyError(
                    "approved manifest production family member has contradictory latest-state markers"
                )
            raise ProductionFamilyError(
                "approved manifest contains a duplicate production family member"
            )
        expected_identities[identity] = is_latest
        expected_members.append((*identity, is_latest))

    for label, values in (
        ("record identifiers", [item[0] for item in expected_members]),
        ("exact-version DOI values", [item[1] for item in expected_members]),
        ("family indices", [item[3] for item in expected_members]),
    ):
        if len(values) != len(set(values)):
            raise ProductionFamilyError(
                f"approved manifest production family contains ambiguous {label}"
            )

    manifest_latest = [item for item in expected_members if item[4]]
    if len(manifest_latest) != 1:
        raise ProductionFamilyError(
            "approved manifest must identify exactly one latest production family member"
        )
    expected_family_index = zenodo.get("version_family_index")
    if not isinstance(expected_family_index, int) or isinstance(
        expected_family_index, bool
    ):
        raise ProductionFamilyError(
            "approved manifest production family index is missing"
        )
    expected_latest = (
        expected_record,
        expected_exact,
        expected_version,
        expected_family_index,
        True,
    )
    if manifest_latest[0] != expected_latest:
        raise ProductionFamilyError(
            "approved manifest latest family member contradicts its current record identity"
        )

    observed_members = [
        (
            item.record_id,
            item.exact_version_doi,
            item.version_label,
            item.family_index,
            item.is_latest,
        )
        for item in family.members
    ]
    if sorted(observed_members) != sorted(expected_members):
        raise ProductionFamilyError(
            "production family members differ from the approved manifest"
        )

    expected_previous = _required_text(
        zenodo, "previous_version_doi", "approved manifest zenodo"
    )
    prior = [
        item
        for item in family.members
        if item.family_index < family.latest.family_index
    ]
    if not prior or max(prior, key=lambda item: item.family_index).exact_version_doi != expected_previous:
        raise ProductionFamilyError(
            "production previous exact-version DOI differs from the approved manifest"
        )


def _validate_next_version(
    manifest: dict[str, Any], intent: ProductionDraftIntent
) -> None:
    zenodo = _required_object(manifest, "zenodo", "approved manifest")
    current = _required_text(zenodo, "target_version", "approved manifest zenodo")
    current_match = VERSION_RE.fullmatch(current)
    next_match = VERSION_RE.fullmatch(intent.next_version)
    if current_match is None or next_match is None:
        raise ProductionPlanError("production version identity must match vN")
    if int(next_match.group(1)) != int(current_match.group(1)) + 1:
        raise ProductionPlanError(
            "production next version must immediately follow the verified latest version"
        )


def _prospective_manifest(
    manifest: dict[str, Any], next_version: str
) -> dict[str, Any]:
    prospective = deepcopy(manifest)
    github = _required_object(prospective, "github", "approved manifest")
    zenodo = _required_object(prospective, "zenodo", "approved manifest")
    filename = archival_filename(
        _required_text(github, "canonical_filename", "approved manifest github"),
        next_version,
    )
    zenodo["target_version"] = next_version
    zenodo["archival_filename"] = filename
    prospective["preview"]["default_file"] = filename
    return prospective


def _metadata_differences(
    approved_metadata: dict[str, Any], inherited_metadata: dict[str, Any]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            key
            for key in set(approved_metadata) | set(inherited_metadata)
            if approved_metadata.get(key) != inherited_metadata.get(key)
        )
    )


def _manifest_fingerprint(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reject_ambiguous_members(members: tuple[ProductionFamilyMember, ...]) -> None:
    for label, values in (
        ("record identifiers", [item.record_id for item in members]),
        ("exact-version DOI values", [item.exact_version_doi for item in members]),
        ("family indices", [item.family_index for item in members]),
    ):
        if len(values) != len(set(values)):
            raise ProductionFamilyError(
                f"production family contains ambiguous {label}"
            )


def _supported_doi(value: object, paths: tuple[str, ...], label: str) -> str:
    if not isinstance(value, dict):
        raise ProductionFamilyError(f"{label} response must be an object")
    observed: list[tuple[str, str]] = []
    for path in paths:
        present, candidate = _path_value(value, path)
        if not present or candidate is None:
            continue
        if not isinstance(candidate, str) or not candidate or candidate != candidate.strip():
            raise ProductionFamilyError(
                f"{label} at $.{path} must contain a non-empty string"
            )
        observed.append((path, candidate))
    if not observed:
        raise ProductionFamilyError(f"{label} is missing from supported paths")
    identifiers = {candidate for _, candidate in observed}
    if len(identifiers) != 1:
        rendered_paths = ", ".join(f"$.{path}" for path, _ in observed)
        raise ProductionFamilyError(
            f"{label} contains conflicting values at {rendered_paths}"
        )
    return observed[0][1]


def _verified_unpublished_draft(
    value: object, *, expected_concept_doi: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionSafetyError("production draft response must be an object")
    _record_id(value)
    status = value.get("status")
    if status is not None and status not in {"draft", "new_version_draft"}:
        raise ProductionSafetyError(
            "production draft must remain unpublished"
        )
    if value.get("is_published") not in {None, False}:
        raise ProductionSafetyError(
            "production draft cannot carry a published-state marker"
        )
    if value.get("state") not in {None, "unsubmitted"}:
        raise ProductionSafetyError(
            "production draft must remain unsubmitted"
        )
    if value.get("submitted") not in {None, False}:
        raise ProductionSafetyError(
            "production draft cannot carry a submitted-state marker"
        )
    concept_doi = _supported_doi(
        value, _CONCEPT_DOI_PATHS, "production draft concept DOI"
    )
    if concept_doi != expected_concept_doi:
        raise ProductionSafetyError(
            "production draft belongs to a different concept-DOI family"
        )
    return value


def _record_id(value: dict[str, Any]) -> str:
    observed = [
        _production_record_segment(candidate)
        for candidate in (value.get("id"), value.get("recid"))
        if candidate is not None
    ]
    if not observed:
        raise ProductionFamilyError("production record identifier is missing")
    if len(set(observed)) != 1:
        raise ProductionFamilyError(
            "production record contains contradictory identifier representations"
        )
    return observed[0]


def _optional_record_id(value: object) -> str | None:
    return None if value is None else _production_record_segment(value)


def _production_record_segment(value: object) -> str:
    if isinstance(value, bool):
        raise ProductionSafetyError(
            "production record identifier contains unsupported characters"
        )
    text = str(value) if value is not None else ""
    if _PRODUCTION_RECORD_ID.fullmatch(text) is None:
        raise ProductionSafetyError(
            "production record identifier contains unsupported characters"
        )
    return text


def _path_value(value: object, path: str) -> tuple[bool, Any]:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _required_object(
    value: dict[str, Any], key: str, label: str
) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ProductionPlanError(f"{label} requires object field {key}")
    return result


def _required_text(value: dict[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ProductionPlanError(f"{label} requires string field {key}")
    return result
