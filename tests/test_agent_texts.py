from analytical_memory.agent_texts import agent_document, agent_text
from analytical_memory.api_models import FieldDeclarationInput
from analytical_memory.mcp_schema import describe_response_schema
from analytical_memory.mcp_server import agent_guide_document
from analytical_memory.resources import resource_path


def test_required_on_create_text_is_shared_by_agent_contracts() -> None:
    required = agent_text("field_declaration", "required")
    assert "creates a Node" in required
    assert "key-matched updates may omit it" in required
    assert "every imported record" not in required

    input_schema = FieldDeclarationInput.model_json_schema()
    assert input_schema["properties"]["required"]["description"] == required

    output_schema = describe_response_schema(
        {"type": "object", "properties": {"required": {"type": "boolean"}}}
    )
    assert output_schema["properties"]["required"]["description"] == required


def test_agent_guide_is_loaded_from_packaged_resource() -> None:
    assert resource_path("agent", "texts.json").is_file()
    guide = agent_guide_document()
    assert guide == agent_document("guide")
    assert (
        "Required declared fields must be present when a record creates a Node"
        in (guide["operations"]["import"])
    )

    guide["guide_version"] = "mutated"
    assert agent_guide_document()["guide_version"] == "1"
