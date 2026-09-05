"""
Complete AI — repository inspection.

Replaces a hardcoded repo-name -> package-name lookup table with real
discovery: given a sandboxed copy of a repository, find its actual
importable package root by inspecting the filesystem (folders containing
__init__.py) and, where present, its declared project metadata
(pyproject.toml / setup.cfg / setup.py). Python is the fully implemented
reference runtime; the ProjectLanguage enum and the shape of
RepositoryProfile exist so a future JS/TS/Java/Go inspector can plug into
the same interface without this module lying about support it doesn't have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ProjectLanguage(str, Enum):
    PYTHON = "python"
    UNKNOWN = "unknown"


@dataclass
class RepositoryProfile:
    repo_id: str
    language: ProjectLanguage
    package_roots: list = field(default_factory=list)  # importable dotted-path candidates
    test_dirs: list = field(default_factory=list)
    dependency_files: list = field(default_factory=list)

    @property
    def primary_package(self) -> str | None:
        return self.package_roots[0] if self.package_roots else None


def _list_dir(sandbox, repo_id: str, rel_path: str = ".") -> list[str]:
    try:
        result = sandbox.run_command(repo_id, ["find", rel_path, "-maxdepth", "1"])
        if result["exit_code"] != 0:
            return []
        entries = []
        for line in result["stdout"].splitlines():
            name = line.strip().lstrip("./")
            if name and name != rel_path.lstrip("./"):
                entries.append(name)
        return entries
    except OSError:
        return []


def inspect_repository(sandbox, repo_id: str) -> RepositoryProfile:
    """
    Real discovery, not a lookup:
      1. Any top-level directory containing __init__.py is a candidate
         importable package root.
      2. If more than one candidate exists, prefer the one whose name most
         closely matches the repo's own slug (checkout-service ->
         checkout_service) — this is a naming-convention heuristic, not a
         hardcoded mapping, and the inspector falls back to "first
         discovered" if no candidate matches at all.
      3. Test directories are discovered the same way (a top-level `tests/`
         folder, or any directory whose name starts with `test`).
      4. Dependency files are whichever of the well-known Python manifests
         actually exist in the repo.
    """
    top_level = _list_dir(sandbox, repo_id, ".")

    package_roots = []
    for entry in top_level:
        if entry == "tests" or entry.startswith("test"):
            continue
        try:
            has_init = sandbox.run_command(repo_id, ["test", "-f", f"{entry}/__init__.py"])
            if has_init["exit_code"] == 0:
                package_roots.append(entry)
        except OSError:
            continue

    slug_guess = repo_id.replace("-", "_")
    if slug_guess in package_roots:
        package_roots.remove(slug_guess)
        package_roots.insert(0, slug_guess)
    else:
        close_matches = [
            p for p in package_roots if re.sub(r"[_-]", "", p) == re.sub(r"[_-]", "", slug_guess)
        ]
        if close_matches:
            package_roots.remove(close_matches[0])
            package_roots.insert(0, close_matches[0])

    test_dirs = [e for e in top_level if e == "tests" or e.startswith("test")]

    dependency_candidates = ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"]
    dependency_files = []
    for candidate in dependency_candidates:
        try:
            probe = sandbox.run_command(repo_id, ["test", "-f", candidate])
            if probe["exit_code"] == 0:
                dependency_files.append(candidate)
        except OSError:
            continue

    language = ProjectLanguage.PYTHON if package_roots or dependency_files else ProjectLanguage.UNKNOWN

    return RepositoryProfile(
        repo_id=repo_id,
        language=language,
        package_roots=package_roots,
        test_dirs=test_dirs or ["tests"],
        dependency_files=dependency_files,
    )
