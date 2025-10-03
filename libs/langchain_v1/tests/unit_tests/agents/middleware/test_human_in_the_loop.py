"""Tests for HumanInTheLoopMiddleware."""

import pytest
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    HumanInTheLoopMiddleware,
)

from ..model import FakeToolCallingModel


def test_human_in_the_loop_middleware_initialization() -> None:
    """Test HumanInTheLoopMiddleware initialization."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_accept": True, "allow_edit": True, "allow_respond": True}
        },
        description_prefix="Custom prefix",
    )

    assert middleware.interrupt_on == {
        "test_tool": {"allow_accept": True, "allow_edit": True, "allow_respond": True}
    }
    assert middleware.description_prefix == "Custom prefix"


def test_human_in_the_loop_middleware_no_interrupts_needed() -> None:
    """Test HumanInTheLoopMiddleware when no interrupts are needed."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_respond": True, "allow_edit": True, "allow_accept": True}
        }
    )

    # Test with no messages
    state: dict[str, Any] = {"messages": []}
    result = middleware.after_model(state, None)
    assert result is None

    # Test with message but no tool calls
    state = {"messages": [HumanMessage(content="Hello"), AIMessage(content="Hi there")]}
    result = middleware.after_model(state, None)
    assert result is None

    # Test with tool calls that don't require interrupts
    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "other_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}
    result = middleware.after_model(state, None)
    assert result is None


def test_human_in_the_loop_middleware_single_tool_accept() -> None:
    """Test HumanInTheLoopMiddleware with single tool accept response."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_respond": True, "allow_edit": True, "allow_accept": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_accept(requests):
        return [{"type": "accept", "args": None}]

    with patch("langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_accept):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0] == ai_message
        assert result["messages"][0].tool_calls == ai_message.tool_calls

    state["messages"].append(
        ToolMessage(content="Tool message", name="test_tool", tool_call_id="1")
    )
    state["messages"].append(AIMessage(content="test_tool called with result: Tool message"))

    result = middleware.after_model(state, None)
    # No interrupts needed
    assert result is None


def test_human_in_the_loop_middleware_single_tool_edit() -> None:
    """Test HumanInTheLoopMiddleware with single tool edit response."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_respond": True, "allow_edit": True, "allow_accept": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_edit(requests):
        return [
            {
                "type": "edit",
                "args": ActionRequest(
                    action="test_tool",
                    args={"input": "edited"},
                ),
            }
        ]

    with patch("langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_edit):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].tool_calls[0]["args"] == {"input": "edited"}
        assert result["messages"][0].tool_calls[0]["id"] == "1"  # ID should be preserved


def test_human_in_the_loop_middleware_single_tool_response() -> None:
    """Test HumanInTheLoopMiddleware with single tool response with custom message."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_respond": True, "allow_edit": True, "allow_accept": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_response(requests):
        return [{"type": "response", "args": "Custom response message"}]

    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_response
    ):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 2
        assert isinstance(result["messages"][0], AIMessage)
        assert isinstance(result["messages"][1], ToolMessage)
        assert result["messages"][1].content == "Custom response message"
        assert result["messages"][1].name == "test_tool"
        assert result["messages"][1].tool_call_id == "1"


def test_human_in_the_loop_middleware_multiple_tools_mixed_responses() -> None:
    """Test HumanInTheLoopMiddleware with multiple tools and mixed response types."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "get_forecast": {"allow_accept": True, "allow_edit": True, "allow_respond": True},
            "get_temperature": {"allow_accept": True, "allow_edit": True, "allow_respond": True},
        }
    )

    ai_message = AIMessage(
        content="I'll help you with weather",
        tool_calls=[
            {"name": "get_forecast", "args": {"location": "San Francisco"}, "id": "1"},
            {"name": "get_temperature", "args": {"location": "San Francisco"}, "id": "2"},
        ],
    )
    state = {"messages": [HumanMessage(content="What's the weather?"), ai_message]}

    def mock_mixed_responses(requests):
        return [
            {"type": "accept", "args": None},
            {"type": "response", "args": "User rejected this tool call"},
        ]

    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_mixed_responses
    ):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert (
            len(result["messages"]) == 2
        )  # AI message with accepted tool call + tool message for rejected

        # First message should be the AI message with both tool calls
        updated_ai_message = result["messages"][0]
        assert len(updated_ai_message.tool_calls) == 2  # Both tool calls remain
        assert updated_ai_message.tool_calls[0]["name"] == "get_forecast"  # Accepted
        assert updated_ai_message.tool_calls[1]["name"] == "get_temperature"  # Got response

        # Second message should be the tool message for the rejected tool call
        tool_message = result["messages"][1]
        assert isinstance(tool_message, ToolMessage)
        assert tool_message.content == "User rejected this tool call"
        assert tool_message.name == "get_temperature"


def test_human_in_the_loop_middleware_multiple_tools_edit_responses() -> None:
    """Test HumanInTheLoopMiddleware with multiple tools and edit responses."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "get_forecast": {"allow_accept": True, "allow_edit": True, "allow_respond": True},
            "get_temperature": {"allow_accept": True, "allow_edit": True, "allow_respond": True},
        }
    )

    ai_message = AIMessage(
        content="I'll help you with weather",
        tool_calls=[
            {"name": "get_forecast", "args": {"location": "San Francisco"}, "id": "1"},
            {"name": "get_temperature", "args": {"location": "San Francisco"}, "id": "2"},
        ],
    )
    state = {"messages": [HumanMessage(content="What's the weather?"), ai_message]}

    def mock_edit_responses(requests):
        return [
            {
                "type": "edit",
                "args": ActionRequest(
                    action="get_forecast",
                    args={"location": "New York"},
                ),
            },
            {
                "type": "edit",
                "args": ActionRequest(
                    action="get_temperature",
                    args={"location": "New York"},
                ),
            },
        ]

    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_edit_responses
    ):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1

        updated_ai_message = result["messages"][0]
        assert updated_ai_message.tool_calls[0]["args"] == {"location": "New York"}
        assert updated_ai_message.tool_calls[0]["id"] == "1"  # ID preserved
        assert updated_ai_message.tool_calls[1]["args"] == {"location": "New York"}
        assert updated_ai_message.tool_calls[1]["id"] == "2"  # ID preserved


def test_human_in_the_loop_middleware_edit_with_modified_args() -> None:
    """Test HumanInTheLoopMiddleware with edit action that includes modified args."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_accept": True, "allow_edit": True, "allow_respond": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_edit_with_args(requests):
        return [
            {
                "type": "edit",
                "args": ActionRequest(
                    action="test_tool",
                    args={"input": "modified"},
                ),
            }
        ]

    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt",
        side_effect=mock_edit_with_args,
    ):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1

        # Should have modified args
        updated_ai_message = result["messages"][0]
        assert updated_ai_message.tool_calls[0]["args"] == {"input": "modified"}
        assert updated_ai_message.tool_calls[0]["id"] == "1"  # ID preserved


def test_human_in_the_loop_middleware_unknown_response_type() -> None:
    """Test HumanInTheLoopMiddleware with unknown response type."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_accept": True, "allow_edit": True, "allow_respond": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_unknown(requests):
        return [{"type": "unknown", "args": None}]

    with patch("langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_unknown):
        with pytest.raises(
            ValueError,
            match=r"Unexpected human response: {'type': 'unknown', 'args': None}. Response action 'unknown' is not allowed for tool 'test_tool'. Expected one of \['accept', 'edit', 'response'\] based on the tool's configuration.",
        ):
            middleware.after_model(state, None)


def test_human_in_the_loop_middleware_disallowed_action() -> None:
    """Test HumanInTheLoopMiddleware with action not allowed by tool config."""
    # edit is not allowed by tool config
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_respond": True, "allow_edit": False, "allow_accept": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_disallowed_action(requests):
        return [
            {
                "type": "edit",
                "args": ActionRequest(
                    action="test_tool",
                    args={"input": "modified"},
                ),
            }
        ]

    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt",
        side_effect=mock_disallowed_action,
    ):
        with pytest.raises(
            ValueError,
            match=r"Unexpected human response: {'type': 'edit', 'args': {'action': 'test_tool', 'args': {'input': 'modified'}}}. Response action 'edit' is not allowed for tool 'test_tool'. Expected one of \['accept', 'response'\] based on the tool's configuration.",
        ):
            middleware.after_model(state, None)


def test_human_in_the_loop_middleware_mixed_auto_approved_and_interrupt() -> None:
    """Test HumanInTheLoopMiddleware with mix of auto-approved and interrupt tools."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "interrupt_tool": {"allow_respond": True, "allow_edit": True, "allow_accept": True}
        }
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[
            {"name": "auto_tool", "args": {"input": "auto"}, "id": "1"},
            {"name": "interrupt_tool", "args": {"input": "interrupt"}, "id": "2"},
        ],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    def mock_accept(requests):
        return [{"type": "accept", "args": None}]

    with patch("langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_accept):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1

        updated_ai_message = result["messages"][0]
        # Should have both tools: auto-approved first, then interrupt tool
        assert len(updated_ai_message.tool_calls) == 2
        assert updated_ai_message.tool_calls[0]["name"] == "auto_tool"
        assert updated_ai_message.tool_calls[1]["name"] == "interrupt_tool"


def test_human_in_the_loop_middleware_interrupt_request_structure() -> None:
    """Test that interrupt requests are structured correctly."""
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "test_tool": {"allow_accept": True, "allow_edit": True, "allow_respond": True}
        },
        description_prefix="Custom prefix",
    )

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test", "location": "SF"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    captured_requests = []

    def mock_capture_requests(requests):
        captured_requests.extend(requests)
        return [{"type": "accept", "args": None}]

    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt", side_effect=mock_capture_requests
    ):
        middleware.after_model(state, None)

        assert len(captured_requests) == 1
        request = captured_requests[0]

        assert "action_request" in request
        assert "config" in request
        assert "description" in request

        assert request["action_request"]["action"] == "test_tool"
        assert request["action_request"]["args"] == {"input": "test", "location": "SF"}
        expected_config = {"allow_accept": True, "allow_edit": True, "allow_respond": True}
        assert request["config"] == expected_config
        assert "Custom prefix" in request["description"]
        assert "Tool: test_tool" in request["description"]
        assert "Args: {'input': 'test', 'location': 'SF'}" in request["description"]


def test_human_in_the_loop_middleware_boolean_configs() -> None:
    """Test HITL middleware with boolean tool configs."""
    middleware = HumanInTheLoopMiddleware(interrupt_on={"test_tool": True})

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    # Test accept
    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt",
        return_value=[{"type": "accept", "args": None}],
    ):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].tool_calls == ai_message.tool_calls

    # Test edit
    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt",
        return_value=[
            {
                "type": "edit",
                "args": ActionRequest(
                    action="test_tool",
                    args={"input": "edited"},
                ),
            }
        ],
    ):
        result = middleware.after_model(state, None)
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].tool_calls[0]["args"] == {"input": "edited"}

    middleware = HumanInTheLoopMiddleware(interrupt_on={"test_tool": False})

    result = middleware.after_model(state, None)
    # No interruption should occur
    assert result is None


def test_human_in_the_loop_middleware_sequence_mismatch() -> None:
    """Test that sequence mismatch in resume raises an error."""
    middleware = HumanInTheLoopMiddleware(interrupt_on={"test_tool": True})

    ai_message = AIMessage(
        content="I'll help you",
        tool_calls=[{"name": "test_tool", "args": {"input": "test"}, "id": "1"}],
    )
    state = {"messages": [HumanMessage(content="Hello"), ai_message]}

    # Test with too few responses
    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt",
        return_value=[],  # No responses for 1 tool call
    ):
        with pytest.raises(
            ValueError,
            match=r"Number of human responses \(0\) does not match number of hanging tool calls \(1\)\.",
        ):
            middleware.after_model(state, None)

    # Test with too many responses
    with patch(
        "langchain.agents.middleware.human_in_the_loop.interrupt",
        return_value=[
            {"type": "accept", "args": None},
            {"type": "accept", "args": None},
        ],  # 2 responses for 1 tool call
    ):
        with pytest.raises(
            ValueError,
            match=r"Number of human responses \(2\) does not match number of hanging tool calls \(1\)\.",
        ):
            middleware.after_model(state, None)
