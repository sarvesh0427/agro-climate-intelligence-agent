import sys
from typing import Any

from google.adk import Agent, Workflow
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.workflow import START
from mcp import StdioServerParameters
from pydantic import BaseModel, Field

from agro_agent.config import Settings
from agro_agent.guardrail import blocked_output, security_screen


class AgroPlanOutput(BaseModel):
    irrigation_urgency: str = Field(description="HIGH, MEDIUM, or LOW")
    reasoning: str = Field(description="Farmer-friendly explanation of the plan")
    actions: list[str] = Field(description="Concrete irrigation actions to take")
    risks: list[str] = Field(description="Risks if the plan is ignored")


COORDINATOR_INSTRUCTION = """You are the Lead Agro-Climate Intelligence Coordinator.

Your job is to translate soil and environmental metrics into practical, safe irrigation
strategies for local farmers.

Context for this request:
- Location: {region_name} ({region_district})
- Coordinates: latitude {latitude}, longitude {longitude}
- Crop: {crop}
- Farmer strategy request: {user_intent}

Required steps:
1. Call fetch_location_metrics with latitude, longitude, and crop.
2. If the farmer strategy mentions days or multi-day planning, also call get_weather_forecast
   with latitude, longitude, and an appropriate number of days (default 3).
3. Analyze soil moisture, temperature, crop type, and baseline urgency from tool output.
4. Honor the farmer's strategy request when forming recommendations.
5. Produce a concise irrigation plan.

Output requirements (mandatory):
- reasoning: at least 2 complete sentences for the farmer.
- actions: at least 2 concrete, specific irrigation steps (not empty).
- risks: at least 1 risk when urgency is HIGH or MEDIUM.
- irrigation_urgency: HIGH, MEDIUM, or LOW aligned with tool output.

Safety rules:
- Never invent metrics; only use tool output.
- Prefer water conservation when the farmer asks for sustainability.
- Flag crop stress risks clearly when soil moisture is low.
"""


def _build_mcp_toolset(settings: Settings) -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[str(settings.mcp_script_resolved)],
            ),
            timeout=30.0,
        ),
        tool_filter=["fetch_location_metrics", "get_weather_forecast"],
    )


def create_agro_workflow(settings: Settings) -> Workflow:
    coordinator_agent = Agent(
        name="coordinator_agent",
        model=settings.agro_model,
        instruction=COORDINATOR_INSTRUCTION,
        tools=[_build_mcp_toolset(settings)],
        output_schema=AgroPlanOutput,
        mode="single_turn",
    )

    return Workflow(
        name="agro_workflow",
        edges=[
            (START, security_screen),
            (security_screen, {"blocked": blocked_output, "cleared": coordinator_agent}),
        ],
    )
