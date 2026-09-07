"""Fake Tool Layer — thay cho tool "RetrieveIncidentMetrics" thật. Xem
incident_logs.py để biết lý do thiết kế."""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "scenarios"


def get_incident_metrics(scenario_id: str) -> dict:
    path = DATA_DIR / scenario_id / "metrics.json"
    if not path.exists():
        return {
            "service": "unknown",
            "time_range": "unknown",
            "series": [],
            "note": f"Không có fake metrics cho scenario_id={scenario_id!r}",
        }
    return json.loads(path.read_text(encoding="utf-8"))
