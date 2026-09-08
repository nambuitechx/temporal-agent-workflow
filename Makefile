run:
	docker compose up -d --build

down:
	docker compose down

# Chạy Alembic migration trong container backend (đã có sqlalchemy/asyncpg/
# alembic qua pyproject.toml) — cần `make run` trước để postgres/backend đã
# lên (mục 8 bước 2 của docs/2026-09-08-generic-agent-loop-design.md).
migrate:
	docker compose exec backend alembic -c alembic.ini upgrade head

# Seed usecase incident_investigation + 3 agent (log_agent/metrics_agent/
# orchestrator) — idempotent, xem shared/db/seed.py (mục 8 bước 3).
seed:
	docker compose exec backend python -m shared.db.seed