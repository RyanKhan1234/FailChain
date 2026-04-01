"""Parser registry — maps parser type strings to parser classes."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path
from typing import Type

from failchain.parsers.base import BaseParser


class ParserRegistry:
    _registry: dict[str, Type[BaseParser]] = {}
    _loaded_entry_points: bool = False

    @classmethod
    def register(cls, name: str, parser_class: Type[BaseParser]) -> None:
        """Manually register a parser class under the given name."""
        cls._registry[name] = parser_class

    @classmethod
    def _load_entry_points(cls) -> None:
        if cls._loaded_entry_points:
            return
        cls._loaded_entry_points = True
        try:
            eps = entry_points(group="failchain.parsers")
            for ep in eps:
                try:
                    cls._registry[ep.name] = ep.load()
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    def get(cls, name: str) -> Type[BaseParser]:
        cls._load_entry_points()
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry.keys()))
            raise ValueError(
                f"Unknown parser '{name}'. Available parsers: {available}\n"
                "You can register custom parsers via the 'failchain.parsers' entry point."
            )
        return cls._registry[name]

    @classmethod
    def all_names(cls) -> list[str]:
        cls._load_entry_points()
        return sorted(cls._registry.keys())

    @classmethod
    def auto_detect(cls, report_path: str | Path) -> str:
        """Guess parser name from file extension."""
        cls._load_entry_points()
        ext = Path(report_path).suffix.lower()
        for name, klass in cls._registry.items():
            if ext in klass.extensions:
                return name
        return "junit-xml"


# Bootstrap built-in parsers
def _bootstrap() -> None:
    from failchain.parsers.junit_xml import JUnitXMLParser
    from failchain.parsers.playwright_json import PlaywrightJSONParser

    ParserRegistry.register("junit-xml", JUnitXMLParser)
    ParserRegistry.register("playwright-json", PlaywrightJSONParser)


_bootstrap()
