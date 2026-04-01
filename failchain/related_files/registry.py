"""Registry for related-file resolution strategies."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Optional, Type

from failchain.related_files.base import BaseRelatedFilesResolver


class RelatedFilesRegistry:
    _registry: dict[str, Type[BaseRelatedFilesResolver]] = {}
    _loaded: bool = False

    @classmethod
    def register(cls, name: str, klass: Type[BaseRelatedFilesResolver]) -> None:
        cls._registry[name] = klass

    @classmethod
    def _load_entry_points(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True
        try:
            for ep in entry_points(group="failchain.related_file_strategies"):
                try:
                    cls._registry[ep.name] = ep.load()
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseRelatedFilesResolver]]:
        cls._load_entry_points()
        if name == "none":
            return None
        if name not in cls._registry:
            # Graceful fallback: no related file resolution
            return None
        return cls._registry[name]

    @classmethod
    def all_names(cls) -> list[str]:
        cls._load_entry_points()
        return ["none"] + sorted(cls._registry.keys())


def _bootstrap() -> None:
    from failchain.related_files.cypress_commands import CypressCommandsResolver
    from failchain.related_files.playwright_pom import PlaywrightPOMResolver
    from failchain.related_files.pytest_fixtures import PytestFixturesResolver

    RelatedFilesRegistry.register("playwright-pom", PlaywrightPOMResolver)
    RelatedFilesRegistry.register("cypress-commands", CypressCommandsResolver)
    RelatedFilesRegistry.register("pytest-fixtures", PytestFixturesResolver)


_bootstrap()
