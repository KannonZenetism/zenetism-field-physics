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
from urllib.parse import urlsplit

from .archival import ArchivalCopy, prepare_archival_copy, require_approved_manifest
from .description import description_text, infer_description_form
from .errors import (
    ProductionFamilyError,
    ProductionPlanError,
    ProductionSafetyError,
)
from .naming import VERSION_RE, archival_filename
from .production_boundary import production_environment
from .sandbox_metadata import serialize_sandbox_draft

_PRODUCTION_RECORD_ID = re.compile(r"[0-9]+")
_PRODUCTION_CONCEPT_DOI = re.compile(r"10\.5281/zenodo\.([0-9]+)")
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
_TWO_STATE_SCHEMA = "zenetism-publication-engine-v2-stage-3b-candidate-preparation"
_TWO_STATE_PREPARATION_STATE = "architect_review_required"
_APPROVED_SITE_RELATION = {
    "relation": "IsDocumentedBy",
    "scheme": "URL",
    "resource_type": "Other",
    "identifier": "https://zenetism.aelionkannon.chatgpt.site",
}


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
    def from_object(
        cls,
        value: object,
        *,
        latest_relation_identity: tuple[str, str, str, str, int] | None = None,
    ) -> "ProductionFamilyMember":
        identity = _family_member_identity(value)
        is_latest = _explicit_family_latest_state(value)
        if latest_relation_identity is not None:
            relation_state = identity == latest_relation_identity
            if is_latest is not None and is_latest != relation_state:
                raise ProductionFamilyError(
                    "production family contains conflicting latest-state evidence"
                )
            if is_latest is None:
                is_latest = relation_state
        if is_latest is None:
            raise ProductionFamilyError(
                "production family member requires explicit latest-state evidence"
            )
        return cls(
            record_id=identity[0],
            exact_version_doi=identity[1],
            concept_doi=identity[2],
            version_label=identity[3],
            family_index=identity[4],
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
        latest_relation_value = value.get("latest_relation_record")
        latest_relation_identity: tuple[str, str, str, str, int] | None = None
        if latest_relation_value is not None:
            if not isinstance(latest_value, dict):
                raise ProductionFamilyError(
                    "production latest family member must be an object"
                )
            latest_identity = _family_member_identity(latest_value)
            _fixed_family_relation_path(
                latest_value,
                relation="latest",
                expected_record_id=latest_identity[0],
            )
            latest_relation_identity = _family_member_identity(
                latest_relation_value
            )
            if latest_relation_identity != latest_identity:
                raise ProductionFamilyError(
                    "production latest relation differs from the expected family member"
                )
        latest = ProductionFamilyMember.from_object(
            latest_value,
            latest_relation_identity=latest_relation_identity,
        )
        members_value = value.get("members")
        if not isinstance(members_value, list) or not members_value:
            raise ProductionFamilyError(
                "production family observation requires explicit family members"
            )
        members = tuple(
            ProductionFamilyMember.from_object(
                item,
                latest_relation_identity=latest_relation_identity,
            )
            for item in members_value
        )
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
        if _is_two_state_package(manifest):
            return self._plan_two_state(
                manifest,
                repository_root=repository_root,
                registry_path=registry_path,
                family_observation=family_observation,
                intent=intent,
            )

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
        source_record_id = _required_text(
            _required_object(approved, "zenodo", "approved manifest"),
            "record_id",
            "approved manifest zenodo",
        )
        return _complete_production_plan(
            approved_identity=approved,
            prospective=prospective,
            approved_intent=approved_intent,
            registry_identity=registry_identity,
            family=family,
            source_record_id=source_record_id,
            repository_root=repository_root,
        )

    def _plan_two_state(
        self,
        manifest: object,
        *,
        repository_root: str | Path,
        registry_path: str | Path,
        family_observation: object,
        intent: object,
    ) -> ProductionDraftPlan:
        package = _validated_two_state_package(manifest)
        approved_intent = ProductionDraftIntent.from_object(intent)
        record_key = _required_text(package, "record_key", "two-state manifest")
        if approved_intent.record_key != record_key:
            raise ProductionPlanError(
                "production draft intent record_key differs from the two-state manifest"
            )

        baseline_manifest = _published_baseline_family_manifest(package)
        family = ProductionFamilySnapshot.from_object(family_observation)
        _validate_family_identity(baseline_manifest, family)
        _validate_two_state_intent(package, approved_intent)
        registry_identity = _exact_two_state_registry_identity(package, registry_path)
        prospective = _two_state_candidate_manifest(package)
        source_record_id = _required_text(
            _required_object(
                _required_object(package, "published_baseline", "two-state manifest"),
                "zenodo",
                "published baseline",
            ),
            "record_id",
            "published baseline zenodo",
        )
        return _complete_production_plan(
            approved_identity=package,
            prospective=prospective,
            approved_intent=approved_intent,
            registry_identity=registry_identity,
            family=family,
            source_record_id=source_record_id,
            repository_root=repository_root,
        )


def _complete_production_plan(
    *,
    approved_identity: dict[str, Any],
    prospective: dict[str, Any],
    approved_intent: ProductionDraftIntent,
    registry_identity: dict[str, str],
    family: ProductionFamilySnapshot,
    source_record_id: str,
    repository_root: str | Path,
) -> ProductionDraftPlan:
    archival_copy = prepare_archival_copy(
        prospective, repository_root=repository_root
    )
    metadata_package = serialize_sandbox_draft(prospective, archival_copy)
    inherited_differences = _metadata_differences(
        metadata_package.saved_payload["metadata"], family.inherited_metadata
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
        manifest_fingerprint=_manifest_fingerprint(approved_identity),
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


def _is_two_state_package(value: object) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == _TWO_STATE_SCHEMA


def _validated_two_state_package(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionPlanError("two-state production manifest must be an object")
    expected_top_level = {
        "schema_version",
        "record_key",
        "preparation_state",
        "corpus_classification",
        "published_baseline",
        "candidate",
        "publication",
    }
    if set(value) != expected_top_level:
        raise ProductionPlanError(
            "two-state production manifest contains missing or unsupported root fields"
        )
    if value.get("schema_version") != _TWO_STATE_SCHEMA:
        raise ProductionPlanError("two-state production manifest schema is unsupported")
    if value.get("preparation_state") != _TWO_STATE_PREPARATION_STATE:
        raise ProductionPlanError(
            "two-state production manifest requires explicit architect review state"
        )
    _required_text(value, "record_key", "two-state manifest")
    _required_text(value, "corpus_classification", "two-state manifest")
    publication = _required_object(value, "publication", "two-state manifest")
    if publication != {"architect_publish_required": True}:
        raise ProductionSafetyError(
            "two-state production manifest must retain the architect publication gate"
        )

    baseline = _required_object(value, "published_baseline", "two-state manifest")
    _require_exact_fields(
        baseline,
        {
            "github",
            "zenodo",
            "comparison",
            "creator",
            "contributors",
            "repository_url",
            "description",
            "keywords",
            "related_identifiers",
            "site_relation",
            "site_relation_status",
            "preview",
        },
        "published baseline",
    )
    baseline_github = _required_object(baseline, "github", "published baseline")
    baseline_zenodo = _required_object(baseline, "zenodo", "published baseline")
    _require_exact_fields(
        baseline_zenodo,
        {
            "record_id",
            "concept_record_id",
            "exact_version_doi",
            "concept_doi",
            "previous_version_doi",
            "version",
            "record_revision",
            "version_family_index",
            "is_latest",
            "publication_date",
            "archival_filename",
            "archival_byte_size",
            "archival_checksum",
            "archival_sha256",
            "archival_md5",
            "metadata",
            "version_family",
        },
        "published baseline zenodo",
    )
    candidate = _required_object(value, "candidate", "two-state manifest")
    candidate_fields = {
        "github",
        "production_identity",
        "metadata",
        "creator",
        "contributors",
        "repository_url",
        "description",
        "keywords",
        "keyword_change",
        "related_identifiers",
        "site_relation",
        "preview",
    }
    comparison_fields = {
        "comparison_to_published_baseline",
        "comparison_to_published_v8",
    }
    present_comparison_fields = set(candidate).intersection(comparison_fields)
    if len(present_comparison_fields) != 1:
        raise ProductionPlanError(
            "candidate requires one explicit published-baseline comparison"
        )
    comparison_field = next(iter(present_comparison_fields))
    _require_exact_fields(
        candidate,
        candidate_fields | {comparison_field},
        "candidate",
    )
    candidate_github = _required_object(candidate, "github", "candidate")
    production_identity = _required_object(
        candidate, "production_identity", "candidate"
    )
    candidate_metadata = _required_object(candidate, "metadata", "candidate")
    _require_exact_fields(
        candidate_metadata,
        {
            "title",
            "publisher",
            "resource_type",
            "access",
            "license",
            "publication_date",
            "version",
            "copyright",
            "language",
        },
        "candidate metadata",
    )
    github_fields = {
        "repository",
        "branch",
        "directory",
        "canonical_filename",
        "path",
        "commit",
        "blob_sha",
        "byte_size",
        "sha256",
        "md5",
    }
    _require_exact_fields(baseline_github, github_fields, "published baseline github")
    _require_exact_fields(candidate_github, github_fields, "candidate github")
    _require_exact_fields(
        production_identity,
        {
            "route",
            "source_record_id",
            "concept_record_id",
            "concept_doi",
            "previous_exact_version_doi",
            "previous_version",
            "target_version",
            "exact_version_doi",
            "archival_filename",
            "archival_byte_size",
            "archival_sha256",
            "archival_md5",
            "publication_date",
            "new_version_action",
            "standalone_deposition_permitted",
        },
        "candidate production identity",
    )
    _required_digest(
        baseline_github, "commit", 40, "published baseline github"
    )
    _required_digest(
        baseline_github, "blob_sha", 40, "published baseline github"
    )
    _required_digest(candidate_github, "commit", 40, "candidate github")
    _required_digest(candidate_github, "blob_sha", 40, "candidate github")
    _validate_two_state_people_and_prose(baseline, "published baseline")
    _validate_two_state_people_and_prose(
        candidate,
        "candidate",
        require_exact_word_count=(
            comparison_field == "comparison_to_published_baseline"
        ),
    )

    for key in ("repository", "branch", "directory", "canonical_filename", "path"):
        if _required_text(candidate_github, key, "candidate github") != _required_text(
            baseline_github, key, "published baseline github"
        ):
            raise ProductionPlanError(
                f"candidate GitHub {key} differs from the published canonical identity"
            )
    expected_path = str(
        Path(_required_text(candidate_github, "directory", "candidate github"))
        / _required_text(candidate_github, "canonical_filename", "candidate github")
    )
    if _required_text(candidate_github, "path", "candidate github") != expected_path:
        raise ProductionPlanError(
            "candidate GitHub path differs from its approved directory and filename"
        )

    baseline_size = _required_positive_int(
        baseline_github, "byte_size", "published baseline github"
    )
    baseline_sha256 = _required_digest(
        baseline_github, "sha256", 64, "published baseline github"
    )
    baseline_md5 = _required_digest(
        baseline_github, "md5", 32, "published baseline github"
    )
    if (
        _required_positive_int(
            baseline_zenodo, "archival_byte_size", "published baseline zenodo"
        )
        != baseline_size
        or _required_text(
            baseline_zenodo, "archival_sha256", "published baseline zenodo"
        )
        != baseline_sha256
        or _required_text(
            baseline_zenodo, "archival_md5", "published baseline zenodo"
        )
        != baseline_md5
        or _required_text(
            baseline_zenodo, "archival_checksum", "published baseline zenodo"
        )
        != f"md5:{baseline_md5}"
    ):
        raise ProductionPlanError(
            "published baseline GitHub and Zenodo payload identities differ"
        )
    baseline_comparison = _required_object(
        baseline, "comparison", "published baseline"
    )
    if any(
        baseline_comparison.get(key) != "matching"
        for key in (
            "payload_status",
            "byte_size_status",
            "sha256_status",
            "md5_status",
        )
    ):
        raise ProductionPlanError(
            "published baseline must preserve an exact matching payload state"
        )
    baseline_metadata = _required_object(
        baseline_zenodo, "metadata", "published baseline zenodo"
    )
    _require_fields_with_optional(
        baseline_metadata,
        {
            "title",
            "resource_type",
            "access",
            "license",
            "copyright",
            "language",
        },
        {"publisher"},
        "published baseline metadata",
    )
    _validate_two_state_metadata_objects(
        baseline_metadata, "published baseline metadata"
    )
    _validate_two_state_metadata_objects(candidate_metadata, "candidate metadata")
    baseline_publisher = baseline_metadata.get("publisher")
    candidate_publisher = _required_text(
        candidate_metadata, "publisher", "candidate metadata"
    )
    if (
        baseline_publisher is not None
        and baseline_publisher != candidate_publisher
    ):
        raise ProductionPlanError(
            "candidate Publisher differs from the explicit published baseline"
        )
    if (
        baseline.get("site_relation_status") != "absent"
        or baseline.get("site_relation") is not None
        or baseline.get("related_identifiers") != []
    ):
        raise ProductionPlanError(
            "published baseline Site-relation absence is contradictory or ambiguous"
        )

    candidate_size = _required_positive_int(
        candidate_github, "byte_size", "candidate github"
    )
    candidate_sha256 = _required_digest(
        candidate_github, "sha256", 64, "candidate github"
    )
    candidate_md5 = _required_digest(
        candidate_github, "md5", 32, "candidate github"
    )
    baseline_payload_identity = (baseline_size, baseline_sha256, baseline_md5)
    candidate_payload_identity = (candidate_size, candidate_sha256, candidate_md5)
    if candidate_payload_identity == baseline_payload_identity:
        raise ProductionPlanError(
            "published baseline and proposed candidate payload identities collapsed"
        )
    if (
        _required_positive_int(
            production_identity, "archival_byte_size", "candidate production identity"
        )
        != candidate_size
        or _required_text(
            production_identity, "archival_sha256", "candidate production identity"
        )
        != candidate_sha256
        or _required_text(
            production_identity, "archival_md5", "candidate production identity"
        )
        != candidate_md5
    ):
        raise ProductionPlanError(
            "candidate archival payload differs from the approved GitHub identity"
        )
    comparison = _required_object(candidate, comparison_field, "candidate")
    expected_comparison = {
        "payload_status": "different",
        "byte_size_status": (
            "matching" if candidate_size == baseline_size else "different"
        ),
        "sha256_status": (
            "matching" if candidate_sha256 == baseline_sha256 else "different"
        ),
        "md5_status": "matching" if candidate_md5 == baseline_md5 else "different",
    }
    if comparison != expected_comparison:
        raise ProductionPlanError(
            "candidate comparison does not describe the published-baseline difference"
        )

    baseline_record_id = _production_record_segment(
        _required_text(baseline_zenodo, "record_id", "published baseline zenodo")
    )
    baseline_concept_record_id = _production_record_segment(
        _required_text(
            baseline_zenodo, "concept_record_id", "published baseline zenodo"
        )
    )
    baseline_exact_doi = _required_text(
        baseline_zenodo, "exact_version_doi", "published baseline zenodo"
    )
    baseline_concept_doi = _required_text(
        baseline_zenodo, "concept_doi", "published baseline zenodo"
    )
    baseline_version = _required_text(
        baseline_zenodo, "version", "published baseline zenodo"
    )
    if VERSION_RE.fullmatch(baseline_version) is None:
        raise ProductionPlanError("published baseline version must match vN")
    expected_baseline_filename = archival_filename(
        _required_text(
            baseline_github, "canonical_filename", "published baseline github"
        ),
        baseline_version,
    )
    if (
        _required_text(
            baseline_zenodo, "archival_filename", "published baseline zenodo"
        )
        != expected_baseline_filename
        or baseline_zenodo.get("is_latest") is not True
    ):
        raise ProductionPlanError(
            "published baseline filename or latest state is contradictory"
        )
    baseline_preview = _required_object(
        baseline, "preview", "published baseline"
    )
    if baseline_preview != {
        "explicit_default_file": True,
        "default_file": expected_baseline_filename,
    }:
        raise ProductionPlanError(
            "published baseline default Preview differs from its archival file"
        )
    if (
        _production_record_segment(
            _required_text(
                production_identity, "source_record_id", "candidate production identity"
            )
        )
        != baseline_record_id
        or _production_record_segment(
            _required_text(
                production_identity,
                "concept_record_id",
                "candidate production identity",
            )
        )
        != baseline_concept_record_id
        or _required_text(
            production_identity,
            "concept_doi",
            "candidate production identity",
        )
        != baseline_concept_doi
        or _required_text(
            production_identity,
            "previous_exact_version_doi",
            "candidate production identity",
        )
        != baseline_exact_doi
        or _required_text(
            production_identity, "previous_version", "candidate production identity"
        )
        != baseline_version
    ):
        raise ProductionFamilyError(
            "candidate continuation differs from the published baseline family identity"
        )
    if (
        "exact_version_doi" not in production_identity
        or production_identity.get("exact_version_doi") is not None
    ):
        raise ProductionSafetyError(
            "candidate exact-version DOI must remain unset until reservation"
        )
    if (
        production_identity.get("route") != "new-version"
        or production_identity.get("new_version_action")
        != "deposit:actions/newversion"
        or production_identity.get("standalone_deposition_permitted") is not False
    ):
        raise ProductionSafetyError(
            "candidate production route differs from the confined new-version operation"
        )
    target_version = _required_text(
        production_identity, "target_version", "candidate production identity"
    )
    target_match = VERSION_RE.fullmatch(target_version)
    baseline_match = VERSION_RE.fullmatch(baseline_version)
    assert baseline_match is not None
    if target_match is None or int(target_match.group(1)) != (
        int(baseline_match.group(1)) + 1
    ):
        raise ProductionPlanError(
            "candidate version must immediately follow the published baseline"
        )
    expected_filename = archival_filename(
        _required_text(candidate_github, "canonical_filename", "candidate github"),
        target_version,
    )
    if _required_text(
        production_identity, "archival_filename", "candidate production identity"
    ) != expected_filename:
        raise ProductionPlanError(
            "candidate archival filename differs from the approved vN convention"
        )

    metadata = candidate_metadata
    if (
        metadata.get("version") != target_version
        or metadata.get("publication_date")
        != _required_text(
            production_identity, "publication_date", "candidate production identity"
        )
        or metadata.get("publication_date")
        != _required_text(
            baseline_zenodo, "publication_date", "published baseline zenodo"
        )
    ):
        raise ProductionPlanError(
            "candidate version or publication date contradicts the approved continuation"
        )
    preview = _required_object(candidate, "preview", "candidate")
    if preview != {
        "explicit_default_file": True,
        "default_file": expected_filename,
    }:
        raise ProductionPlanError(
            "candidate default Preview differs from the approved archival file"
        )
    site_relation = _required_object(candidate, "site_relation", "candidate")
    related_identifiers = candidate.get("related_identifiers")
    if (
        site_relation != _APPROVED_SITE_RELATION
        or related_identifiers != [_APPROVED_SITE_RELATION]
    ):
        raise ProductionPlanError(
            "candidate Site-relation transition is unapproved or contradictory"
        )
    keyword_change = _required_object(candidate, "keyword_change", "candidate")
    _require_fields_with_optional(
        keyword_change,
        {
            "architect_review_required",
            "previous_count",
            "proposed_count",
            "added",
            "removed",
        },
        {"replacements"},
        "candidate keyword change",
    )
    baseline_keywords = baseline.get("keywords")
    candidate_keywords = candidate.get("keywords")
    _validate_keyword_transition(
        baseline_keywords,
        candidate_keywords,
        keyword_change,
    )
    return value


def _validate_keyword_transition(
    baseline_keywords: object,
    candidate_keywords: object,
    keyword_change: dict[str, Any],
) -> None:
    if not isinstance(baseline_keywords, list) or not isinstance(
        candidate_keywords, list
    ):
        raise ProductionPlanError("keyword transition requires two ordered lists")
    if (
        keyword_change.get("architect_review_required") is not True
        or keyword_change.get("previous_count") != len(baseline_keywords)
        or keyword_change.get("proposed_count") != len(candidate_keywords)
    ):
        raise ProductionPlanError(
            "candidate keyword transition differs from the explicit architect-review state"
        )
    added = keyword_change.get("added")
    removed = keyword_change.get("removed")
    replacements = keyword_change.get("replacements", [])
    if not isinstance(added, list) or not isinstance(removed, list):
        raise ProductionPlanError("keyword additions and removals must be ordered lists")
    if not isinstance(replacements, list):
        raise ProductionPlanError("keyword replacements must be an ordered list")
    replacement_map: dict[str, str] = {}
    for item in replacements:
        if not isinstance(item, dict):
            raise ProductionPlanError("keyword replacement must be an object")
        _require_exact_fields(
            item,
            {"previous", "proposed"},
            "keyword replacement",
        )
        previous = _required_text(item, "previous", "keyword replacement")
        proposed = _required_text(item, "proposed", "keyword replacement")
        if previous in replacement_map or previous not in baseline_keywords:
            raise ProductionPlanError("keyword replacement identity is ambiguous")
        replacement_map[previous] = proposed
    transformed_baseline = [
        replacement_map.get(item, item) for item in baseline_keywords
    ]
    if len(transformed_baseline) != len(set(transformed_baseline)):
        raise ProductionPlanError("keyword replacements produce duplicate terms")
    expected_added = [
        item for item in candidate_keywords if item not in transformed_baseline
    ]
    expected_removed = [
        item for item in transformed_baseline if item not in candidate_keywords
    ]
    retained_baseline = [
        item for item in transformed_baseline if item in candidate_keywords
    ]
    retained_candidate = [
        item for item in candidate_keywords if item in transformed_baseline
    ]
    if (
        added != expected_added
        or removed != expected_removed
        or retained_candidate != retained_baseline
        or candidate_keywords[:3]
        != ["Zenetism", "Aelion Kannon", "Structural Metaphysics"]
    ):
        raise ProductionPlanError(
            "candidate keyword transition differs from the explicit architect-review state"
        )


def _validate_two_state_people_and_prose(
    state: dict[str, Any],
    label: str,
    *,
    require_exact_word_count: bool = False,
) -> None:
    creator = _required_object(state, "creator", label)
    _require_exact_fields(
        creator,
        {"family_name", "given_names", "rendered_name"},
        f"{label} creator",
    )
    if creator != {
        "family_name": "Aelion Kannon",
        "given_names": "",
        "rendered_name": "Aelion Kannon",
    }:
        raise ProductionPlanError(
            f"{label} creator differs from the approved corpus convention"
        )
    contributors = state.get("contributors")
    if not isinstance(contributors, list) or not contributors:
        raise ProductionPlanError(f"{label} contributors must be explicit")
    contributor_identities: list[tuple[str, str]] = []
    for item in contributors:
        if not isinstance(item, dict):
            raise ProductionPlanError(f"{label} contributor must be an object")
        _require_exact_fields(item, {"name", "role"}, f"{label} contributor")
        contributor_identities.append(
            (
                _required_text(item, "name", f"{label} contributor"),
                _required_text(item, "role", f"{label} contributor"),
            )
        )
    if len(contributor_identities) != len(set(contributor_identities)):
        raise ProductionPlanError(f"{label} contributors are ambiguous")
    github = _required_object(state, "github", label)
    expected_repository_url = (
        f"https://github.com/{_required_text(github, 'repository', f'{label} github')}"
        f"/tree/{_required_text(github, 'branch', f'{label} github')}"
        f"/{_required_text(github, 'directory', f'{label} github').strip('/')}"
    )
    if _required_text(state, "repository_url", label) != expected_repository_url:
        raise ProductionPlanError(
            f"{label} Repository URL differs from the precise GitHub directory"
        )
    description = _required_object(state, "description", label)
    description_fields = (
        {"form", "word_count", "rendered_html", "attestation_included"}
        if label == "candidate"
        else {"form", "rendered_html"}
    )
    _require_exact_fields(
        description, description_fields, f"{label} description"
    )
    rendered_html = _required_text(
        description, "rendered_html", f"{label} description"
    )
    form = _required_text(description, "form", f"{label} description")
    if form not in {"Short", "Standard", "Series"}:
        raise ProductionPlanError(f"{label} description form is unsupported")
    if infer_description_form(rendered_html) != form:
        raise ProductionPlanError(
            f"{label} description form differs from its rendered structure"
        )
    if label == "candidate":
        word_count = description.get("word_count")
        rendered_text = description_text(rendered_html)
        actual_word_count = len(
            re.findall(
                r"\b[^\W_]+(?:[-'][^\W_]+)*\b",
                rendered_text or "",
                flags=re.UNICODE,
            )
        )
        approved_range = {
            "Short": range(0, 120),
            "Standard": range(120, 221),
            "Series": range(220, 351),
        }[form]
        if (
            not isinstance(word_count, int)
            or isinstance(word_count, bool)
            or (require_exact_word_count and word_count != actual_word_count)
            or word_count not in approved_range
            or actual_word_count not in approved_range
            or description.get("attestation_included") is not False
        ):
            raise ProductionPlanError(
                "candidate description length or attestation state is invalid"
            )
    keywords = state.get("keywords")
    if not isinstance(keywords, list) or not keywords or not all(
        isinstance(item, str) and item for item in keywords
    ):
        raise ProductionPlanError(f"{label} keywords must be an ordered string list")
    if len(keywords) != len(set(keywords)):
        raise ProductionPlanError(f"{label} keywords are ambiguous")


def _validate_two_state_metadata_objects(
    metadata: dict[str, Any], label: str
) -> None:
    resource_type = _required_object(metadata, "resource_type", label)
    license_value = _required_object(metadata, "license", label)
    _require_exact_fields(resource_type, {"id", "title"}, f"{label} resource type")
    _require_exact_fields(license_value, {"id", "title"}, f"{label} license")
    for key in ("title", "access", "copyright", "language"):
        _required_text(metadata, key, label)
    if label == "candidate metadata" or "publisher" in metadata:
        _required_text(metadata, "publisher", label)
    if "publication_date" in metadata:
        _required_text(metadata, "publication_date", label)
    if "version" in metadata:
        _required_text(metadata, "version", label)


def _published_baseline_family_manifest(package: dict[str, Any]) -> dict[str, Any]:
    baseline = _required_object(package, "published_baseline", "two-state manifest")
    zenodo = deepcopy(_required_object(baseline, "zenodo", "published baseline"))
    zenodo["target_version"] = zenodo.pop("version")
    return {"zenodo": zenodo}


def _validate_two_state_intent(
    package: dict[str, Any], intent: ProductionDraftIntent
) -> None:
    candidate = _required_object(package, "candidate", "two-state manifest")
    production_identity = _required_object(
        candidate, "production_identity", "candidate"
    )
    if intent.next_version != _required_text(
        production_identity, "target_version", "candidate production identity"
    ):
        raise ProductionPlanError(
            "production draft intent differs from the approved candidate version"
        )


def _two_state_candidate_manifest(package: dict[str, Any]) -> dict[str, Any]:
    baseline = _required_object(package, "published_baseline", "two-state manifest")
    baseline_zenodo = _required_object(baseline, "zenodo", "published baseline")
    candidate = _required_object(package, "candidate", "two-state manifest")
    candidate_github = deepcopy(_required_object(candidate, "github", "candidate"))
    production_identity = _required_object(
        candidate, "production_identity", "candidate"
    )
    candidate_metadata = deepcopy(
        _required_object(candidate, "metadata", "candidate")
    )
    candidate_md5 = _required_text(
        production_identity, "archival_md5", "candidate production identity"
    )
    return {
        "schema_version": "zenetism-publication-engine-v2-stage-1",
        "record_key": _required_text(package, "record_key", "two-state manifest"),
        "corpus_classification": _required_text(
            package, "corpus_classification", "two-state manifest"
        ),
        "github": candidate_github,
        "zenodo": {
            "record_id": _required_text(
                baseline_zenodo, "record_id", "published baseline zenodo"
            ),
            "concept_record_id": _required_text(
                baseline_zenodo, "concept_record_id", "published baseline zenodo"
            ),
            "exact_version_doi": _required_text(
                baseline_zenodo, "exact_version_doi", "published baseline zenodo"
            ),
            "concept_doi": _required_text(
                baseline_zenodo, "concept_doi", "published baseline zenodo"
            ),
            "previous_version_doi": _required_text(
                production_identity,
                "previous_exact_version_doi",
                "candidate production identity",
            ),
            "target_version": _required_text(
                production_identity, "target_version", "candidate production identity"
            ),
            "record_revision": baseline_zenodo.get("record_revision"),
            "version_family_index": baseline_zenodo.get("version_family_index"),
            "is_latest": baseline_zenodo.get("is_latest"),
            "publication_date": _required_text(
                production_identity, "publication_date", "candidate production identity"
            ),
            "archival_filename": _required_text(
                production_identity, "archival_filename", "candidate production identity"
            ),
            "archival_byte_size": production_identity.get("archival_byte_size"),
            "archival_checksum": f"md5:{candidate_md5}",
            "archival_sha256": _required_text(
                production_identity, "archival_sha256", "candidate production identity"
            ),
            "archival_md5": candidate_md5,
            "metadata": candidate_metadata,
            "version_family": deepcopy(baseline_zenodo.get("version_family")),
        },
        "creator": deepcopy(_required_object(candidate, "creator", "candidate")),
        "contributors": deepcopy(candidate.get("contributors")),
        "repository_url": _required_text(candidate, "repository_url", "candidate"),
        "description": deepcopy(
            _required_object(candidate, "description", "candidate")
        ),
        "keywords": deepcopy(candidate.get("keywords")),
        "related_identifiers": deepcopy(candidate.get("related_identifiers")),
        "site_relation": deepcopy(
            _required_object(candidate, "site_relation", "candidate")
        ),
        "preview": deepcopy(_required_object(candidate, "preview", "candidate")),
        "comparison": {
            "payload_status": "matching",
            "byte_size_status": "matching",
            "sha256_status": "matching",
            "md5_status": "matching",
        },
        "publication": deepcopy(
            _required_object(package, "publication", "two-state manifest")
        ),
    }


def _exact_two_state_registry_identity(
    package: dict[str, Any], registry_path: str | Path
) -> dict[str, str]:
    path = Path(registry_path)
    if not path.is_file():
        raise ProductionPlanError("production planning requires the publication registry")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = [dict(item) for item in csv.DictReader(stream)]
    baseline = _required_object(package, "published_baseline", "two-state manifest")
    github = _required_object(baseline, "github", "published baseline")
    zenodo = _required_object(baseline, "zenodo", "published baseline")
    canonical_filename = _required_text(
        github, "canonical_filename", "published baseline github"
    )
    matches = [item for item in rows if item.get("canonical_filename") == canonical_filename]
    if len(matches) != 1:
        raise ProductionPlanError(
            "publication registry requires one exact published-baseline row"
        )
    row = matches[0]
    candidate = _required_object(package, "candidate", "two-state manifest")
    production_identity = _required_object(
        candidate, "production_identity", "candidate"
    )
    target_version = _required_text(
        production_identity, "target_version", "candidate production identity"
    )
    expected = {
        "canonical_filename": canonical_filename,
        "github_directory": _required_text(
            github, "directory", "published baseline github"
        ),
        "github_commit": _required_text(
            github, "commit", "published baseline github"
        ),
        "github_sha256": _required_text(
            github, "sha256", "published baseline github"
        ),
        "github_md5": _required_text(github, "md5", "published baseline github"),
        "concept_doi": _required_text(
            zenodo, "concept_doi", "published baseline zenodo"
        ),
        "latest_version_label": _required_text(
            zenodo, "version", "published baseline zenodo"
        ),
        "latest_version_doi": _required_text(
            zenodo, "exact_version_doi", "published baseline zenodo"
        ),
        "zenodo_archival_filename": _required_text(
            zenodo, "archival_filename", "published baseline zenodo"
        ),
        "zenodo_checksum": _required_text(
            zenodo, "archival_checksum", "published baseline zenodo"
        ),
        "publication_date": _required_text(
            zenodo, "publication_date", "published baseline zenodo"
        ),
        "metadata_status": "validated",
        "file_status": "matching",
        "site_relation_status": f"absent — {target_version} conformance prepared",
        "architect_approval_state": (
            f"published baseline — {target_version} architect review required"
        ),
    }
    mismatches = [key for key, expected_value in expected.items() if row.get(key) != expected_value]
    if mismatches:
        raise ProductionPlanError(
            "publication registry differs from the approved published baseline: "
            + ", ".join(mismatches)
        )
    result = {key: row[key] for key in expected}
    result["zenodo_byte_size"] = str(
        _required_positive_int(zenodo, "archival_byte_size", "published baseline zenodo")
    )
    return result


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


def _family_member_identity(
    value: object,
) -> tuple[str, str, str, str, int]:
    if not isinstance(value, dict):
        raise ProductionFamilyError("production family member must be an object")
    record_id = _record_id(value)
    exact_doi = _supported_doi(
        value, _EXACT_DOI_PATHS, "production exact-version DOI"
    )
    concept_doi = _supported_doi(
        value, _CONCEPT_DOI_PATHS, "production concept DOI"
    )
    metadata = value.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ProductionFamilyError(
            "production family member metadata must be an object"
        )
    metadata = metadata if isinstance(metadata, dict) else {}
    version_label = metadata.get("version", value.get("version_label"))
    if (
        not isinstance(version_label, str)
        or VERSION_RE.fullmatch(version_label) is None
    ):
        raise ProductionFamilyError(
            "production family member requires an explicit vN version label"
        )

    legacy_versions = _legacy_versions(value)
    legacy_indices: list[int] = []
    for container, key in (
        (legacy_versions, "index"),
        (value, "family_index"),
    ):
        if key not in container:
            continue
        candidate = container[key]
        if not isinstance(candidate, int) or isinstance(candidate, bool):
            raise ProductionFamilyError(
                "production family member requires an integer family index"
            )
        legacy_indices.append(candidate)
    if len(set(legacy_indices)) > 1:
        raise ProductionFamilyError(
            "production family member contains conflicting legacy family indices"
        )

    relation = _invenio_version_relation(
        value,
        record_id=record_id,
        concept_doi=concept_doi,
    )
    supported_indices = list(legacy_indices)
    if relation is not None:
        # InvenioRDM exposes a zero-based relation index. The engine preserves
        # its established one-based manifest index through this exact mapping.
        supported_indices.append(relation["index"] + 1)
    if not supported_indices:
        raise ProductionFamilyError(
            "production family member requires explicit family-index evidence"
        )
    if len(set(supported_indices)) != 1:
        raise ProductionFamilyError(
            "production family member contains conflicting family-index representations"
        )
    family_index = supported_indices[0]
    if family_index <= 0:
        raise ProductionFamilyError(
            "production family member family index must be positive"
        )
    return record_id, exact_doi, concept_doi, version_label, family_index


def _explicit_family_latest_state(value: object) -> bool | None:
    if not isinstance(value, dict):
        raise ProductionFamilyError("production family member must be an object")
    legacy_versions = _legacy_versions(value)
    observed: list[bool] = []
    for container, key in (
        (legacy_versions, "is_latest"),
        (value, "is_latest"),
    ):
        if key not in container:
            continue
        candidate = container[key]
        if not isinstance(candidate, bool):
            raise ProductionFamilyError(
                "production family member latest-state marker must be boolean"
            )
        observed.append(candidate)

    record_id = _record_id(value)
    concept_doi = _supported_doi(
        value, _CONCEPT_DOI_PATHS, "production concept DOI"
    )
    relation = _invenio_version_relation(
        value,
        record_id=record_id,
        concept_doi=concept_doi,
    )
    if relation is not None and "is_last" in relation:
        observed.append(relation["is_last"])
    if len(set(observed)) > 1:
        raise ProductionFamilyError(
            "production family member contains conflicting latest-state representations"
        )
    return observed[0] if observed else None


def _legacy_versions(value: dict[str, Any]) -> dict[str, Any]:
    versions = value.get("versions")
    if versions is None:
        return {}
    if not isinstance(versions, dict):
        raise ProductionFamilyError(
            "production family member legacy versions field must be an object"
        )
    return versions


def _invenio_version_relation(
    value: dict[str, Any],
    *,
    record_id: str,
    concept_doi: str,
) -> dict[str, Any] | None:
    metadata = value.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    relations = metadata.get("relations")
    if relations is None:
        return None
    if not isinstance(relations, dict):
        raise ProductionFamilyError(
            "production family metadata relations must be an object"
        )
    version_relations = relations.get("version")
    if version_relations is None:
        return None
    if not isinstance(version_relations, list) or len(version_relations) != 1:
        raise ProductionFamilyError(
            "production family version relation must contain exactly one entry"
        )
    relation = version_relations[0]
    if not isinstance(relation, dict):
        raise ProductionFamilyError(
            "production family version relation entry must be an object"
        )
    allowed = {"index", "is_last", "parent"}
    required = {"index", "parent"}
    if not required.issubset(relation) or not set(relation).issubset(allowed):
        raise ProductionFamilyError(
            "production family version relation contains missing or unsupported fields"
        )
    relation_index = relation.get("index")
    if (
        not isinstance(relation_index, int)
        or isinstance(relation_index, bool)
        or relation_index < 0
    ):
        raise ProductionFamilyError(
            "production family version relation index must be a non-negative integer"
        )
    if "is_last" in relation and not isinstance(relation.get("is_last"), bool):
        raise ProductionFamilyError(
            "production family version relation latest-state marker must be boolean"
        )
    parent = relation.get("parent")
    if not isinstance(parent, dict) or set(parent) != {"pid_type", "pid_value"}:
        raise ProductionFamilyError(
            "production family version relation parent is malformed"
        )
    parent_id = parent.get("pid_value")
    if parent.get("pid_type") != "recid" or not isinstance(parent_id, str):
        raise ProductionFamilyError(
            "production family version relation parent identity is unsupported"
        )
    concept_match = _PRODUCTION_CONCEPT_DOI.fullmatch(concept_doi)
    if concept_match is None or parent_id != concept_match.group(1):
        raise ProductionFamilyError(
            "production family version relation parent differs from the concept identity"
        )
    _fixed_family_relation_path(
        value,
        relation="versions",
        expected_record_id=record_id,
    )
    _fixed_family_relation_path(
        value,
        relation="latest",
        expected_record_id=record_id,
    )
    return relation


def _fixed_family_relation_path(
    value: object,
    *,
    relation: str,
    expected_record_id: str,
) -> str:
    if relation not in {"latest", "versions"}:
        raise ProductionFamilyError(
            "production family relation name is unsupported"
        )
    if not isinstance(value, dict):
        raise ProductionFamilyError("production family member must be an object")
    links = value.get("links")
    if not isinstance(links, dict):
        raise ProductionFamilyError(
            "production family member requires fixed relation links"
        )
    relation_url = links.get(relation)
    if not isinstance(relation_url, str) or not relation_url:
        raise ProductionFamilyError(
            f"production family member requires a fixed {relation} relation"
        )
    parsed = urlsplit(relation_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProductionFamilyError(
            f"production family {relation} relation contains an invalid port"
        ) from exc
    suffix = "/latest" if relation == "latest" else ""
    expected_path = f"/api/records/{expected_record_id}/versions{suffix}"
    environment = production_environment()
    if (
        parsed.scheme != "https"
        or parsed.hostname != "zenodo.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
        or relation_url != f"{environment.origin}{expected_path}"
    ):
        raise ProductionFamilyError(
            f"production family {relation} relation falls outside the fixed production identity"
        )
    return expected_path


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


def _required_positive_int(value: dict[str, Any], key: str, label: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result <= 0:
        raise ProductionPlanError(f"{label} requires positive integer field {key}")
    return result


def _required_digest(
    value: dict[str, Any], key: str, length: int, label: str
) -> str:
    result = _required_text(value, key, label)
    if re.fullmatch(f"[0-9a-f]{{{length}}}", result) is None:
        raise ProductionPlanError(f"{label} requires lowercase hexadecimal field {key}")
    return result


def _require_exact_fields(
    value: dict[str, Any], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise ProductionPlanError(
            f"{label} contains missing or unsupported fields"
        )


def _require_fields_with_optional(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    fields = set(value)
    if not required.issubset(fields) or not fields.issubset(required | optional):
        raise ProductionPlanError(
            f"{label} contains missing or unsupported fields"
        )
