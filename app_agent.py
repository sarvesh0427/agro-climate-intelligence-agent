# app_agent.py
import re
from typing import Dict, Any

# --- SECURITY FEATURE: Prompt Injection & Malicious Content Guardrail ---
class SecurityGuardrailAgent:
    def __init__(self):
        # Prevent common SQL injection and prompt override keywords
        self.banned_keywords = [r"drop table", r"delete from", r"ignore previous instructions", r"system prompt"]

    def audit_input(self, user_prompt: str) -> bool:
        """Returns True if safe, False if a threat is detected."""
        for pattern in self.banned_keywords:
            if re.search(pattern, user_prompt, re.IGNORECASE):
                return False
        return True

class AgroCoordinatorAgent:
    def __init__(self, mcp_client):
        self.mcp = mcp_client
        self.system_prompt = (
            "You are the Lead Agro-Climate Intelligence Coordinator. Your job is to translate "
            "raw soil and environmental metrics into practical, safe irrigation strategies for local farmers."
        )

    def execute_plan(self, user_intent: str, region_id: str) -> Dict[str, Any]:
        # Step 1: Call the MCP Tool Server to grab live metrics safely
        try:
            raw_metrics = self.mcp.fetch_agro_metrics({"region_id": region_id})
            if "error" in raw_metrics:
                return {"status": "error", "message": raw_metrics["error"]}
        except Exception as e:
            return {"status": "error", "message": f"MCP execution failed: {str(e)}"}

        # Step 2: Formulate Agentic Reasoning
        moisture = raw_metrics["current_soil_moisture_pct"]
        urgency = raw_metrics["irrigation_urgency"]
        
        reasoning = (
            f"Analysis complete for {region_id}. Current soil moisture level sits at {moisture}%. "
            f"Under our agricultural preservation framework, this triggers a {urgency} urgency status. "
            f"Action plan: Optimize water delivery for {raw_metrics['recommended_crop']} cultivation."
        )
        
        return {
            "status": "success",
            "data": raw_metrics,
            "reasoning": reasoning
        }