from google.adk.events import Event
from google.genai import types

from apps.agent_api.agent_runtime import inspect_adk_event


def test_extracts_redacted_tool_trajectory_without_arguments() -> None:
    event = Event(
        author="agentic_checkout",
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_function_call(
                    name="execute_authorized_checkout",
                    args={"authorization_id": "secret-id"},
                )
            ],
        ),
    )

    traces, final_text, checkout_result = inspect_adk_event(event)

    assert [(trace.tool_name, trace.phase) for trace in traces] == [
        ("execute_authorized_checkout", "requested")
    ]
    assert not hasattr(traces[0], "arguments")
    assert final_text is None
    assert checkout_result is None


def test_extracts_structured_checkout_result() -> None:
    checkout = {"status": "confirmed", "mode": "mock", "real_funds_moved": False}
    event = Event(
        author="agentic_checkout",
        content=types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name="execute_authorized_checkout",
                    response=checkout,
                )
            ],
        ),
    )

    traces, _, checkout_result = inspect_adk_event(event)

    assert [(trace.tool_name, trace.phase) for trace in traces] == [
        ("execute_authorized_checkout", "completed")
    ]
    assert checkout_result == checkout


def test_extracts_final_agent_text() -> None:
    event = Event(
        author="agentic_checkout",
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="결제가 확인되었습니다.")],
        ),
    )

    traces, final_text, checkout_result = inspect_adk_event(event)

    assert traces == []
    assert final_text == "결제가 확인되었습니다."
    assert checkout_result is None
