"""Structure document generator — builds Mermaid diagrams, file trees,
hierarchical structure docs, and JSON data for the React viewer.

Extracted from ReviewReport to keep models.py focused on data models.
Requirements: 2.7 项目结构文档规范
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path


class _PyVisitor(ast.NodeVisitor):
    """AST visitor that extracts class and function symbols from Python source."""
    def __init__(self):
        self.symbols: list[tuple[str, list[str]]] = []
        self._in_class = False
        self._class_children: list[str] = []

    def visit_ClassDef(self, node):
        self._in_class = True
        self._class_children = []
        self.generic_visit(node)
        self.symbols.append(
            (f"class {node.name}", list(self._class_children))
        )
        self._in_class = False
        self._class_children = []

    def visit_FunctionDef(self, node):
        name = f"def {node.name}()"
        if self._in_class:
            self._class_children.append(name)
        else:
            self.symbols.append((name, []))

    def visit_AsyncFunctionDef(self, node):
        name = f"def {node.name}()"
        if self._in_class:
            self._class_children.append(name)
        else:
            self.symbols.append((name, []))


def extract_symbols(file_path: str) -> list[tuple[str, list[str]]]:
    """Extract symbols (classes/functions) from a source file.

    Returns list of (symbol_text, children) tuples where children are
    nested symbols (e.g. methods inside a class).
    """
    symbols: list[tuple[str, list[str]]] = []
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".py":
            with open(file_path) as f:
                tree = ast.parse(f.read())
            _pv = _PyVisitor()
            _pv.visit(tree)
            symbols = _pv.symbols
        elif ext in (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx"):
            with open(file_path) as f:
                content = f.read()
            for m in re.finditer(
                r"^\s*(?:static\s+|inline\s+|virtual\s+)?"
                r"(?:int|void|char|float|double|long|short|unsigned|signed|"
                r"size_t|bool|string|auto|const|volatile|struct|class|"
                r"\w+_t|FILE|char\*|void\*)\s*(\w+)\s*\(",
                content, re.MULTILINE,
            ):
                symbols.append((f"def {m.group(1)}()", []))
        elif ext == ".go":
            with open(file_path) as f:
                content = f.read()
            for m in re.finditer(
                r"^\s*(?:func\s+)(?:\([^)]*\)\s+)?(\w+)\s*\(",
                content, re.MULTILINE,
            ):
                symbols.append((f"func {m.group(1)}()", []))
        elif ext == ".rs":
            with open(file_path) as f:
                content = f.read()
            for m in re.finditer(
                r"^\s*(?:pub\s+)?(?:fn\s+)(\w+)\s*[\(<]",
                content, re.MULTILINE,
            ):
                symbols.append((f"fn {m.group(1)}()", []))
    except (SyntaxError, OSError, UnicodeDecodeError):
        pass
    return symbols


def _find_common_root(all_files: list[str]) -> str | None:
    """Find the common directory root from a list of file paths."""
    if not all_files:
        return None
    normalized = [fp.replace(os.sep, "/").rstrip("/") for fp in all_files]
    if len(normalized) == 1:
        common = os.path.dirname(normalized[0])
    else:
        common = os.path.commonprefix(normalized)
        if "/" in common:
            common = common[: common.rfind("/") + 1]
        common = common.rstrip("/")
    return common if common and os.path.isdir(common) else None


def _normalize_relative(fp: str, root: Path, scope: Path) -> str | None:
    """Return relative posix path of fp under scope, or None."""
    try:
        resolved = Path(fp).resolve()
        return resolved.relative_to(scope).as_posix()
    except ValueError:
        try:
            return Path(fp).relative_to(scope).as_posix()
        except ValueError:
            return None


_IGNORE_PARTS = frozenset({
    ".git", ".DS_Store", "__pycache__", "build", "dist",
    "node_modules", ".egg-info", "archived", ".venv", "report",
})


def build_file_tree(all_files: list[str], subdir: str | None = None) -> str:
    """Generate a compact project file tree — files in same dir grouped on one line."""
    root_dir = _find_common_root(all_files)
    if not root_dir:
        return "(no files in scope)"

    root_path = Path(root_dir).resolve()
    scope_path = (root_path / subdir) if subdir else root_path
    scope_files: list[str] = []

    for fp in all_files:
        rel = _normalize_relative(fp, root_path, scope_path)
        if rel:
            scope_files.append(rel)

    if not scope_files:
        return "(no files in scope)"

    tree: dict = {}
    for rel in sorted(scope_files):
        parts = rel.split("/")
        node = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Leaf — mark as file (not dict with children)
                node.setdefault("__files__", []).append(part)
            else:
                node = node.setdefault(part, {})

    root_label = scope_path.name if subdir else Path(root_dir).name
    lines = ["```"]
    lines.append(root_label)
    _render_tree_compact(tree, lines, prefix="")
    lines.append("```")
    return "\n".join(lines)


def _render_tree_compact(node: dict, lines: list[str], prefix: str) -> None:
    """Render tree with files grouped on one line per directory."""
    # Collect child dirs and local files
    dirs: list[str] = []
    files: list[str] = []
    for k, v in node.items():
        if k == "__files__":
            files = sorted(v)
        elif not k.startswith("__"):
            dirs.append(k)

    # Build combined item list: directories first, then file group
    items: list[tuple[str, bool]] = [(d, True) for d in sorted(dirs)]
    if files:
        file_line = ", ".join(files)
        items.append((file_line, False))

    last_idx = len(items) - 1
    for idx, (name, is_dir) in enumerate(items):
        is_last = idx == last_idx
        connector = "└── " if is_last else "├── "
        if is_dir:
            lines.append(f"{prefix}{connector}{name}")
            extension = "    " if is_last else "│   "
            _render_tree_compact(node[name], lines, prefix + extension)
        else:
            lines.append(f"{prefix}{connector}{name}")


def build_mermaid_diagram(all_files: list[str], subdir: str | None = None) -> str:
    """Generate a Mermaid flowchart — directories as nodes, files grouped within."""
    root_dir = _find_common_root(all_files)
    if not root_dir:
        return "(no files to diagram)"

    root_path = Path(root_dir).resolve()
    scope_path = (root_path / subdir) if subdir else root_path
    parent_node = scope_path.name
    max_depth = 3

    # Group files by directory path
    dir_files: dict[str, list[str]] = {}
    for fp in all_files:
        rel = _normalize_relative(fp, root_path, scope_path)
        if not rel:
            continue
        parts = rel.split("/")
        if len(parts) == 1:
            dir_files.setdefault(".", []).append(parts[0])
        else:
            dir_path = "/".join(parts[:-1])
            dir_files.setdefault(dir_path, []).append(parts[-1])

    nodes: set[str] = {parent_node}
    edges: set[tuple[str, str]] = set()

    for dir_path in sorted(dir_files):
        parts = dir_path.split("/") if dir_path != "." else []
        total_depth = len(parts)

        if total_depth == 0:
            continue  # root-relative files are handled separately

        if total_depth > max_depth:
            visible_parts = parts[:max_depth]
            visible_path = "/".join(visible_parts)
            nodes.add(visible_path)
            if max_depth == 1:
                edges.add((parent_node, visible_path))
            else:
                parent_id = "/".join(visible_parts[:-1])
                edges.add((parent_id, visible_path))
            nodes.add("...")
            edges.add((visible_path, "..."))
        else:
            # Add node for each directory depth
            for depth in range(len(parts)):
                node_id = "/".join(parts[: depth + 1])
                nodes.add(node_id)
                if depth == 0:
                    edges.add((parent_node, node_id))
                else:
                    parent_id = "/".join(parts[:depth])
                    edges.add((parent_id, node_id))

    lines = ["```mermaid", "graph TD"]
    for n in sorted(nodes):
        label = n.split("/")[-1]
        files_in_dir = dir_files.get(n, [])
        if files_in_dir:
            count = len(files_in_dir)
            label = f"{label} ({count})"
        safe_id = n.replace("/", "_").replace(".", "_").replace("-", "_")
        lines.append(f"    {safe_id}[{label}]")
    lines.append("")
    for src, dst in sorted(edges):
        src_id = src.replace("/", "_").replace(".", "_").replace("-", "_")
        dst_id = dst.replace("/", "_").replace(".", "_").replace("-", "_")
        lines.append(f"    {src_id} --> {dst_id}")
    lines.append("```")
    return "\n".join(lines)


def generate_hierarchical_structure_docs(all_files: list[str], output_dir: str) -> list[str]:
    """Write root + per-module structure.md files with Mermaid + file tree."""
    if not all_files:
        return []

    root_dir = _find_common_root(all_files)
    if not root_dir:
        return []

    root_path = Path(root_dir).resolve()
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # Collect top-level source directories
    module_dirs: set[str] = set()
    for fp in all_files:
        rel = _normalize_relative(fp, root_path, root_path)
        if not rel:
            continue
        parts = rel.split("/")
        if len(parts) >= 2 and not any(p.startswith(".") or p in _IGNORE_PARTS for p in parts):
            module_dirs.add(parts[0])

    written: list[str] = []

    def _write_doc(rel_dir: str | None, title: str, subdir: str | None) -> str:
        doc_dir = base_dir / rel_dir if rel_dir else base_dir
        doc_dir.mkdir(parents=True, exist_ok=True)
        doc_path = doc_dir / "structure.md"
        doc_path_zh = doc_dir / "structure_zh.md"
        doc_path_en = doc_dir / "structure_en.md"

        mermaid = build_mermaid_diagram(all_files, subdir=subdir)
        mermaid_block = ""
        if mermaid and not mermaid.startswith("(no "):
            mermaid_block = f"## Structure Diagram\n\n{mermaid}\n"
        ft = build_file_tree(all_files, subdir=subdir)
        file_tree_block = f"## File Tree\n\n{ft}\n"

        module_nav = ""
        if rel_dir is None:
            children = sorted(module_dirs)
            if children:
                nav_lines = ["## Modules\n"]
                for child in children:
                    nav_lines.append(f"- [{child}]({child}/structure.md)")
                nav_lines.append("")
                module_nav = "\n".join(nav_lines)

        back_nav = f"[⬆ 返回顶层结构](../structure.md)\n" if rel_dir and "/" not in rel_dir else ""

        zh_title = {"Project Structure Overview": "项目结构总览"}.get(title, title)
        zh_content = f"# {zh_title}\n\n{back_nav}\n{mermaid_block}{file_tree_block}{module_nav}"
        doc_path.write_text(zh_content, encoding="utf-8")
        doc_path_zh.write_text(zh_content, encoding="utf-8")

        en_content = f"# {title}\n\n[⬆ Back to top structure](../structure_en.md)\n\n{mermaid_block}{file_tree_block}{module_nav}"
        doc_path_en.write_text(en_content, encoding="utf-8")

        return str(doc_path)

    written.append(_write_doc(None, "Project Structure Overview", None))
    for mod in sorted(module_dirs):
        if not (root_path / mod).is_dir():
            continue
        mod_name = mod.replace("_", " ").replace("-", " ").title()
        written.append(_write_doc(mod, f"Module: {mod_name}", mod))

    return written


def generate_structure_json(all_files: list[str], output_dir: str) -> dict:
    """Build structured JSON data for the React visualization page."""
    if not all_files:
        return {"modules": [], "files": [], "imports": []}

    root_dir = _find_common_root(all_files)
    if not root_dir:
        return {"modules": [], "files": [], "imports": []}

    root_path = Path(root_dir).resolve()
    ignore_parts = _IGNORE_PARTS

    modules: list[dict] = []
    file_list: list[dict] = []
    imports: list[dict] = []
    module_file_map: dict[str, list[str]] = {}
    root_files: list[str] = []

    for fp in all_files:
        try:
            p = Path(fp).resolve()
            rel = p.relative_to(root_path).as_posix()
        except ValueError:
            continue
        if any(part in ignore_parts or part.startswith(".") for part in rel.split("/")):
            continue

        parts = rel.split("/")
        if len(parts) >= 2:
            module_file_map.setdefault(parts[0], []).append(fp)
        else:
            root_files.append(fp)

        symbols = extract_symbols(fp) or []
        file_list.append({
            "path": rel,
            "name": parts[-1],
            "module": parts[0] if len(parts) >= 2 else "",
            "symbols": [{"name": s[0], "children": s[1]} for s in symbols],
        })

    for mod_name, mod_files in sorted(module_file_map.items()):
        if not (root_path / mod_name).is_dir():
            continue
        sub_files = []
        for fp in mod_files:
            try:
                sub_files.append(Path(fp).resolve().relative_to(root_path).as_posix())
            except ValueError:
                continue
        modules.append({
            "name": mod_name,
            "label": mod_name.replace("_", " ").replace("-", " ").title(),
            "path": str(root_path / mod_name),
            "files": sorted(sub_files),
            "file_count": len(sub_files),
        })

    if root_files:
        modules.insert(0, {
            "name": ".",
            "label": "Root",
            "path": str(root_path),
            "files": sorted(
                Path(fp).resolve().relative_to(root_path).as_posix()
                for fp in root_files
            ),
            "file_count": len(root_files),
        })

    # Parse imports for dependency edges
    for fp in all_files:
        if not fp.endswith(".py"):
            continue
        try:
            with open(fp) as fh:
                tree = ast.parse(fh.read())
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        try:
            fp_rel = Path(fp).resolve().relative_to(root_path).as_posix()
        except ValueError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name.split(".")[0]
                    if target and not target.startswith("_"):
                        imports.append({"from": fp_rel, "target": target})
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    target = node.module.split(".")[0]
                    if target and not target.startswith("_"):
                        imports.append({"from": fp_rel, "target": target})

    return {"modules": modules, "files": file_list, "imports": imports}
