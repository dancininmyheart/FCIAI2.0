from __future__ import annotations

import re
import posixpath
import zipfile
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Final
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr
from urllib.parse import unquote

from .pptx_xml_types import PptxXmlPackageError


MC_NS: Final = "http://schemas.openxmlformats.org/markup-compatibility/2006"
MC_CHOICE: Final = f"{{{MC_NS}}}Choice"
RESERVED_NAMESPACE_PREFIX_RE: Final = re.compile(r"ns\d+$")
NAMESPACE_SERIALIZATION_LOCK: Final = Lock()
REQUIRED_MEMBERS: Final = frozenset({"[Content_Types].xml", "ppt/presentation.xml"})
RELATIONSHIP_NS: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
RELATIONSHIP_TAG: Final = f"{{{RELATIONSHIP_NS}}}Relationship"


def serialize_slide_xml(source_data: bytes, root: ElementTree.Element) -> bytes:
    source_namespaces = _namespace_map(source_data)
    required = _required_prefixes(root)
    with NAMESPACE_SERIALIZATION_LOCK:
        for prefix, uri in source_namespaces.items():
            if not RESERVED_NAMESPACE_PREFIX_RE.fullmatch(prefix):
                ElementTree.register_namespace(prefix, uri)
        serialized = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    declared = _namespace_map(serialized)
    missing = {
        prefix: source_namespaces[prefix]
        for prefix in required
        if prefix not in declared and prefix in source_namespaces
    }
    unresolved = required - declared.keys() - missing.keys()
    if unresolved:
        raise PptxXmlPackageError("compatibility markup references an undeclared namespace")
    return _inject_root_namespaces(serialized, missing)


def validate_pptx_package(
    path: Path,
    expected_members: tuple[str, ...],
) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise PptxXmlPackageError("archive contains duplicate members")
            if tuple(names) != expected_members:
                raise PptxXmlPackageError("archive member inventory changed")
            if not REQUIRED_MEMBERS.issubset(names):
                raise PptxXmlPackageError("archive is missing a required member")
            if archive.testzip() is not None:
                raise PptxXmlPackageError("archive CRC validation failed")
            for name in names:
                if name.endswith((".xml", ".rels")) or name == "[Content_Types].xml":
                    _validate_xml_part(name, archive.read(name))
                if name.endswith(".rels"):
                    _validate_relationship_targets(name, archive.read(name), frozenset(names))
    except (OSError, zipfile.BadZipFile) as exc:
        raise PptxXmlPackageError("output is not a readable ZIP package") from exc


def _validate_xml_part(name: str, data: bytes) -> None:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise PptxXmlPackageError(f"XML part is malformed: {name}") from exc
    declared = _namespace_map(data)
    if not _required_prefixes(root).issubset(declared):
        raise PptxXmlPackageError(f"compatibility namespace is unresolved: {name}")


def _validate_relationship_targets(
    relationship_part: str,
    data: bytes,
    members: frozenset[str],
) -> None:
    root = ElementTree.fromstring(data)
    source_directory = posixpath.dirname(_source_part_for_relationships(relationship_part))
    for relationship in root.iter(RELATIONSHIP_TAG):
        if relationship.get("TargetMode", "").casefold() == "external":
            continue
        target = unquote(relationship.get("Target", "").split("#", 1)[0]).replace("\\", "/")
        if not target:
            raise PptxXmlPackageError(f"relationship target is empty: {relationship_part}")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
            posixpath.join(source_directory, target),
        )
        if resolved not in members:
            raise PptxXmlPackageError(f"relationship target is missing: {relationship_part}")


def _source_part_for_relationships(relationship_part: str) -> str:
    if relationship_part == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in relationship_part or not relationship_part.endswith(".rels"):
        raise PptxXmlPackageError(f"relationship part path is invalid: {relationship_part}")
    directory, filename = relationship_part.split(marker, 1)
    return f"{directory}/{filename[:-5]}"


def _namespace_map(data: bytes) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    try:
        for _, (prefix, uri) in ElementTree.iterparse(BytesIO(data), events=("start-ns",)):
            namespaces[prefix] = uri
    except ElementTree.ParseError as exc:
        raise PptxXmlPackageError("XML namespace declarations are malformed") from exc
    return namespaces


def _required_prefixes(root: ElementTree.Element) -> set[str]:
    required: set[str] = set()
    for choice in root.iter(MC_CHOICE):
        required.update(choice.get("Requires", "").split())
    return required


def _inject_root_namespaces(data: bytes, missing: dict[str, str]) -> bytes:
    if not missing:
        return data
    declaration = "".join(
        f" xmlns:{prefix}={quoteattr(uri)}"
        for prefix, uri in sorted(missing.items())
    ).encode("utf-8")
    declaration_end = data.find(b"?>")
    root_start = data.find(b"<", declaration_end + 2 if declaration_end >= 0 else 0)
    root_end = data.find(b">", root_start)
    if root_start < 0 or root_end < 0:
        raise PptxXmlPackageError("serialized slide has no root element")
    insertion = root_end - 1 if data[root_end - 1 : root_end] == b"/" else root_end
    return data[:insertion] + declaration + data[insertion:]
