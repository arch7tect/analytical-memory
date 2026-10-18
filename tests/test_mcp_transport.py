from __future__ import annotations

import json

import pytest
from mcp.types import CallToolResult, TextContent

from analytical_memory.mcp_transport import CompactMCPServer, compact_json_text


def test_json_text_preserves_literals_and_escapes() -> None:
    original = r"""{
        "text": "line one\n  line two\tquote: \" slash: \\",
        "unicode": "λ Привет \u0000",
        "numbers": [1.23000000000000000000000000001, -0.0, 1E+100, 9007199254740993],
        "nested": {"empty": null, "present": false, "list": [ {}, [] ]}
    }"""
    packed = compact_json_text(original)
    assert json.loads(packed) == json.loads(original)
    assert "1.23000000000000000000000000001,-0.0,1E+100,9007199254740993" in packed
    assert r"line one\n  line two\tquote: \" slash: \\" in packed
    assert r"λ Привет \u0000" in packed
    assert compact_json_text(packed) == packed


@pytest.mark.anyio
async def test_structured_result_and_unstructured_blocks_are_preserved() -> None:
    server = CompactMCPServer("test")

    @server.tool()
    def structured() -> dict[str, object]:
        return {"rows": [{"message": "two  spaces\nand newline", "value": None}]}

    @server.tool()
    def blocks() -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text="plain  text\n")])

    @server.tool()
    def failure() -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=' { "error": true } ')],
            is_error=True,
        )

    result = await server.call_tool("structured", {})
    assert isinstance(result, CallToolResult)
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == result.structured_content
    assert result.content[0].text == (
        '{"rows":[{"message":"two  spaces\\nand newline","value":null}]}'
    )
    plain = await server.call_tool("blocks", {})
    assert isinstance(plain, CallToolResult)
    assert plain.content == [TextContent(type="text", text="plain  text\n")]
    error = await server.call_tool("failure", {})
    assert isinstance(error, CallToolResult) and error.is_error
    assert error.content == [TextContent(type="text", text=' { "error": true } ')]
