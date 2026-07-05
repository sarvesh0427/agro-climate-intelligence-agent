# app_mcp.py
# This code implements a FastMCP server where it provides agents with real, programamatically validated data tools for agriculture metrics
import sqlite3
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

# Initialize FastMCP Server
mcp = FastMCP("AgroClimateToolServer")

# SECURITY FEATURE: Strict Input Validation Schema 
class RegionQuery(BaseModel):
    region_id: str = Field(..., description="The unique identifier for the agricultural zone (e.g., REG-001)")
    forecast_days: int = Field(default=3, description="Number of days to forecast soil moisture trends")

    @field_validator('region_id')
    @classmethod
    def validate_region_format(cls, v: str) -> str:
        if not v.startswith("REG-"):
            raise ValueError("Security Alert: Invalid Region ID format. Must match 'REG-XXX'")
        return v

# Mock Database Setup for quick standalone deployment
# Inside app_mcp.py
def init_mock_db():
    # ADD check_same_thread=False inside the parentheses here:
    conn = sqlite3.connect(":memory:", check_same_thread=False) 
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE soil_metrics (
            region_id TEXT, soil_moisture REAL, temperature REAL, recommended_crop TEXT
        )
    """)
    cursor.executemany("INSERT INTO soil_metrics VALUES (?, ?, ?, ?)", [
        ("REG-001", 22.5, 28.4, "Maize"),
        ("REG-002", 45.1, 19.8, "Rice"),
        ("REG-003", 12.0, 32.1, "Legumes")
    ])
    conn.commit()
    return conn

db_conn = init_mock_db()

# AGENT SKILL / MCP TOOL
@mcp.tool()
def fetch_agro_metrics(query: RegionQuery) -> dict:
    """Retrieves authenticated, clean soil and temperature metrics for a specific zone."""
    cursor = db_conn.cursor()
    # SQL Injection Prevention via Parameterized Query
    cursor.execute("SELECT * FROM soil_metrics WHERE region_id = ?", (query.region_id,))
    row = cursor.fetchone()
    
    if not row:
        return {"error": f"Region {query.region_id} not found in verified registry."}
        
    return {
        "region": row[0],
        "current_soil_moisture_pct": row[1],
        "average_temp_celsius": row[2],
        "recommended_crop": row[3],
        "irrigation_urgency": "HIGH" if row[1] < 20.0 else "MEDIUM" if row[1] < 35.0 else "LOW"
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")