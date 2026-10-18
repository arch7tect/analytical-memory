"""Lossless JSON text presentation after MCP result validation."""

from __future__ import annotations

import json
import re
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, InputRequiredResult, TextContent

_JSON_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|[ \t\r\n]+')


def compact_json_text(text: str) -> str:
    # Keep string escapes, numeric lexemes and member order byte-for-byte.
    # Only insignificant whitespace outside strings is removed.
    json.loads(text)
    return _JSON_TOKENS.sub(
        lambda match: match[0] if match[0].startswith('"') else "", text
    )


class CompactMCPServer(MCPServer[Any]):
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        result = await super().call_tool(name, arguments, context)
        if (
            isinstance(result, CallToolResult)
            and not result.is_error
            and result.structured_content is not None
            and len(result.content) == 1
            and isinstance(result.content[0], TextContent)
        ):
            block = result.content[0]
            try:
                text = compact_json_text(block.text)
            except ValueError:
                return result
            return result.model_copy(
                update={"content": [block.model_copy(update={"text": text})]}
            )
        return result
