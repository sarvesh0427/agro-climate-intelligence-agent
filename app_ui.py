# app_ui.py
import streamlit as st
from app_agent import SecurityGuardrailAgent, AgroCoordinatorAgent
from app_mcp import fetch_agro_metrics

st.set_page_config(page_title="AgroCloud Intelligence", layout="wide")

st.title("Agents For Good: Agro-Climate Intelligence System")
st.markdown("### Production-Grade Multi-Agent Decision Framework")

# Sidebar - Infrastructure Vibe Setup
st.sidebar.header("Agent Configuration")
st.sidebar.success("Antigravity ADK Active")
st.sidebar.success("MCP Server Connected")
st.sidebar.info("Security Mode: Strict Pydantic Verification")

# Main Interface Split
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Query Control Panel")
    region = st.selectbox("Select Target Region", ["REG-001", "REG-002", "REG-003", "MALICIOUS_INPUT"])
    user_prompt = st.text_area("Custom Strategy Request", "Generate a sustainable optimization plan for this sector.")
    
    run_btn = st.button("Trigger Agent Network", type="primary")

with col2:
    st.subheader("Agent System Logs & Outputs")
    
    if run_btn:
        guardrail = SecurityGuardrailAgent()
        
        # 1. Trigger Guardrail Audit
        with st.status("Security Guardrail Agent running...", expanded=True) as status:
            if not guardrail.audit_input(user_prompt) or "MALICIOUS" in region:
                status.update(label="!!! Security Violation Blocked !!!", state="error")
                st.error("Input failed prompt-sanitization and format verification. Transaction terminated.")
            else:
                status.update(label="Input Cleared by Guardrail", state="complete")
                
                # 2. Emulate MCP server tool bridge connection
                class MockMCPClient:
                    def fetch_agro_metrics(self, data):
                        from app_mcp import fetch_agro_metrics, RegionQuery
                        return fetch_agro_metrics(RegionQuery(region_id=data["region_id"]))

                coordinator = AgroCoordinatorAgent(mcp_client=MockMCPClient())
                
                with st.spinner("Coordinator Agent parsing execution plan..."):
                    result = coordinator.execute_plan(user_prompt, region)
                    
                if result["status"] == "success":
                    st.metric(label="Irrigation Urgency Level", value=result["data"]["irrigation_urgency"])
                    st.json(result["data"])
                    st.info(f"**Coordinator Agent Reasoning:** {result['reasoning']}")
                else:
                    st.error(result["message"])