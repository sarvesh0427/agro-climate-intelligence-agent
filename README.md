# Agro-Climate Intelligence Agent

### Production-Grade Multi-Agent Decision Framework for Sustainable Agriculture

[![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Built with Antigravity](https://img.shields.io/badge/Framework-Antigravity%20ADK-green)](https://www.kaggle.com/competitions/vibecoding-agents-capstone-project)

---

## 🎥 Submission Deliverables
* **Project Writeup & Code Deployment:** Available via the Kaggle Notebook Platform.
* **YouTube Video Demonstration (5-Min Pitch):** coming soon
* **Production Code Base:** Hosted in this GitHub Repository.

---

## 📋 Problem Statement & Core Value
Smallholder farmers and local agricultural coordinators face immense friction when translating raw, fragmented climate and soil metrics into timely irrigation plans. Static dashboards fail to offer actionable reasoning, leading to either water wastage or crop failure.

**The Solution:** The **Agro-Climate Intelligence Agent** leverages a secure multi-agent architecture to autonomously ingest authenticated environmental data via a standardized Model Context Protocol (MCP) server, apply safety guardrails against malicious inputs, and synthesize localized, high-urgency irrigation strategies.

---

## System Architecture

Our solution is engineered around three core course pillars to ensure modularity, scalability, and security:

```text
                  [ User Input / Streamlit UI ]
                               │
                               ▼
            ┌──────────────────────────────────────┐
            │     Security Guardrail Agent         │
            │  (Regex & Prompt Injection Audit)    │
            └──────────────────┬───────────────────┘
                               │
                       [ Cleared Input ]
                               │
                               ▼
            ┌──────────────────────────────────────┐
            │       Coordinator Agent (ADK)        │
            └──────────────────┬───────────────────┘
                               │
                     [ Orchestrates Tools ]
                               │
                               ▼
            ┌──────────────────────────────────────┐
            │      FastMCP Analytics Server        │
            │     (Safe Parameterized SQL)         │
            └──────────────────────────────────────┘
```

### Key Concepts Demonstrated:
1. **Multi-Agent Coordination (ADK):** Utilizing an Orchestrator pattern where a specialized *Security Guardrail Agent* pre-screens constraints before handing off tasks to the *AgroCoordinator Agent*.
2. **Model Context Protocol (FastMCP):** Isolation of data retrieval tasks into an independent, typed tool server (`app_mcp.py`) utilizing strict Pydantic validation schemas.
3. **Enterprise Security Gating:** Protects infrastructure from prompt injections and SQL execution anomalies using defensive input validation and parameterized data lookups.

---

## Tech Stack & Agent Skills
* **Agent Framework:** Antigravity ADK & Agents CLI patterns.
* **Tool Interface:** FastMCP (Model Context Protocol).
* **Frontend Dashboard:** Streamlit (Python).
* **Database Layer:** Mock SQL Ecosystem (SQLite parameterized backend).

---

## Setup & Installation Instructions

Ensure you have Python 3.10+ installed on your system.

### 1. Initialize the Environment
```bash
# Navigate to the cloned repository
cd agro-climate-intelligence-agent

# Activate your virtual environment (if not already done)
# For Windows:
venv\Scripts\activate
# For macOS/Linux:
source venv/bin/bin/activate
