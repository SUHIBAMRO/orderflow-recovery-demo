import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class RecoveryWorkflow:
    def __init__(self):
        self.woken = False

    @workflow.signal
    def wake(self):
        self.woken = True

    @workflow.run
    async def run(self, order_id: str) -> dict:
        while True:
            self.woken = False
            state = await workflow.execute_activity(
                "tick_order", order_id, start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30), maximum_attempts=0))
            if state["status"] in {"COMPLETED", "ROADTAX_REFUNDED"}:
                return state
            delay = max(0, state["next_attempt"] - workflow.now().timestamp())
            if state["status"] in {"WAITING_PHOTOS", "WAITING_CORRECTION", "REFUND_REQUIRED", "MANUAL_REVIEW"}:
                # Periodic reconciliation makes delayed/lost UI wakeups harmless.
                try:
                    await workflow.wait_condition(lambda: self.woken, timeout=timedelta(seconds=30))
                except asyncio.TimeoutError:
                    pass
            elif delay:
                await workflow.sleep(timedelta(seconds=delay))
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(order_id)
