import ast
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_PACKAGES = {"agent", "tools", "knowledge"}


def _iter_python_files(package_dir):
    for root, _dirs, files in os.walk(package_dir):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def test_agent_tools_knowledge_never_import_ground_truth():
    offenders = []
    for package in FORBIDDEN_PACKAGES:
        package_dir = os.path.join(PROJECT_ROOT, package)
        if not os.path.isdir(package_dir):
            continue
        for path in _iter_python_files(package_dir):
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and "GroundTruthBug" in [alias.name for alias in node.names]
                ):
                    offenders.append(path)
    assert not offenders, f"GroundTruthBug referenced in agent/tools/knowledge code: {offenders}"
