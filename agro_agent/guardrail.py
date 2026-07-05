import re
from typing import Any

from google.adk.agents.context import Context
from google.adk.workflow._node import node

from agro_agent.geo_utils import validate_coordinates

BANNED_KEYWORDS = [
    r"drop table",
    r"delete from",
    r"ignore previous instructions",
    r"system prompt",
]
MAX_PROMPT_LENGTH = 2000
REGISTRY_REGION_PATTERN = re.compile(r"^REG-\d{3}$")
CUSTOM_REGION_PATTERN = re.compile(r"^REG-CUST-[a-f0-9]{6}$")
ONE_TIME_REGION_ID = "REG-CUST-000000"


def audit_custom_coords(lat: float | None, lon: float | None) -> tuple[bool, str | None]:
    if lat is None or lon is None:
        return False, "Custom farm requires valid latitude and longitude."
    ok, reason = validate_coordinates(lat, lon)
    if not ok:
        return False, reason
    return True, None


def audit_input(
    user_prompt: str,
    region_id: str,
    *,
    region_mode: str = "registry",
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[bool, str | None]:
    """Return (is_safe, block_reason)."""
    if len(user_prompt) > MAX_PROMPT_LENGTH:
        return False, "Input exceeds maximum allowed length."

    if "MALICIOUS" in region_id:
        return False, "Region failed format verification."

    if region_mode == "custom":
        if region_id != ONE_TIME_REGION_ID and not CUSTOM_REGION_PATTERN.match(region_id):
            return False, "Invalid custom farm ID. Must match REG-CUST-XXXXXX."
        ok, reason = audit_custom_coords(latitude, longitude)
        if not ok:
            return False, reason
    elif not REGISTRY_REGION_PATTERN.match(region_id):
        return False, "Invalid region ID format. Must match REG-XXX."

    for pattern in BANNED_KEYWORDS:
        if re.search(pattern, user_prompt, re.IGNORECASE):
            return False, "Input failed prompt-sanitization checks."

    return True, None


@node
def security_screen(ctx: Context, node_input: Any) -> dict[str, Any]:
    user_intent = str(ctx.state.get("user_intent", ""))
    region_id = str(ctx.state.get("region_id", ""))
    region_mode = str(ctx.state.get("region_mode", "registry"))
    latitude = ctx.state.get("latitude")
    longitude = ctx.state.get("longitude")

    is_safe, reason = audit_input(
        user_intent,
        region_id,
        region_mode=region_mode,
        latitude=latitude,
        longitude=longitude,
    )
    if not is_safe:
        ctx.route = "blocked"
        ctx.state["block_reason"] = reason
        return {"status": "blocked", "message": reason, "stage": "guardrail"}

    ctx.route = "cleared"
    return {
        "status": "cleared",
        "stage": "guardrail",
        "user_intent": user_intent,
        "region_id": region_id,
        "region_mode": region_mode,
    }


@node
def blocked_output(ctx: Context, node_input: Any) -> dict[str, Any]:
    reason = ctx.state.get("block_reason", "Security violation blocked.")
    return {
        "status": "blocked",
        "message": reason,
        "stage": "guardrail",
    }
