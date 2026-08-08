"""Exact serialization of approved manifests into InvenioRDM draft metadata."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .archival import ArchivalCopy, require_approved_manifest
from .errors import ManifestApprovalError
from .naming import require_document_version

ROLE_IDS = {"Researcher": "researcher"}
RELATION_IDS = {"IsDocumentedBy": "isdocumentedby"}
DESCRIPTION_FORMS = frozenset({"Short", "Standard", "Series"})


@dataclass(frozen=True)
class SandboxDraftPackage:
    record_key: str
    description_form: str
    archival_copy: ArchivalCopy
    existing_dois_not_supplied: tuple[str, ...]
    create_payload: dict[str, Any]
    saved_payload: dict[str, Any]

    def audit_summary(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "description_form": self.description_form,
            "doi_behavior": "reserve_sandbox_doi",
            "existing_doi_supplied": False,
            "archival_copy": self.archival_copy.audit_summary(),
            "saved_draft": deepcopy(self.saved_payload),
        }


def serialize_sandbox_draft(
    manifest: object, archival_copy: ArchivalCopy
) -> SandboxDraftPackage:
    approved = require_approved_manifest(manifest)
    zenodo = _object(approved, "zenodo")
    metadata_source = _object(zenodo, "metadata")
    creator = _object(approved, "creator")
    description = _object(approved, "description")
    site_relation = _object(approved, "site_relation")
    description_form = _string(description, "form")
    if description_form not in DESCRIPTION_FORMS:
        raise ManifestApprovalError("description form must be Short, Standard, or Series")

    version = require_document_version(_string(zenodo, "target_version"))
    access = _string(metadata_source, "access")
    if access != "Open":
        raise ManifestApprovalError("Stage 2A supports only approved Open-access drafts")

    contributors = approved.get("contributors")
    if not isinstance(contributors, list):
        raise ManifestApprovalError("manifest contributors must be an explicit list")
    keywords = approved.get("keywords")
    if not isinstance(keywords, list) or not all(
        isinstance(item, str) and item for item in keywords
    ):
        raise ManifestApprovalError("manifest keywords must be a non-empty ordered string list")
    related = approved.get("related_identifiers")
    if not isinstance(related, list):
        raise ManifestApprovalError("manifest related_identifiers must be an explicit list")
    if site_relation not in related:
        raise ManifestApprovalError(
            "the approved Site relation is absent from related identifiers"
        )

    resource_type = _object(metadata_source, "resource_type")
    license_value = _object(metadata_source, "license")
    metadata = {
        "resource_type": {"id": _string(resource_type, "id")},
        "title": _string(metadata_source, "title"),
        "publication_date": _string(zenodo, "publication_date"),
        "creators": [_creator(creator)],
        "contributors": [_contributor(item) for item in contributors],
        "description": _string(description, "rendered_html"),
        "subjects": [{"subject": item} for item in keywords],
        "version": version,
        "rights": [{"id": _string(license_value, "id")}],
        "copyright": _string(metadata_source, "copyright"),
        "languages": [{"id": _string(metadata_source, "language")}],
        "related_identifiers": [_related_identifier(item) for item in related],
    }
    common = {
        "access": {"record": "public", "files": "public"},
        "metadata": metadata,
        "custom_fields": {
            "code:codeRepository": _precise_repository_url(approved)
        },
    }
    create_payload = deepcopy(common)
    create_payload["files"] = {"enabled": True}
    saved_payload = deepcopy(common)
    saved_payload["files"] = {
        "enabled": True,
        "default_preview": archival_copy.archival_filename,
        "order": [archival_copy.archival_filename],
    }
    return SandboxDraftPackage(
        record_key=_top_level_string(approved, "record_key"),
        description_form=description_form,
        archival_copy=archival_copy,
        existing_dois_not_supplied=tuple(
            value
            for value in (
                zenodo.get("exact_version_doi"),
                zenodo.get("concept_doi"),
                zenodo.get("previous_version_doi"),
            )
            if isinstance(value, str) and value
        ),
        create_payload=create_payload,
        saved_payload=saved_payload,
    )


def _creator(value: dict[str, Any]) -> dict[str, Any]:
    family_name = _string(value, "family_name")
    given_names = value.get("given_names")
    rendered_name = _string(value, "rendered_name")
    if given_names != "" or rendered_name != family_name:
        raise ManifestApprovalError(
            "creator must preserve the family-name-only Aelion Kannon convention"
        )
    return {
        "person_or_org": {
            "type": "personal",
            "family_name": family_name,
            "given_name": "",
        }
    }


def _contributor(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestApprovalError("each contributor must be an object")
    name = _string(value, "name")
    role = _string(value, "role")
    role_id = ROLE_IDS.get(role)
    if role_id is None:
        raise ManifestApprovalError(f"unsupported approved contributor role: {role}")
    return {
        "person_or_org": {
            "type": "personal",
            "family_name": name,
            "given_name": "",
        },
        "role": {"id": role_id},
    }


def _related_identifier(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestApprovalError("each related identifier must be an object")
    relation = _string(value, "relation")
    relation_id = RELATION_IDS.get(relation)
    if relation_id is None:
        raise ManifestApprovalError(f"unsupported approved relation: {relation}")
    scheme = _string(value, "scheme")
    resource_type = _string(value, "resource_type")
    return {
        "identifier": _string(value, "identifier"),
        "scheme": scheme.casefold(),
        "relation_type": {"id": relation_id},
        "resource_type": {"id": resource_type.casefold()},
    }


def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ManifestApprovalError(f"manifest field {key} must be an object")
    return result


def _string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ManifestApprovalError(f"manifest field {key} is required")
    return result


def _top_level_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ManifestApprovalError(f"manifest field {key} is required")
    return result


def _precise_repository_url(manifest: dict[str, Any]) -> str:
    github = _object(manifest, "github")
    expected = (
        f"https://github.com/{_string(github, 'repository')}"
        f"/tree/{_string(github, 'branch')}/{_string(github, 'directory').strip('/')}"
    )
    observed = _top_level_string(manifest, "repository_url")
    if observed != expected:
        raise ManifestApprovalError(
            "Repository URL must identify the precise approved GitHub directory"
        )
    return observed
