"""Tool registry — allows plugins to register custom LangChain tools.

Usage in a plugin:
    from failchain.tools.registry import ToolRegistry
    from langchain_core.tools import tool

    @tool
    def my_custom_tool(arg: str) -> str:
        \"\"\"My custom investigation tool.\"\"\"
        return ...

    ToolRegistry.register(my_custom_tool)
"""

from __future__ import annotations

from langchain_core.tools import BaseTool


class ToolRegistry:
    _extra_tools: list[BaseTool] = []

    @classmethod
    def register(cls, tool_or_func) -> None:
        """Register a custom tool to be included in every agent run.

        Accepts either a BaseTool instance or a @tool-decorated function.
        """
        if isinstance(tool_or_func, BaseTool):
            cls._extra_tools.append(tool_or_func)
        else:
            # Assume it's been decorated with @tool and is already a BaseTool
            cls._extra_tools.append(tool_or_func)

    @classmethod
    def get_extra_tools(cls) -> list[BaseTool]:
        return list(cls._extra_tools)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered extra tools (mainly for testing)."""
        cls._extra_tools.clear()
