# app_agent.py — backward-compatible shim for legacy imports.
from agro_agent.guardrail import audit_input, security_screen, blocked_output

__all__ = ["SecurityGuardrailAgent", "audit_input", "security_screen", "blocked_output"]


class SecurityGuardrailAgent:
    """Legacy wrapper; prefer agro_agent.guardrail.audit_input in new code."""

    def audit_input(self, user_prompt: str) -> bool:
        is_safe, _ = audit_input(
            user_prompt,
            "REG-CUST-000000",
            latitude=0.0,
            longitude=0.0,
        )
        return is_safe
