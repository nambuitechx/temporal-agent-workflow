"""Đăng ký Workflow + Activities, start Temporal Worker.

Chạy như 1 process/container riêng, KHÔNG expose HTTP — chỉ poll task queue
của Temporal. Tách biệt hoàn toàn khỏi Backend Server (xem README.md).
"""
import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from shared.activities import ask_orchestrator, get_usecase_limits, notify_human, run_agent
from shared.models import TASK_QUEUE
from shared.workflows import AgentLoopWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


async def _connect_with_retry(address: str, attempts: int = 30, delay: float = 2.0) -> Client:
    """Temporal server trong docker-compose có thể chưa sẵn sàng ngay —
    retry thay vì crash-loop container."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await Client.connect(address)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Kết nối Temporal thất bại (lần %d/%d): %s", attempt, attempts, exc)
            await asyncio.sleep(delay)
    raise RuntimeError(f"Không kết nối được Temporal tại {address}") from last_exc


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    client = await _connect_with_retry(address)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentLoopWorkflow],
        activities=[ask_orchestrator, run_agent, notify_human, get_usecase_limits],
    )
    logger.info("Worker đã kết nối Temporal tại %s, polling task queue %r", address, TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
