import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker
from .db import Database
from .engine import Engine
from .providers import HttpGateway
from .workflows import RecoveryWorkflow

log = logging.getLogger("orderflow")
db = Database(os.environ["DATABASE_URL"])
engine = Engine(db, HttpGateway(os.environ["PROVIDER_URL"], os.environ["PROVIDER_TOKEN"]))
QUEUE = "orderflow-recovery"


@activity.defn(name="tick_order")
def tick_order(order_id: str) -> dict:
    return engine.tick(order_id)


def pending():
    with db.transaction() as s:
        return s.all("SELECT * FROM wakeups WHERE delivered=0 ORDER BY created_at LIMIT 100")


def delivered(ident):
    with db.transaction() as s:
        s.execute("UPDATE wakeups SET delivered=1 WHERE id=?", (ident,))


async def dispatch(client):
    while True:
        try:
            for event in await asyncio.to_thread(pending):
                try:
                    await client.start_workflow(RecoveryWorkflow.run, event["order_id"],
                        id="order-" + event["order_id"], task_queue=QUEUE,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        start_signal="wake", start_signal_args=[])
                except WorkflowAlreadyStartedError:
                    # A closed terminal workflow needs no further action.
                    pass
                await asyncio.to_thread(delivered, event["id"])
        except Exception:
            log.exception("Wakeup dispatch failed; durable outbox retained")
        await asyncio.sleep(2)


async def main():
    db.initialize()
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "temporal:7233"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        worker = Worker(client, task_queue=QUEUE, workflows=[RecoveryWorkflow],
                        activities=[tick_order], activity_executor=pool)
        await asyncio.gather(worker.run(), dispatch(client))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
