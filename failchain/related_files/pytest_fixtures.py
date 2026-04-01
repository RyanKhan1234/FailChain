"""pytest fixtures related-file resolver.

pytest fixtures live in conftest.py files at any level of the directory tree.
This resolver includes all conftest.py files from the test file up to the
project root (where pytest.ini / pyproject.toml / setup.py is found).
"""

from __future__ import annotations

from pathlib import Path

from failchain.related_files.base import BaseRelatedFilesResolver

_PROJECT_MARKERS = {"pytest.ini", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini"}


class PytestFixturesResolver(BaseRelatedFilesResolver):
    name = "pytest-fixtures"

    def resolve(self, test_file_path: str | Path) -> list[str]:
        test_file = Path(test_file_path)
        if not test_file.exists():
            return []

        related: list[Path] = []
        content = test_file.read_text(encoding="utf-8", errors="replace")
        base_dir = test_file.parent

        # 1. All conftest.py files from test dir up to project root
        project_root = self._find_project_root(test_file)
        current = base_dir
        for _ in range(15):
            conftest = current / "conftest.py"
            if conftest.exists():
                related.append(conftest)
            if project_root and current == project_root:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        # 2. Relative Python imports
        for import_path in self._extract_imports(content):
            if import_path.startswith("."):
                # Convert dotted relative import to path
                parts = import_path.lstrip(".").replace(".", "/")
                candidate = base_dir / f"{parts}.py"
                if candidate.exists():
                    related.append(candidate)
                # Also try as package
                candidate2 = base_dir / parts / "__init__.py"
                if candidate2.exists():
                    related.append(candidate2)

        # Deduplicate
        test_resolved = test_file.resolve()
        seen: set[str] = set()
        result: list[str] = []
        for p in related:
            key = str(p.resolve())
            if key not in seen and p.resolve() != test_resolved:
                seen.add(key)
                result.append(str(p))

        return result

    @staticmethod
    def _find_project_root(start: Path) -> Path | None:
        current = start.parent
        for _ in range(15):
            for marker in _PROJECT_MARKERS:
                if (current / marker).exists():
                    return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None
