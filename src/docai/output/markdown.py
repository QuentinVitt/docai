from __future__ import annotations

import logging
import os

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import DocItem, DocItemType, FileDoc, FileDocType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity renderer
# ---------------------------------------------------------------------------


def _render_entity(doc: DocItem) -> str:
    lines: list[str] = [f"### `{doc.name}`"]
    if doc.parent:
        lines.append(f"*{doc.type} of `{doc.parent}`*")
    else:
        lines.append(f"*{doc.type}*")
    lines.append("")
    lines.append(doc.description)

    if doc.type in (DocItemType.FUNCTION, DocItemType.METHOD):
        if doc.parameters:
            lines.append("")
            lines.append("**Parameters:**")
            lines.append("")
            lines.append("| Name | Type | Description |")
            lines.append("|------|------|-------------|")
            for p in doc.parameters:
                type_col = f"`{p.type_hint}`" if p.type_hint else "—"
                lines.append(f"| `{p.name}` | {type_col} | {p.description} |")
        if doc.returns:
            lines.append("")
            type_part = f"`{doc.returns.type_hint}` — " if doc.returns.type_hint else ""
            lines.append(f"**Returns:** {type_part}{doc.returns.description}")
        if doc.raises:
            lines.append("")
            lines.append("**Raises:**")
            lines.append("")
            for r in doc.raises:
                lines.append(f"- `{r.exception}`: {r.description}")
        if doc.side_effects:
            lines.append("")
            lines.append(f"**Side effects:** {doc.side_effects}")

    if doc.type in (DocItemType.CLASS, DocItemType.DATATYPE):
        if doc.attributes:
            lines.append("")
            lines.append("**Attributes:**")
            lines.append("")
            lines.append("| Name | Type | Description |")
            lines.append("|------|------|-------------|")
            for a in doc.attributes:
                type_col = f"`{a.type_hint}`" if a.type_hint else "—"
                lines.append(f"| `{a.name}` | {type_col} | {a.description} |")
        if doc.dunder_methods:
            lines.append("")
            methods = ", ".join(f"`{m}`" for m in doc.dunder_methods)
            lines.append(f"**Dunder methods:** {methods}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File renderer
# ---------------------------------------------------------------------------


def _render_file(file_doc: FileDoc, entity_docs: list[DocItem]) -> str:
    filename = os.path.basename(file_doc.path)
    lines: list[str] = [
        f"# {filename}",
        "",
        f"**Type:** {file_doc.type}",
        "",
        file_doc.description,
    ]

    if not entity_docs:
        return "\n".join(lines)

    # Group entities by type for organised sections
    sections: dict[str, list[DocItem]] = {}
    order = [
        DocItemType.CLASS,
        DocItemType.DATATYPE,
        DocItemType.FUNCTION,
        DocItemType.METHOD,
        DocItemType.CONSTANT,
    ]
    for t in order:
        group = [d for d in entity_docs if d.type == t]
        if group:
            sections[
                t.value.capitalize() + ("s" if not t.value.endswith("s") else "")
            ] = group

    for section_title, items in sections.items():
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## {section_title}")
        for item in items:
            lines.append("")
            lines.append(_render_entity(item))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Package renderer
# ---------------------------------------------------------------------------


def _render_package(pkg_doc, output_dir: str) -> str:
    pkg_name = pkg_doc.path.split(os.sep)[-1] if pkg_doc.path else pkg_doc.path
    lines: list[str] = [
        f"# {pkg_name}",
        "",
        f"**Path:** `{pkg_doc.path}`",
        "",
        pkg_doc.description,
    ]

    if pkg_doc.files:
        lines.append("")
        lines.append("## Files")
        lines.append("")
        for f in sorted(pkg_doc.files):
            stem = os.path.splitext(os.path.basename(f))[0]
            lines.append(f"- [{os.path.basename(f)}]({stem}.md)")

    if pkg_doc.packages:
        lines.append("")
        lines.append("## Sub-packages")
        lines.append("")
        for sp in sorted(pkg_doc.packages):
            sp_name = sp.split(os.sep)[-1]
            lines.append(f"- [{sp_name}]({sp_name}/package.md)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Project renderer
# ---------------------------------------------------------------------------


def _render_project(project_doc, top_level_packages: list[str]) -> str:
    lines: list[str] = [
        f"# {project_doc.name}",
        "",
        project_doc.description,
    ]

    if top_level_packages:
        lines.append("")
        lines.append("## Packages")
        lines.append("")
        for pkg in sorted(top_level_packages):
            pkg_name = pkg.split(os.sep)[-1]
            lines.append(f"- [{pkg}]({pkg}/package.md)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def write_markdown_docs(
    project_path: str,
    project_name: str,
    packages: dict[str, dict],
    project_files_info: dict[str, dict],
    cache: DocumentationCache,
) -> None:
    output_dir = os.path.join(project_path, "docs")
    os.makedirs(output_dir, exist_ok=True)

    # Write project.md
    project_doc = cache.get_project_documentation(project_name)
    if project_doc is not None:
        top_level_packages = [p for p in packages if os.path.dirname(p) not in packages]
        _write(
            os.path.join(output_dir, "project.md"),
            _render_project(project_doc, top_level_packages),
        )

    # Write package.md for each package
    for pkg_path, _pkg_info in packages.items():
        pkg_doc = cache.get_package_documentation(pkg_path)
        if pkg_doc is None:
            continue
        pkg_out_dir = os.path.join(output_dir, pkg_path)
        os.makedirs(pkg_out_dir, exist_ok=True)
        _write(
            os.path.join(pkg_out_dir, "package.md"),
            _render_package(pkg_doc, output_dir),
        )

    # Write {stem}.md for each documented file
    for file_path, file_info in project_files_info.items():
        if file_info.get("file_doc_type") in (None, FileDocType.SKIPPED):
            continue
        file_doc = cache.get_file_documentation(file_path)
        if file_doc is None or not file_doc.description:
            continue

        entity_docs = [
            doc
            for entity in file_info.get("entities", [])
            if (doc := cache.get_entity_documentation(file_path, entity)) is not None
        ]

        stem = os.path.splitext(os.path.basename(file_path))[0]
        file_dir = os.path.dirname(file_path)
        out_dir = os.path.join(output_dir, file_dir) if file_dir else output_dir
        os.makedirs(out_dir, exist_ok=True)
        _write(os.path.join(out_dir, f"{stem}.md"), _render_file(file_doc, entity_docs))

    logger.info("Markdown documentation written to %s", output_dir)


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.debug("Wrote %s", path)
