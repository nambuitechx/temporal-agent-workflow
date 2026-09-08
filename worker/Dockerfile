FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Cache layer riêng cho dependency resolve — chỉ invalidate khi pyproject/lock đổi.
COPY worker/pyproject.toml worker/uv.lock ./worker/
RUN cd worker && uv sync --frozen --no-install-project

COPY shared ./shared
COPY agents ./agents
COPY worker ./worker
COPY alembic.ini ./alembic.ini

ENV PATH="/app/worker/.venv/bin:${PATH}"
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "worker/main.py"]
