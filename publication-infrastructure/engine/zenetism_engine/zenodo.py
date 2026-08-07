"""Read-only retrieval and normalization of public Zenodo published records."""

from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import quote

from .errors import RecordShapeError, VersionFamilyError
from .hashing import calculate_checksums
from .http import ReadOnlyHttpClient
from .models import Person, RelatedIdentifier, VersionMember, ZenodoPublishedRecord
from .naming import VERSION_RE, archival_filename

ZENODO_IDENTIFIER_RE = re.compile(r"(?:zenodo\.|/records/)([0-9]+)(?:$|[/?#])", re.IGNORECASE)


class ZenodoClient:
    api_root = "https://zenodo.org/api/records"

    def __init__(self, http: ReadOnlyHttpClient | None = None) -> None:
        self.http = http or ReadOnlyHttpClient()
        self.headers = {
            "Accept": "application/vnd.inveniordm.v1+json",
            "User-Agent": "zenetism-publication-engine-stage1",
        }

    def fetch_published_record(
        self, identifier: str, *, canonical_filename: str | None = None
    ) -> ZenodoPublishedRecord:
        requested_id = record_id_from_identifier(identifier)
        record, _ = self.http.get_json(
            f"{self.api_root}/{quote(requested_id, safe='')}", headers=self.headers
        )
        if record.get("is_published") is not True or record.get("status") != "published":
            raise RecordShapeError(f"Zenodo record {requested_id} is not a published record")

        versions_url = _required_path(record, ("links", "versions"), "Zenodo record")
        family_hits = self._fetch_version_family(versions_url)
        if not family_hits:
            raise RecordShapeError("Zenodo versions response contains no family members")

        metadata = _required_dict(record.get("metadata"), "Zenodo metadata")
        version_label = metadata.get("version") if isinstance(metadata.get("version"), str) else None
        file_entry = _select_file(record, canonical_filename, version_label)
        content_url = _required_path(file_entry, ("links", "content"), "Zenodo file")
        payload = self.http.get(content_url, headers={"User-Agent": self.headers["User-Agent"]}).body
        checksums = calculate_checksums(payload)
        _verify_advertised_file(file_entry, checksums.byte_size, checksums.md5)

        exact_doi = _required_path(record, ("pids", "doi", "identifier"), "Zenodo record")
        concept_doi = _required_path(
            record, ("parent", "pids", "doi", "identifier"), "Zenodo parent"
        )
        if exact_doi == concept_doi:
            raise VersionFamilyError("Zenodo exact-version DOI equals concept DOI")

        creators = tuple(_people(metadata.get("creators"), contributor=False))
        contributors = tuple(_people(metadata.get("contributors"), contributor=True))
        related = tuple(_related_identifiers(metadata.get("related_identifiers")))
        rights = metadata.get("rights") if isinstance(metadata.get("rights"), list) else []
        right = rights[0] if rights and isinstance(rights[0], dict) else {}
        languages = metadata.get("languages") if isinstance(metadata.get("languages"), list) else []
        language = languages[0].get("id") if languages and isinstance(languages[0], dict) else None
        resource_type = metadata.get("resource_type")
        resource_type = resource_type if isinstance(resource_type, dict) else {}
        custom_fields = record.get("custom_fields")
        custom_fields = custom_fields if isinstance(custom_fields, dict) else {}
        files = _required_dict(record.get("files"), "Zenodo files")
        versions = record.get("versions")
        versions = versions if isinstance(versions, dict) else {}
        access = record.get("ui")
        access = access if isinstance(access, dict) else {}
        access_status = access.get("access_status")
        access_status = access_status if isinstance(access_status, dict) else {}

        version_family = tuple(
            sorted((_version_member(item) for item in family_hits), key=_version_sort_key)
        )
        current_id = str(_required_scalar(record.get("id"), "Zenodo record id"))
        if not any(member.record_id == current_id for member in version_family):
            raise VersionFamilyError("resolved Zenodo record is absent from its version family")

        return ZenodoPublishedRecord(
            requested_identifier=identifier,
            record_id=current_id,
            concept_record_id=str(
                _required_path(record, ("parent", "id"), "Zenodo parent")
            ),
            exact_version_doi=exact_doi,
            concept_doi=concept_doi,
            version_label=version_label,
            record_revision=_optional_int(record.get("revision_id")),
            family_index=_optional_int(versions.get("index")),
            is_latest=versions.get("is_latest") is True,
            publication_date=_optional_str(metadata.get("publication_date")),
            archival_filename=_required_str(file_entry.get("key"), "Zenodo archival filename"),
            advertised_checksum=_required_str(
                file_entry.get("checksum"), "Zenodo advertised checksum"
            ),
            checksums=checksums,
            payload=payload,
            title=_optional_str(metadata.get("title")),
            description=_optional_str(metadata.get("description")),
            keywords=tuple(_keywords(metadata.get("subjects"))),
            creator=creators[0] if creators else None,
            contributors=contributors,
            repository_url=_optional_str(custom_fields.get("code:codeRepository")),
            related_identifiers=related,
            copyright=_optional_str(metadata.get("copyright")),
            resource_type_id=_optional_str(resource_type.get("id")),
            resource_type_title=_localized(resource_type.get("title")),
            access=_optional_str(access_status.get("title_l10n"))
            or _optional_str(access_status.get("id")),
            license_id=_optional_str(right.get("id")),
            license_title=_localized(right.get("title")),
            language=_optional_str(language),
            default_preview=_optional_str(files.get("default_preview")),
            version_family=version_family,
            raw_metadata=dict(metadata),
        )

    def _fetch_version_family(self, first_url: str) -> list[dict[str, Any]]:
        url: str | None = first_url
        result: list[dict[str, Any]] = []
        pages = 0
        while url is not None:
            pages += 1
            if pages > 100:
                raise RecordShapeError("Zenodo version-family pagination exceeded 100 pages")
            page, _ = self.http.get_json(url, headers=self.headers)
            hits = _required_path(page, ("hits", "hits"), "Zenodo versions")
            if not isinstance(hits, list):
                raise RecordShapeError("Zenodo version-family hits must be a list")
            for item in hits:
                result.append(_required_dict(item, "Zenodo version family member"))
            links = page.get("links")
            links = links if isinstance(links, dict) else {}
            next_url = links.get("next")
            url = next_url if isinstance(next_url, str) and next_url else None
        return result


def record_id_from_identifier(identifier: str) -> str:
    stripped = identifier.strip()
    if stripped.isdigit():
        return stripped
    match = ZENODO_IDENTIFIER_RE.search(stripped)
    if not match:
        raise RecordShapeError(f"cannot extract a Zenodo record id from {identifier!r}")
    return match.group(1)


def _select_file(
    record: dict[str, Any], canonical_filename: str | None, version_label: str | None
) -> dict[str, Any]:
    entries = _required_path(record, ("files", "entries"), "Zenodo files")
    if not isinstance(entries, dict) or not entries:
        raise RecordShapeError("Zenodo published record has no downloadable files")
    if canonical_filename is not None and version_label is not None and VERSION_RE.fullmatch(version_label):
        expected = archival_filename(canonical_filename, version_label)
        selected = entries.get(expected)
        if isinstance(selected, dict):
            return selected
        # A single historical file can still be retrieved and then fail the
        # naming invariant explicitly; retrieval itself must not rewrite it.
        if len(entries) == 1:
            return _required_dict(next(iter(entries.values())), "Zenodo file entry")
        raise RecordShapeError(
            f"Zenodo record has multiple files and does not contain expected archival file {expected}"
        )
    if len(entries) != 1:
        raise RecordShapeError(
            "Zenodo record has multiple files and no explicit vN filename can be selected"
        )
    selected = next(iter(entries.values()))
    return _required_dict(selected, "Zenodo file entry")


def _verify_advertised_file(file_entry: dict[str, Any], size: int, md5: str) -> None:
    advertised_size = file_entry.get("size")
    if not isinstance(advertised_size, int) or advertised_size != size:
        raise RecordShapeError(
            f"Zenodo byte-size mismatch: API={advertised_size!r}, downloaded={size}"
        )
    advertised_checksum = file_entry.get("checksum")
    if not isinstance(advertised_checksum, str) or advertised_checksum != f"md5:{md5}":
        raise RecordShapeError(
            f"Zenodo checksum mismatch: API={advertised_checksum!r}, downloaded='md5:{md5}'"
        )


def _version_member(item: object) -> VersionMember:
    value = _required_dict(item, "Zenodo version family member")
    metadata = value.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    versions = value.get("versions")
    versions = versions if isinstance(versions, dict) else {}
    label = metadata.get("version") if isinstance(metadata.get("version"), str) else None
    return VersionMember(
        record_id=str(_required_scalar(value.get("id"), "Zenodo family record id")),
        exact_version_doi=_required_path(
            value, ("pids", "doi", "identifier"), "Zenodo family member"
        ),
        version_label=label,
        record_revision=_optional_int(value.get("revision_id")),
        family_index=_optional_int(versions.get("index")),
        is_latest=versions.get("is_latest") is True,
    )


def _version_sort_key(member: VersionMember) -> tuple[int, str]:
    return (member.family_index if member.family_index is not None else 2**31, member.record_id)


def _people(value: object, *, contributor: bool) -> Iterable[Person]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RecordShapeError("Zenodo creator/contributor metadata is not a list")
    result: list[Person] = []
    for entry in value:
        item = _required_dict(entry, "Zenodo person")
        person = item.get("person_or_org")
        person = _required_dict(person, "Zenodo person_or_org")
        role = item.get("role")
        role = role if isinstance(role, dict) else {}
        result.append(
            Person(
                name=_required_str(person.get("name"), "Zenodo rendered person name"),
                family_name=_optional_str(person.get("family_name")) or "",
                given_names=_optional_str(person.get("given_name")) or "",
                role=_localized(role.get("title")) if contributor else None,
            )
        )
    return result


def _keywords(value: object) -> Iterable[str]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RecordShapeError("Zenodo subjects metadata is not a list")
    result: list[str] = []
    for entry in value:
        item = _required_dict(entry, "Zenodo subject")
        result.append(_required_str(item.get("subject"), "Zenodo keyword"))
    return result


def _related_identifiers(value: object) -> Iterable[RelatedIdentifier]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RecordShapeError("Zenodo related identifiers metadata is not a list")
    result: list[RelatedIdentifier] = []
    for entry in value:
        item = _required_dict(entry, "Zenodo related identifier")
        relation = item.get("relation_type")
        relation = relation if isinstance(relation, dict) else {}
        resource_type = item.get("resource_type")
        resource_type = resource_type if isinstance(resource_type, dict) else {}
        relation_id = _required_str(relation.get("id"), "Zenodo relation type")
        result.append(
            RelatedIdentifier(
                identifier=_required_str(item.get("identifier"), "Zenodo related identifier"),
                relation=_canonical_relation(relation_id),
                scheme=_required_str(item.get("scheme"), "Zenodo identifier scheme").upper(),
                resource_type=_localized(resource_type.get("title"))
                or _required_str(resource_type.get("id"), "Zenodo related resource type"),
            )
        )
    return result


def _canonical_relation(value: str) -> str:
    known = {"isdocumentedby": "IsDocumentedBy"}
    return known.get(value.lower(), value)


def _localized(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in ("en", "en_US", "en-US"):
            result = value.get(key)
            if isinstance(result, str) and result:
                return result
        for result in value.values():
            if isinstance(result, str) and result:
                return result
    return None


def _required_path(value: object, path: tuple[str, ...], context: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise RecordShapeError(f"{context} omitted required {'.'.join(path)!r}")
        current = current[key]
    return current


def _required_dict(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecordShapeError(f"{context} must be an object")
    return value


def _required_str(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecordShapeError(f"{context} is missing")
    return value


def _required_scalar(value: object, context: str) -> str | int:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise RecordShapeError(f"{context} is missing")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
