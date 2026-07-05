import tempfile
from pathlib import Path
from unittest.mock import patch

from agro_agent import plan_history
from agro_agent.farms import create_farm, delete_farm


def test_plan_history_save_and_prune():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with patch("agro_agent.farms.get_settings") as mock_settings:
            from agro_agent.config import Settings

            settings = Settings(custom_farms_db_path=db_path)
            mock_settings.return_value = settings

            farm = create_farm(
                name="Test Farm",
                crop="Maize",
                latitude=20.0,
                longitude=80.0,
                radius_m=500.0,
            )
            region_id = farm["region_id"]

            for i in range(12):
                plan_history.save_plan_run(
                    region_id,
                    urgency="MEDIUM",
                    crop="Maize",
                    latitude=20.0,
                    longitude=80.0,
                    reasoning=f"Run {i}",
                    user_prompt="test",
                )

            runs = plan_history.list_plan_runs(region_id)
            assert len(runs) == plan_history.MAX_PLAN_HISTORY

            delete_farm(region_id)
            assert plan_history.list_plan_runs(region_id) == []
