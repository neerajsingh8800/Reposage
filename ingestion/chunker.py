"""
AST-aware code chunker for RepoSage.

Instead of splitting files by a fixed number of tokens/lines (which cuts
functions in half and destroys meaning), we parse each file into an AST
using tree-sitter and extract whole semantic units: functions, methods,
and classes. Each chunk carries metadata that later powers hybrid
retrieval and the dependency graph.
"""

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjs.language())
TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())


@dataclass
class CodeChunk:
    file_path: str
    chunk_type: str          # "function" | "class" | "method" | "script"
    name: str                 # function/class/module name
    parent_class: str | None  # set if this is a method
    start_line: int
    end_line: int
    code: str
    docstring: str | None = None
    calls: list[str] = field(default_factory=list)  # function names called inside this chunk


def _get_docstring(node, source: bytes) -> str | None:
    body = node.child_by_field_name("body")
    if body is None:
        return None
    for child in body.children:
        if child.type == "expression_statement" and child.children:
            expr = child.children[0]
            if expr.type == "string":
                text = source[expr.start_byte:expr.end_byte].decode("utf-8")
                return text.strip("'\" \n")
    return None


def _get_calls(node, source: bytes) -> list[str]:
    calls = []

    def walk(n):
        if n.type == "call":
            func_node = n.child_by_field_name("function")
            if func_node is not None:
                name = source[func_node.start_byte:func_node.end_byte].decode("utf-8").strip()
                if name:
                    calls.append(name)
        for child in n.children:
            walk(child)

    walk(node)
    return calls


def chunk_text_file(
    file_path: str,
    max_chunk_lines: int = 50,
    overlap_lines: int = 10,
) -> list[CodeChunk]:
    """Create chunks for text-based source/doc files (.md, .txt, .json, .yaml, etc.).
    
    Small files (<= max_chunk_lines) become a single chunk. Larger files are split
    using a sliding window with overlap to preserve semantic context.
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    stem = Path(file_path).stem or "doc"
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if total_lines <= max_chunk_lines:
        return [CodeChunk(
            file_path=file_path,
            chunk_type="doc",
            name=stem,
            parent_class=None,
            start_line=1,
            end_line=max(1, total_lines),
            code=text,
            docstring=None,
            calls=[],
        )]

    step = max(1, max_chunk_lines - overlap_lines)
    chunks: list[CodeChunk] = []
    part = 1

    for start_idx in range(0, total_lines, step):
        end_idx = min(start_idx + max_chunk_lines, total_lines)
        chunk_text = "".join(lines[start_idx:end_idx])
        chunks.append(CodeChunk(
            file_path=file_path,
            chunk_type="doc",
            name=f"{stem}_part_{part}",
            parent_class=None,
            start_line=start_idx + 1,
            end_line=end_idx,
            code=chunk_text,
            docstring=None,
            calls=[],
        ))
        part += 1
        if end_idx >= total_lines:
            break

    return chunks


def chunk_notebook_file(file_path: str) -> list[CodeChunk]:
    """Parse a Jupyter notebook (.ipynb) JSON file into cell-level and function-level chunks.
    
    Extracts code cells (with AST call and symbol resolution), functions/classes defined inside
    notebook cells, and markdown cells in order, preserving sequence and metadata.
    Falls back to python chunking if the file is not valid JSON.
    """
    import json

    try:
        raw_text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw_text)
    except Exception:
        # Fallback to python/text chunking if notebook is not standard JSON
        try:
            return chunk_python_file(file_path)
        except Exception:
            return chunk_text_file(file_path)

    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        try:
            return chunk_python_file(file_path)
        except Exception:
            return chunk_text_file(file_path)

    cells = data.get("cells", [])
    stem = Path(file_path).stem or "notebook"
    chunks: list[CodeChunk] = []
    parser = Parser(PY_LANGUAGE)
    current_line = 1

    for idx, cell in enumerate(cells):
        cell_type = cell.get("cell_type", "")
        source_raw = cell.get("source", "")
        if isinstance(source_raw, list):
            source = "".join(source_raw)
        elif isinstance(source_raw, str):
            source = source_raw
        else:
            source = str(source_raw)

        if not source.strip():
            continue

        line_count = max(1, len(source.splitlines()))
        cell_start_line = current_line
        cell_end_line = current_line + line_count - 1

        if cell_type == "code":
            calls: list[str] = []
            try:
                src_bytes = source.encode("utf-8")
                tree = parser.parse(src_bytes)
                calls = _get_calls(tree.root_node, src_bytes)

                # Extract any inner functions or classes defined in this notebook cell
                def visit_cell(node, parent_cls: str | None = None):
                    if node.type == "function_definition":
                        name_node = node.child_by_field_name("name")
                        if name_node:
                            f_name = src_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8")
                            f_start = cell_start_line + node.start_point[0]
                            f_end = cell_start_line + node.end_point[0]
                            chunks.append(CodeChunk(
                                file_path=file_path,
                                chunk_type="method" if parent_cls else "function",
                                name=f_name,
                                parent_class=parent_cls,
                                start_line=f_start,
                                end_line=f_end,
                                code=src_bytes[node.start_byte:node.end_byte].decode("utf-8"),
                                docstring=_get_docstring(node, src_bytes),
                                calls=_get_calls(node, src_bytes),
                            ))
                    elif node.type == "class_definition":
                        name_node = node.child_by_field_name("name")
                        if name_node:
                            c_name = src_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8")
                            c_start = cell_start_line + node.start_point[0]
                            c_end = cell_start_line + node.end_point[0]
                            chunks.append(CodeChunk(
                                file_path=file_path,
                                chunk_type="class",
                                name=c_name,
                                parent_class=None,
                                start_line=c_start,
                                end_line=c_end,
                                code=src_bytes[node.start_byte:node.end_byte].decode("utf-8"),
                                docstring=_get_docstring(node, src_bytes),
                                calls=[],
                            ))
                            for c in node.children:
                                visit_cell(c, parent_cls=c_name)
                    else:
                        for c in node.children:
                            visit_cell(c, parent_cls=parent_cls)

                visit_cell(tree.root_node)
            except Exception:
                calls = []

            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="notebook_code",
                name=f"{stem}_cell_{idx + 1}",
                parent_class=None,
                start_line=cell_start_line,
                end_line=cell_end_line,
                code=source,
                docstring=None,
                calls=calls,
            ))
        elif cell_type == "markdown":
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="notebook_markdown",
                name=f"{stem}_cell_{idx + 1}_md",
                parent_class=None,
                start_line=cell_start_line,
                end_line=cell_end_line,
                code=source,
                docstring=None,
                calls=[],
            ))
        else:
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="doc",
                name=f"{stem}_cell_{idx + 1}",
                parent_class=None,
                start_line=cell_start_line,
                end_line=cell_end_line,
                code=source,
                docstring=None,
                calls=[],
            ))

        current_line += line_count

    return chunks


def chunk_python_file(
    file_path: str,
    max_procedural_lines: int = 50,
    overlap_lines: int = 10,
) -> list[CodeChunk]:
    """Parse a single Python file into function/class/method-level chunks and module-level chunks.

    Extracts all functions and classes, and also preserves module-level script chunks
    so global imports, ML pipelines, constants, and procedural code are indexed.
    """
    try:
        source = Path(file_path).read_bytes()
        parser = Parser(PY_LANGUAGE)
        tree = parser.parse(source)
        root = tree.root_node
    except Exception:
        return chunk_text_file(file_path, max_chunk_lines=max_procedural_lines, overlap_lines=overlap_lines)

    chunks: list[CodeChunk] = []
    symbol_line_ranges: list[tuple[int, int]] = []

    def visit(node, parent_class: str | None = None):
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            class_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else "Class"
            start_l = node.start_point[0] + 1
            end_l = node.end_point[0] + 1
            symbol_line_ranges.append((start_l, end_l))

            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="class",
                name=class_name,
                parent_class=None,
                start_line=start_l,
                end_line=end_l,
                code=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                docstring=_get_docstring(node, source),
                calls=[],
            ))
            for child in node.children:
                visit(child, parent_class=class_name)

        elif node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            func_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else "func"
            start_l = node.start_point[0] + 1
            end_l = node.end_point[0] + 1
            symbol_line_ranges.append((start_l, end_l))

            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="method" if parent_class else "function",
                name=func_name,
                parent_class=parent_class,
                start_line=start_l,
                end_line=end_l,
                code=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                docstring=_get_docstring(node, source),
                calls=_get_calls(node, source),
            ))
        else:
            for child in node.children:
                visit(child, parent_class=parent_class)

    visit(root)

    text = source.decode("utf-8", errors="replace")
    module_name = Path(file_path).stem or "module"
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    # Check if there is substantial module-level code outside of functions/classes
    # or if the entire file was purely procedural.
    if not chunks:
        # File has no functions/classes: chunk entire script
        if total_lines <= max_procedural_lines:
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="script",
                name=module_name,
                parent_class=None,
                start_line=1,
                end_line=max(1, total_lines),
                code=text,
                docstring=None,
                calls=_get_calls(root, source),
            ))
        else:
            step = max(1, max_procedural_lines - overlap_lines)
            part = 1
            for start_idx in range(0, total_lines, step):
                end_idx = min(start_idx + max_procedural_lines, total_lines)
                chunk_text = "".join(lines[start_idx:end_idx])
                chunk_calls: list[str] = []
                try:
                    chunk_bytes = chunk_text.encode("utf-8")
                    chunk_tree = parser.parse(chunk_bytes)
                    chunk_calls = _get_calls(chunk_tree.root_node, chunk_bytes)
                except Exception:
                    chunk_calls = []

                chunks.append(CodeChunk(
                    file_path=file_path,
                    chunk_type="script",
                    name=f"{module_name}_part_{part}",
                    parent_class=None,
                    start_line=start_idx + 1,
                    end_line=end_idx,
                    code=chunk_text,
                    docstring=None,
                    calls=chunk_calls,
                ))
                part += 1
                if end_idx >= total_lines:
                    break
    else:
        # File has functions/classes. Also capture top-level script / module code (e.g. imports, model setup, pipelines)
        # so global logic is never lost during retrieval.
        if total_lines <= max_procedural_lines:
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="script",
                name=f"{module_name}_module",
                parent_class=None,
                start_line=1,
                end_line=max(1, total_lines),
                code=text,
                docstring=None,
                calls=_get_calls(root, source),
            ))
        else:
            # Add top-level script chunks
            step = max(1, max_procedural_lines - overlap_lines)
            part = 1
            for start_idx in range(0, total_lines, step):
                end_idx = min(start_idx + max_procedural_lines, total_lines)
                chunk_text = "".join(lines[start_idx:end_idx])
                chunk_calls: list[str] = []
                try:
                    chunk_bytes = chunk_text.encode("utf-8")
                    chunk_tree = parser.parse(chunk_bytes)
                    chunk_calls = _get_calls(chunk_tree.root_node, chunk_bytes)
                except Exception:
                    chunk_calls = []

                chunks.append(CodeChunk(
                    file_path=file_path,
                    chunk_type="script",
                    name=f"{module_name}_module_part_{part}",
                    parent_class=None,
                    start_line=start_idx + 1,
                    end_line=end_idx,
                    code=chunk_text,
                    docstring=None,
                    calls=chunk_calls,
                ))
                part += 1
                if end_idx >= total_lines:
                    break

    return chunks


def _get_js_ts_docstring(node, source: bytes) -> str | None:
    """Extract JSDoc / block comment / line comments preceding a JS/TS node."""
    target_node = node.parent if node.parent and node.parent.type == "export_statement" else node
    curr = target_node.prev_sibling
    while curr and curr.type in ("comment", "\n", " "):
        if curr.type == "comment":
            text = source[curr.start_byte:curr.end_byte].decode("utf-8", errors="replace").strip()
            if text.startswith("/**") or text.startswith("/*"):
                lines = [l.strip("/* \t") for l in text.splitlines()]
                clean = " ".join([l for l in lines if l]).strip()
                if clean:
                    return clean
            elif text.startswith("//"):
                clean = text.lstrip("/ \t")
                if clean:
                    return clean
        curr = curr.prev_sibling
    return None


def _get_js_ts_calls(node, source: bytes) -> list[str]:
    """Extract call expressions, new expressions, and JSX component references from a JS/TS node."""
    calls: list[str] = []

    def walk(n):
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None:
                text = source[fn.start_byte:fn.end_byte].decode("utf-8", errors="replace").strip()
                if text:
                    calls.append(text)
        elif n.type == "new_expression":
            constructor = n.child_by_field_name("constructor")
            if constructor is not None:
                text = source[constructor.start_byte:constructor.end_byte].decode("utf-8", errors="replace").strip()
                if text:
                    calls.append(text)
        elif n.type in ("jsx_element", "jsx_self_closing_element"):
            name_node = None
            if n.type == "jsx_element":
                opening = n.child_by_field_name("open_tag") or (n.children[0] if n.children else None)
                if opening:
                    name_node = opening.child_by_field_name("name") or (opening.children[1] if len(opening.children) > 1 else None)
            else:
                name_node = n.child_by_field_name("name") or (n.children[1] if len(n.children) > 1 else None)

            if name_node is not None:
                tag = source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace").strip()
                if tag and (tag[0].isupper() or "." in tag):
                    calls.append(tag)

        for c in n.children:
            walk(c)

    walk(node)
    return calls


def _get_js_ts_parser(file_path: str) -> Parser:
    ext = Path(file_path).suffix.lower()
    if ext in (".ts", ".mts", ".cts"):
        return Parser(TS_LANGUAGE)
    elif ext in (".tsx", ".jsx"):
        return Parser(TSX_LANGUAGE)
    else:
        return Parser(JS_LANGUAGE)


def chunk_js_ts_file(
    file_path: str,
    max_procedural_lines: int = 50,
    overlap_lines: int = 10,
) -> list[CodeChunk]:
    """Parse a JavaScript or TypeScript file (.js, .jsx, .ts, .tsx) into semantic AST chunks.

    Extracts function declarations, arrow functions/expressions, classes, methods,
    constructors, TypeScript interfaces/types/enums, and JSX components.
    Falls back to sliding-window chunks if no functions/classes are declared.
    """
    try:
        source = Path(file_path).read_bytes()
        parser = _get_js_ts_parser(file_path)
        tree = parser.parse(source)
    except Exception:
        # Graceful fallback to text chunking if AST parsing fails
        return chunk_text_file(file_path, max_chunk_lines=max_procedural_lines, overlap_lines=overlap_lines)

    root = tree.root_node
    stem = Path(file_path).stem or "module"
    chunks: list[CodeChunk] = []

    def visit(node, parent_class: str | None = None):
        nonlocal chunks
        ntype = node.type

        # Unwrap export statements
        if ntype == "export_statement":
            for child in node.children:
                if child.type in (
                    "function_declaration", "generator_function_declaration",
                    "class_declaration", "class", "lexical_declaration",
                    "variable_declaration", "interface_declaration",
                    "type_alias_declaration", "enum_declaration"
                ):
                    visit(child, parent_class=parent_class)
            return

        if ntype in ("class_declaration", "class"):
            name_node = node.child_by_field_name("name")
            class_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else f"{stem}Class"

            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="class",
                name=class_name,
                parent_class=parent_class,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                code=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                docstring=_get_js_ts_docstring(node, source),
                calls=[],
            ))

            body = node.child_by_field_name("body")
            if body:
                for member in body.children:
                    if member.type == "method_definition":
                        m_name_node = member.child_by_field_name("name")
                        if m_name_node:
                            m_name = source[m_name_node.start_byte:m_name_node.end_byte].decode("utf-8")
                            chunks.append(CodeChunk(
                                file_path=file_path,
                                chunk_type="method",
                                name=m_name,
                                parent_class=class_name,
                                start_line=member.start_point[0] + 1,
                                end_line=member.end_point[0] + 1,
                                code=source[member.start_byte:member.end_byte].decode("utf-8", errors="replace"),
                                docstring=_get_js_ts_docstring(member, source),
                                calls=_get_js_ts_calls(member, source),
                            ))
                    elif member.type in ("field_definition", "public_field_definition", "property_definition"):
                        prop_name_node = member.child_by_field_name("property") or member.child_by_field_name("name")
                        val_node = member.child_by_field_name("value")
                        if prop_name_node and val_node and val_node.type in ("arrow_function", "function_expression", "function"):
                            prop_name = source[prop_name_node.start_byte:prop_name_node.end_byte].decode("utf-8")
                            chunks.append(CodeChunk(
                                file_path=file_path,
                                chunk_type="method",
                                name=prop_name,
                                parent_class=class_name,
                                start_line=member.start_point[0] + 1,
                                end_line=member.end_point[0] + 1,
                                code=source[member.start_byte:member.end_byte].decode("utf-8", errors="replace"),
                                docstring=_get_js_ts_docstring(member, source),
                                calls=_get_js_ts_calls(member, source),
                            ))
            return

        if ntype in ("function_declaration", "generator_function_declaration"):
            name_node = node.child_by_field_name("name")
            func_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else f"{stem}_func"
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="method" if parent_class else "function",
                name=func_name,
                parent_class=parent_class,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                code=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                docstring=_get_js_ts_docstring(node, source),
                calls=_get_js_ts_calls(node, source),
            ))
            return

        if ntype in ("lexical_declaration", "variable_declaration"):
            for declarator in node.children:
                if declarator.type == "variable_declarator":
                    name_node = declarator.child_by_field_name("name")
                    val_node = declarator.child_by_field_name("value")
                    if name_node and val_node and val_node.type in ("arrow_function", "function_expression", "function"):
                        var_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                        chunks.append(CodeChunk(
                            file_path=file_path,
                            chunk_type="method" if parent_class else "function",
                            name=var_name,
                            parent_class=parent_class,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            code=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                            docstring=_get_js_ts_docstring(node, source),
                            calls=_get_js_ts_calls(declarator, source),
                        ))
            return

        if ntype in ("interface_declaration", "type_alias_declaration", "enum_declaration"):
            name_node = node.child_by_field_name("name")
            sym_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else f"{stem}_{ntype}"
            chunk_t = "class" if ntype in ("interface_declaration", "enum_declaration") else "type"
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type=chunk_t,
                name=sym_name,
                parent_class=parent_class,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                code=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                docstring=_get_js_ts_docstring(node, source),
                calls=[],
            ))
            return

        for child in node.children:
            visit(child, parent_class=parent_class)

    visit(root)

    text = source.decode("utf-8", errors="replace")
    module_name = stem
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if not chunks:
        if total_lines <= max_procedural_lines:
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="script",
                name=module_name,
                parent_class=None,
                start_line=1,
                end_line=max(1, total_lines),
                code=text,
                docstring=None,
                calls=_get_js_ts_calls(root, source),
            ))
        else:
            step = max(1, max_procedural_lines - overlap_lines)
            part = 1
            for start_idx in range(0, total_lines, step):
                end_idx = min(start_idx + max_procedural_lines, total_lines)
                chunk_text = "".join(lines[start_idx:end_idx])
                chunk_calls: list[str] = []
                try:
                    chunk_bytes = chunk_text.encode("utf-8")
                    parser = _get_js_ts_parser(file_path)
                    chunk_tree = parser.parse(chunk_bytes)
                    chunk_calls = _get_js_ts_calls(chunk_tree.root_node, chunk_bytes)
                except Exception:
                    chunk_calls = []

                chunks.append(CodeChunk(
                    file_path=file_path,
                    chunk_type="script",
                    name=f"{module_name}_part_{part}",
                    parent_class=None,
                    start_line=start_idx + 1,
                    end_line=end_idx,
                    code=chunk_text,
                    docstring=None,
                    calls=chunk_calls,
                ))
                part += 1
                if end_idx >= total_lines:
                    break
    else:
        if total_lines <= max_procedural_lines:
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="script",
                name=f"{module_name}_module",
                parent_class=None,
                start_line=1,
                end_line=max(1, total_lines),
                code=text,
                docstring=None,
                calls=_get_js_ts_calls(root, source),
            ))
        else:
            step = max(1, max_procedural_lines - overlap_lines)
            part = 1
            for start_idx in range(0, total_lines, step):
                end_idx = min(start_idx + max_procedural_lines, total_lines)
                chunk_text = "".join(lines[start_idx:end_idx])
                chunk_calls: list[str] = []
                try:
                    chunk_bytes = chunk_text.encode("utf-8")
                    parser = _get_js_ts_parser(file_path)
                    chunk_tree = parser.parse(chunk_bytes)
                    chunk_calls = _get_js_ts_calls(chunk_tree.root_node, chunk_bytes)
                except Exception:
                    chunk_calls = []

                chunks.append(CodeChunk(
                    file_path=file_path,
                    chunk_type="script",
                    name=f"{module_name}_module_part_{part}",
                    parent_class=None,
                    start_line=start_idx + 1,
                    end_line=end_idx,
                    code=chunk_text,
                    docstring=None,
                    calls=chunk_calls,
                ))
                part += 1
                if end_idx >= total_lines:
                    break

    return chunks


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "sample_repo/payments.py"
    ext = Path(target).suffix.lower()
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        result = chunk_js_ts_file(target)
    else:
        result = chunk_python_file(target)

    print(f"\nParsed {len(result)} chunks from {target}\n" + "=" * 60)
    for c in result:
        print(f"\n[{c.chunk_type.upper()}] {c.name}"
              + (f"  (method of {c.parent_class})" if c.parent_class else ""))
        print(f"  lines {c.start_line}-{c.end_line}")

