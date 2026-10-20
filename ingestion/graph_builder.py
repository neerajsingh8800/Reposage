import posixpath
import re
from pathlib import Path
from typing import Any
import networkx as nx  # type: ignore
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from ingestion.chunker import CodeChunk

PY_LANGUAGE = Language(tspython.language())
_py_parser = Parser(PY_LANGUAGE)

JS_LANGUAGE = Language(tsjs.language())
TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())


def _get_js_ts_parser(file_path: str) -> Parser:
    ext = Path(file_path).suffix.lower()
    if ext in (".ts", ".mts", ".cts"):
        return Parser(TS_LANGUAGE)
    elif ext in (".tsx", ".jsx"):
        return Parser(TSX_LANGUAGE)
    else:
        return Parser(JS_LANGUAGE)


def normalize_repo_rel_path(path_str: str, repo_path: str | Path | None = None) -> str:
    """Normalize file path to forward-slash repository-relative path."""
    if not path_str:
        return ""
    p = Path(path_str)
    if repo_path:
        try:
            return p.resolve().relative_to(Path(repo_path).resolve()).as_posix()
        except Exception:
            pass
    posix_path = p.as_posix()
    if "/repo_storage/" in posix_path:
        parts = posix_path.split("/repo_storage/", 1)[1].split("/", 1)
        if len(parts) > 1:
            return parts[1]
    return posix_path


def _qualified_name(chunk: CodeChunk, repo_path: str | Path | None = None) -> str:
    rel_path = normalize_repo_rel_path(chunk.file_path, repo_path)
    base_name = f"{chunk.parent_class}.{chunk.name}" if chunk.parent_class else chunk.name
    return f"{rel_path}::{base_name}"


def _extract_py_imports(file_path: str) -> dict[str, tuple[str, str | None]]:
    """Extract AST imports from a Python file.

    Returns: { alias_or_symbol_name: (module_name, original_symbol_name) }
    """
    try:
        source = Path(file_path).read_bytes()
        tree = _py_parser.parse(source)
    except Exception:
        return {}

    imports: dict[str, tuple[str, str | None]] = {}
    for child in tree.root_node.children:
        if child.type == "import_statement":
            for n in child.children:
                if n.type == "dotted_name":
                    name = source[n.start_byte:n.end_byte].decode("utf-8").strip()
                    imports[name.split(".")[-1]] = (name, None)
                    imports[name] = (name, None)
                elif n.type == "aliased_import":
                    orig = n.child_by_field_name("name")
                    alias = n.child_by_field_name("alias")
                    if orig and alias:
                        orig_str = source[orig.start_byte:orig.end_byte].decode("utf-8").strip()
                        alias_str = source[alias.start_byte:alias.end_byte].decode("utf-8").strip()
                        imports[alias_str] = (orig_str, None)
        elif child.type == "import_from_statement":
            mod_str = ""
            past_import = False
            for sub in child.children:
                if sub.type == "import":
                    past_import = True
                    continue
                if not past_import:
                    if sub.type in ("dotted_name", "relative_import"):
                        mod_str = source[sub.start_byte:sub.end_byte].decode("utf-8").strip()
                else:
                    if sub.type == "dotted_name":
                        sym = source[sub.start_byte:sub.end_byte].decode("utf-8").strip()
                        imports[sym] = (mod_str, sym)
                    elif sub.type == "aliased_import":
                        orig = sub.child_by_field_name("name")
                        alias = sub.child_by_field_name("alias")
                        if orig and alias:
                            orig_str = source[orig.start_byte:orig.end_byte].decode("utf-8").strip()
                            alias_str = source[alias.start_byte:alias.end_byte].decode("utf-8").strip()
                            imports[alias_str] = (mod_str, orig_str)
    return imports


def _extract_js_ts_imports(file_path: str) -> dict[str, tuple[str, str | None]]:
    """Extract AST imports from a JavaScript or TypeScript file (.js, .jsx, .ts, .tsx).

    Returns: { alias_or_symbol_name: (module_path, original_symbol_name) }
    """
    try:
        source = Path(file_path).read_bytes()
        parser = _get_js_ts_parser(file_path)
        tree = parser.parse(source)
    except Exception:
        return {}

    imports: dict[str, tuple[str, str | None]] = {}

    def clean_str(s: str) -> str:
        return s.strip("'\"` \n\r\t")

    for child in tree.root_node.children:
        # ES Module import
        if child.type == "import_statement":
            source_node = child.child_by_field_name("source")
            if not source_node:
                for c in child.children:
                    if c.type == "string":
                        source_node = c
                        break
            if not source_node:
                continue

            mod_str = clean_str(source[source_node.start_byte:source_node.end_byte].decode("utf-8", errors="replace"))

            for clause in child.children:
                if clause.type == "import_clause":
                    for sub in clause.children:
                        if sub.type == "identifier":
                            sym = source[sub.start_byte:sub.end_byte].decode("utf-8")
                            imports[sym] = (mod_str, None)
                        elif sub.type == "namespace_import":
                            id_node = sub.child_by_field_name("name") or (sub.children[-1] if sub.children else None)
                            if id_node:
                                sym = source[id_node.start_byte:id_node.end_byte].decode("utf-8")
                                imports[sym] = (mod_str, "*")
                        elif sub.type == "named_imports":
                            for spec in sub.children:
                                if spec.type == "import_specifier":
                                    name_node = spec.child_by_field_name("name")
                                    alias_node = spec.child_by_field_name("alias")
                                    if name_node:
                                        orig_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                                        if alias_node:
                                            alias_name = source[alias_node.start_byte:alias_node.end_byte].decode("utf-8")
                                            imports[alias_name] = (mod_str, orig_name)
                                        else:
                                            imports[orig_name] = (mod_str, orig_name)

        # CommonJS require
        elif child.type in ("lexical_declaration", "variable_declaration"):
            for decl in child.children:
                if decl.type == "variable_declarator":
                    val = decl.child_by_field_name("value")
                    name_node = decl.child_by_field_name("name")
                    if val and val.type == "call_expression":
                        fn_node = val.child_by_field_name("function")
                        if fn_node and source[fn_node.start_byte:fn_node.end_byte].decode("utf-8") == "require":
                            args = val.child_by_field_name("arguments")
                            if args and len(args.children) >= 2:
                                arg0 = args.children[1]
                                if arg0.type == "string":
                                    mod_str = clean_str(source[arg0.start_byte:arg0.end_byte].decode("utf-8"))
                                    if name_node:
                                        if name_node.type == "identifier":
                                            sym = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                                            imports[sym] = (mod_str, "*")
                                        elif name_node.type == "object_pattern":
                                            for prop in name_node.children:
                                                if prop.type in ("shorthand_property_identifier_pattern", "identifier"):
                                                    sym = source[prop.start_byte:prop.end_byte].decode("utf-8")
                                                    imports[sym] = (mod_str, sym)
                                                elif prop.type == "pair_pattern":
                                                    k = prop.child_by_field_name("key")
                                                    v = prop.child_by_field_name("value")
                                                    if k and v:
                                                        k_str = source[k.start_byte:k.end_byte].decode("utf-8")
                                                        v_str = source[v.start_byte:v.end_byte].decode("utf-8")
                                                        imports[v_str] = (mod_str, k_str)

    return imports


def _resolve_relative_module(
    mod_str: str,
    rel_file: str,
    known_files: set[str],
    module_to_file: dict[str, str]
) -> str | None:
    """Resolve a module import path to a concrete repository-local file."""
    if mod_str in module_to_file:
        return module_to_file[mod_str]
    simple_mod = mod_str.split("/")[-1].split(".")[-1]
    if simple_mod in module_to_file:
        return module_to_file[simple_mod]

    cur_dir = posixpath.dirname(rel_file.replace("\\", "/"))
    clean_mod = mod_str.replace("\\", "/")

    # Candidate paths relative to the current file's directory
    joined = posixpath.normpath(posixpath.join(cur_dir, clean_mod)).replace("\\", "/")
    if joined.startswith("./"):
        joined = joined[2:]

    candidates = [
        joined,
        f"{joined}.ts", f"{joined}.tsx", f"{joined}.js", f"{joined}.jsx",
        f"{joined}.mjs", f"{joined}.cjs", f"{joined}.mts", f"{joined}.cts",
        f"{joined}.py",
        f"{joined}/index.ts", f"{joined}/index.tsx", f"{joined}/index.js", f"{joined}/index.jsx"
    ]
    for cand in candidates:
        if cand in known_files:
            return cand
        if cand in module_to_file:
            return module_to_file[cand]

    # Candidate paths relative to repository root
    norm_mod = posixpath.normpath(clean_mod).replace("\\", "/").lstrip("./")
    candidates_root = [
        norm_mod,
        f"{norm_mod}.ts", f"{norm_mod}.tsx", f"{norm_mod}.js", f"{norm_mod}.jsx",
        f"{norm_mod}.mjs", f"{norm_mod}.cjs", f"{norm_mod}.mts", f"{norm_mod}.cts",
        f"{norm_mod}.py",
        f"{norm_mod}/index.ts", f"{norm_mod}/index.tsx", f"{norm_mod}/index.js", f"{norm_mod}/index.jsx"
    ]
    for cand in candidates_root:
        if cand in known_files:
            return cand
        if cand in module_to_file:
            return module_to_file[cand]

    return None


def build_graph(chunks: list[CodeChunk], repo_path: str | Path | None = None) -> nx.DiGraph:
    """Build a directed dependency graph from code chunks (Python, JavaScript, TypeScript)."""
    graph = nx.DiGraph()

    file_to_symbols: dict[str, dict[str, list[str]]] = {}
    global_symbols: dict[str, list[str]] = {}
    module_to_file: dict[str, str] = {}
    file_imports: dict[str, dict[str, tuple[str, str | None]]] = {}
    known_files: set[str] = set()

    for chunk in chunks:
        qname = _qualified_name(chunk, repo_path)
        rel_file = normalize_repo_rel_path(chunk.file_path, repo_path)
        known_files.add(rel_file)

        graph.add_node(
            qname,
            id=qname,
            file_path=rel_file,
            name=chunk.name,
            chunk_type=chunk.chunk_type,
            parent_class=chunk.parent_class,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
        )

        file_to_symbols.setdefault(rel_file, {}).setdefault(chunk.name, []).append(qname)
        if chunk.parent_class:
            file_to_symbols[rel_file].setdefault(f"{chunk.parent_class}.{chunk.name}", []).append(qname)

        global_symbols.setdefault(chunk.name, []).append(qname)
        if chunk.parent_class:
            global_symbols.setdefault(f"{chunk.parent_class}.{chunk.name}", []).append(qname)

        stem = Path(rel_file).stem
        module_to_file[stem] = rel_file
        module_to_file[rel_file] = rel_file
        dot_mod = rel_file.replace("/", ".").replace("\\", ".")
        for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"):
            if dot_mod.endswith(ext):
                dot_mod = dot_mod[:-len(ext)]
                break
        module_to_file[dot_mod] = rel_file

        if rel_file not in file_imports:
            ext = Path(chunk.file_path).suffix.lower()
            if ext == ".py":
                file_imports[rel_file] = _extract_py_imports(chunk.file_path)
            elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"):
                file_imports[rel_file] = _extract_js_ts_imports(chunk.file_path)

    for chunk in chunks:
        caller = _qualified_name(chunk, repo_path)
        rel_file = normalize_repo_rel_path(chunk.file_path, repo_path)
        imports = file_imports.get(rel_file, {})

        for call_expr in chunk.calls:
            resolved_targets: list[str] = []

            # 1. Class method call: self.method(...), cls.method(...), or this.method(...)
            if (call_expr.startswith("self.") or call_expr.startswith("cls.") or call_expr.startswith("this.")) and chunk.parent_class:
                method_name = call_expr.split(".", 1)[1]
                target_qname = f"{rel_file}::{chunk.parent_class}.{method_name}"
                if target_qname in graph:
                    resolved_targets.append(target_qname)

            # 2. Module/object attribute call: module.func(...) or obj.method(...)
            if not resolved_targets and "." in call_expr:
                prefix, member = call_expr.rsplit(".", 1)
                mod_name = prefix.split(".")[-1]
                mod_info = imports.get(mod_name) or imports.get(prefix)
                if mod_info:
                    mod_str, orig_sym = mod_info
                    target_file = _resolve_relative_module(mod_str, rel_file, known_files, module_to_file)
                    if target_file and target_file in file_to_symbols:
                        matched = file_to_symbols[target_file].get(member, [])
                        if not matched and orig_sym and orig_sym != "*":
                            matched = file_to_symbols[target_file].get(f"{orig_sym}.{member}", [])
                        if not matched:
                            matched = file_to_symbols[target_file].get(f"{mod_name}.{member}", [])
                        resolved_targets.extend(matched)
                else:
                    target_file = _resolve_relative_module(prefix, rel_file, known_files, module_to_file)
                    if target_file and target_file in file_to_symbols:
                        matched = file_to_symbols[target_file].get(member, [])
                        resolved_targets.extend(matched)

            # 3. Direct imported function / class / component
            simple_name = call_expr.split(".")[-1]
            if not resolved_targets and simple_name in imports:
                mod_str, orig_sym = imports[simple_name]
                sym_to_look = orig_sym if (orig_sym and orig_sym != "*") else simple_name
                target_file = _resolve_relative_module(mod_str, rel_file, known_files, module_to_file)
                if target_file and target_file in file_to_symbols:
                    matched = file_to_symbols[target_file].get(sym_to_look, [])
                    if not matched:
                        matched = file_to_symbols[target_file].get(simple_name, [])
                    resolved_targets.extend(matched)

            # 4. Same-file function or method definition
            if not resolved_targets and rel_file in file_to_symbols:
                same_file_matches = file_to_symbols[rel_file].get(simple_name, [])
                if chunk.parent_class and not same_file_matches:
                    same_file_matches = file_to_symbols[rel_file].get(f"{chunk.parent_class}.{simple_name}", [])
                resolved_targets.extend(same_file_matches)

            # 5. Unambiguous global match in the repository
            if not resolved_targets:
                glob_matches = global_symbols.get(simple_name, [])
                if len(glob_matches) == 1:
                    resolved_targets.extend(glob_matches)

            for target in resolved_targets:
                if target != caller and target in graph:
                    graph.add_edge(caller, target)

    return graph


def _find_matches(graph: nx.DiGraph, name: str) -> list[str]:
    """Find all node IDs in graph matching a query name (simple name, method name, or qualified ID)."""
    if not name or not name.strip():
        return []

    clean_name = name.strip().strip("'\"`")
    for prefix in ("def ", "async def ", "function ", "class ", "const ", "let ", "var ", "export "):
        if clean_name.startswith(prefix):
            clean_name = clean_name[len(prefix):].strip()

    # Strip arguments / parentheses e.g. "get_h2h(row)" -> "get_h2h"
    clean_name = re.sub(r"\(.*?\)", "", clean_name)
    # Strip line numbers or colons e.g. "IPL_Prediction.py:25", "get_h2h:", "get_h2h#L10"
    clean_name = re.sub(r"[:#]L?\d+$", "", clean_name)
    clean_name = clean_name.rstrip("():;").strip().replace("\\", "/")

    if not clean_name:
        return []

    if clean_name in graph:
        return [clean_name]

    matches = []
    # 1. Exact symbol / node / file match (case-sensitive)
    for n in graph.nodes:
        node_name = graph.nodes[n].get("name", "")
        if n == clean_name or n.endswith(f"::{clean_name}") or n.endswith(f"/{clean_name}"):
            matches.append(n)
        elif node_name == clean_name:
            matches.append(n)
        elif "::" in n:
            sym = n.split("::")[-1]
            if sym == clean_name or sym.endswith(f".{clean_name}"):
                matches.append(n)
            file_part = n.split("::")[0]
            if file_part == clean_name or file_part.endswith(f"/{clean_name}"):
                matches.append(n)

    if matches:
        return list(dict.fromkeys(matches))

    # 2. Case-insensitive exact symbol / node / file match
    lower_name = clean_name.lower()
    for n in graph.nodes:
        node_name = (graph.nodes[n].get("name") or "").lower()
        if n.lower() == lower_name or n.lower().endswith(f"::{lower_name}"):
            matches.append(n)
        elif node_name == lower_name:
            matches.append(n)
        elif "::" in n:
            sym = n.split("::")[-1].lower()
            if sym == lower_name or sym.endswith(f".{lower_name}"):
                matches.append(n)
            file_part = n.split("::")[0].lower()
            if file_part == lower_name or file_part.endswith(f"/{lower_name}"):
                matches.append(n)

    if matches:
        return list(dict.fromkeys(matches))

    # 3. Substring matching on symbol name or file path if no exact matches and length >= 3
    if len(clean_name) >= 3:
        for n in graph.nodes:
            node_name = (graph.nodes[n].get("name") or "").lower()
            file_part = (graph.nodes[n].get("file_path") or n.split("::")[0]).lower()
            if lower_name in node_name or lower_name in file_part:
                matches.append(n)

    return list(dict.fromkeys(matches))


def callers_of(graph: nx.DiGraph, name: str) -> list[str]:
    """Return all direct callers of the matched node(s)."""
    matches = _find_matches(graph, name)
    callers = set()
    for m in matches:
        callers.update(graph.predecessors(m))
    return sorted(callers)


def callees_of(graph: nx.DiGraph, name: str) -> list[str]:
    """Return all direct callees of the matched node(s)."""
    matches = _find_matches(graph, name)
    callees = set()
    for m in matches:
        callees.update(graph.successors(m))
    return sorted(callees)


def blast_radius(graph: nx.DiGraph, name: str, max_depth: int = 2) -> dict[str, int]:
    """Return transitive callers with their distance up to max_depth."""
    matches = _find_matches(graph, name)
    affected: dict[str, int] = {}
    for start in matches:
        lengths = nx.single_source_shortest_path_length(
            graph.reverse(copy=False), start, cutoff=max_depth
        )
        for node, dist in lengths.items():
            if node != start:
                affected[node] = min(dist, affected.get(node, dist))
    return dict(sorted(affected.items(), key=lambda kv: kv[1]))


if __name__ == "__main__":
    import sys
    from ingestion.repo_walker import chunk_repo

    target_repo = sys.argv[1] if len(sys.argv) > 1 else "sample_repo"
    chunks = chunk_repo(target_repo, verbose=False)
    graph = build_graph(chunks, repo_path=target_repo)

    print(f"\nGraph built from {target_repo}")
    print(f"  nodes: {graph.number_of_nodes()}")
    print(f"  edges: {graph.number_of_edges()}")

    if len(sys.argv) > 2:
        query_name = sys.argv[2]
        print(f"\nWho calls '{query_name}'?  -> {callers_of(graph, query_name)}")
        print(f"What does '{query_name}' call?  -> {callees_of(graph, query_name)}")
        print(f"Blast radius of '{query_name}' (2 hops): {blast_radius(graph, query_name)}")

