"""Registry for screenshot discovery strategies."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Type

from failchain.screenshots.base import BaseScreenshotDiscovery


class ScreenshotRegistry:
    _registry: dict[str, Type[BaseScreenshotDiscovery]] = {}
    _loaded_entry_points: bool = False

    @classmethod
    def register(cls, name: str, klass: Type[BaseScreenshotDiscovery]) -> None:
        cls._registry[name] = klass

    @classmethod
    def _load_entry_points(cls) -> None:
        if cls._loaded_entry_points:
            return
        cls._loaded_entry_points = True
        try:
            for ep in entry_points(group="failchain.screenshot_strategies"):
                try:
                    cls._registry[ep.name] = ep.load()
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    def get(cls, name: str) -> Type[BaseScreenshotDiscovery]:
        cls._load_entry_points()
        if name not in cls._registry:
            # Graceful fallback: return Playwright (most common)
            return cls._registry.get("playwright", list(cls._registry.values())[0])
        return cls._registry[name]

    @classmethod
    def all_names(cls) -> list[str]:
        cls._load_entry_points()
        return sorted(cls._registry.keys())


def _bootstrap() -> None:
    from failchain.screenshots.cypress import CypressScreenshotDiscovery
    from failchain.screenshots.playwright import PlaywrightScreenshotDiscovery

    ScreenshotRegistry.register("playwright", PlaywrightScreenshotDiscovery)
    ScreenshotRegistry.register("cypress", CypressScreenshotDiscovery)


_bootstrap()
