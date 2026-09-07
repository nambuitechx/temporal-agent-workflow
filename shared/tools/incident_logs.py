"""Fake Tool Layer — thay cho tool "RetrieveIncidentLogs" thật (MCP/API).

Trong Xora Resolve thật, đây sẽ là 1 lời gọi qua Tool Gateway tới hệ thống log
(Datadog/ELK/...). Với POC, ta chỉ đọc sẵn 1 file JSON hardcode theo scenario_id,
nhưng vẫn giữ đúng hình dạng lời gọi (capability + input -> structured data) để
Specialized Agent phía trên không cần biết gì về việc dữ liệu tới từ đâu.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "scenarios"


def get_incident_logs(scenario_id: str) -> dict:
    path = DATA_DIR / scenario_id / "logs.json"
    if not path.exists():
        return {
            "service": "unknown",
            "time_range": "unknown",
            "entries": [],
            "note": f"Không có fake logs cho scenario_id={scenario_id!r}",
        }
    return json.loads(path.read_text(encoding="utf-8"))
