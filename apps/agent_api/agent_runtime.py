"""Run the ADK agent and expose a minimal, redacted tool trajectory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from apps.agent_api.agent import APP_NAME, adk_app


@dataclass(frozen=True, slots=True)
class AgentToolTrace:
    tool_name: str
    phase: str


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    final_text: str
    trajectory: tuple[AgentToolTrace, ...]
    checkout_result: dict[str, Any] | None


def inspect_adk_event(
    event: Event,
) -> tuple[list[AgentToolTrace], str | None, dict[str, Any] | None]:
    """Extract display-safe execution evidence from one ADK event."""

    traces: list[AgentToolTrace] = []
    checkout_result: dict[str, Any] | None = None
    for call in event.get_function_calls():
        traces.append(AgentToolTrace(tool_name=call.name or "unknown", phase="requested"))
    for response in event.get_function_responses():
        name = response.name or "unknown"
        traces.append(AgentToolTrace(tool_name=name, phase="completed"))
        if name == "execute_authorized_checkout" and isinstance(response.response, dict):
            checkout_result = response.response

    final_text: str | None = None
    if event.is_final_response() and event.content and event.content.parts:
        text_parts = [part.text for part in event.content.parts if part.text]
        if text_parts:
            final_text = "\n".join(text_parts)
    return traces, final_text, checkout_result


class AgentRuntime:
    """Process-local ADK runner suitable for the P0 single-instance demo."""

    def __init__(self) -> None:
        self._runner = InMemoryRunner(app=adk_app)

    async def run(
        self,
        *,
        user_id: str,
        session_id: str,
        prompt: str,
    ) -> AgentRunResult:
        session = await self._runner.session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            await self._runner.session_service.create_session(
                app_name=APP_NAME,
                user_id=user_id,
                session_id=session_id,
            )

        trajectory: list[AgentToolTrace] = []
        final_text = ""
        checkout_result: dict[str, Any] | None = None
        message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        async for event in self._runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            event_traces, event_text, event_checkout = inspect_adk_event(event)
            trajectory.extend(event_traces)
            if event_text is not None:
                final_text = event_text
            if event_checkout is not None:
                checkout_result = event_checkout

        return AgentRunResult(
            final_text=final_text,
            trajectory=tuple(trajectory),
            checkout_result=checkout_result,
        )
