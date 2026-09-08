FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Cache layer riêng cho dependency resolve — chỉ invalidate khi pyproject/lock đổi.
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-install-project

COPY shared ./shared
COPY backend ./backend
COPY alembic.ini ./alembic.ini

ENV PATH="/app/backend/.venv/bin:${PATH}"
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
