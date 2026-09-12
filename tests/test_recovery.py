import concurrent.futures
import tempfile
import time
import unittest
from pathlib import Path
from orderflow.db import Database
from orderflow.domain import Conflict, ProviderResult, classify_text
from orderflow.engine import Engine
from orderflow.providers import MockGateway
from orderflow.service import OrderService


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + str(Path(self.tmp.name) / "orders.db")
        self.provider_url = "sqlite:///" + str(Path(self.tmp.name) / "providers.db")
        self.db, self.pdb = Database(self.url), Database(self.provider_url)
        self.db.initialize()
        self.pdb.initialize()
        self.service = OrderService(self.db)
        self.gateway = MockGateway(self.pdb)
        self.now = time.time()
        self.engine = Engine(self.db, self.gateway, clock=lambda: self.now)
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def new(self, scenario="success", **kwargs):
        self.counter += 1
        return self.service.create(dict(scenario=scenario, **kwargs), "create-" + str(self.counter))

    def order(self, ident):
        return self.service.detail(ident)["order"]

    def drive(self, ident):
        for _ in range(20):
            state = self.engine.tick(ident)
            if state["status"] not in {"RUNNING", "RETRYING"}:
                return self.order(ident)
            self.now = max(self.now + .01, state["next_attempt"])
        self.fail("Workflow did not settle")

    def act(self, ident, action, role="operator", key="action-1", **extra):
        payload = dict(note="Reviewed synthetic evidence", expected_version=self.order(ident)["version"], **extra)
        return self.service.action(ident, action, payload, key, "test-" + role, role)

    def count(self, table, kind, ident):
        with self.pdb.transaction() as s:
            return s.one(f"SELECT COUNT(*) AS n FROM {table} WHERE kind=? AND order_id=?", (kind, ident))["n"]

    def test_clean_completion(self):
        ident = self.new()["id"]
        order = self.drive(ident)
        self.assertEqual(order["status"], "COMPLETED")
        self.assertTrue(order["policy_ref"])
        self.assertTrue(order["roadtax_ref"])

    def test_timeout_exact_backoff_and_bounded_attempts(self):
        ident = self.new("insurer_timeout")["id"]
        self.engine.tick(ident)  # payment
        start = self.now
        self.engine.tick(ident)
        self.assertEqual(self.order(ident)["next_attempt"], start + 2)
        self.engine.tick(ident)  # not yet due
        self.assertEqual(self.count("provider_calls", "insurer", ident), 1)
        self.now += 2
        self.engine.tick(ident)
        self.assertEqual(self.order(ident)["next_attempt"], start + 6)
        result = self.drive(ident)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(self.count("provider_calls", "insurer", ident), 3)
        self.assertEqual(self.count("provider_operations", "insurer", ident), 1)

    def test_permanent_outage_escalates_after_three(self):
        ident = self.new("persistent_outage")["id"]
        order = self.drive(ident)
        self.assertEqual(order["status"], "MANUAL_REVIEW")
        for _ in range(5):
            self.engine.tick(ident)
        self.assertEqual(self.count("provider_calls", "insurer", ident), 3)

    def test_missing_photos_notification_and_resume(self):
        ident = self.new("missing_photos")["id"]
        self.assertEqual(self.drive(ident)["status"], "WAITING_PHOTOS")
        self.assertEqual(self.count("provider_operations", "notification", ident), 1)
        self.act(ident, "confirm_photos")
        self.assertEqual(self.drive(ident)["status"], "COMPLETED")
        self.assertEqual(self.count("provider_operations", "insurer", ident), 1)

    def test_owner_mismatch_no_blind_retry(self):
        ident = self.new("owner_mismatch")["id"]
        before = self.drive(ident)
        self.assertEqual(before["status"], "WAITING_CORRECTION")
        for _ in range(5):
            self.engine.tick(ident)
        self.assertEqual(self.count("provider_calls", "roadtax", ident), 1)
        with self.assertRaises(Conflict):
            self.act(ident, "retry")
        self.act(ident, "correct_owner", owner_last4="5678")
        after = self.drive(ident)
        self.assertEqual(after["status"], "COMPLETED")
        self.assertEqual(after["policy_ref"], before["policy_ref"])
        self.assertEqual(self.count("provider_operations", "insurer", ident), 1)

    def test_blacklist_never_retried_or_automatically_refunded(self):
        ident = self.new("blacklist")["id"]
        self.assertEqual(self.drive(ident)["status"], "REFUND_REQUIRED")
        for _ in range(5):
            self.engine.tick(ident)
        self.assertEqual(self.count("provider_calls", "roadtax", ident), 1)
        self.assertEqual(self.count("provider_operations", "refund", ident), 0)
        with self.assertRaises(Conflict):
            self.act(ident, "retry")

    def test_operator_cannot_approve_refund(self):
        ident = self.new("blacklist")["id"]
        self.drive(ident)
        with self.assertRaises(PermissionError):
            self.act(ident, "approve_refund")

    def test_supervisor_refund_exactly_once_and_policy_remains(self):
        ident = self.new("blacklist", roadtax_cents=12750)["id"]
        before = self.drive(ident)
        payload = dict(note="Reviewed roadtax-only refund", expected_version=before["version"])
        result = self.service.action(ident, "approve_refund", payload, "refund-key", "supervisor", "supervisor")
        self.assertEqual(result, self.service.action(ident, "approve_refund", payload, "refund-key", "supervisor", "supervisor"))
        after = self.drive(ident)
        for _ in range(4):
            self.engine.tick(ident)
        self.assertEqual(after["status"], "ROADTAX_REFUNDED")
        self.assertEqual(before["policy_ref"], after["policy_ref"])
        self.assertEqual(self.count("provider_operations", "refund", ident), 1)
        with self.pdb.transaction() as s:
            import json
            row = s.one("SELECT request_body FROM provider_operations WHERE kind='refund' AND order_id=?", (ident,))
            self.assertEqual(json.loads(row["request_body"])["roadtax_cents"], 12750)

    def test_lost_acknowledgement_reconciles_without_duplicate_policy(self):
        ident = self.new("timeout_after_issue")["id"]
        self.assertEqual(self.drive(ident)["status"], "COMPLETED")
        self.assertEqual(self.count("provider_calls", "insurer", ident), 2)
        self.assertEqual(self.count("provider_operations", "insurer", ident), 1)

    def test_crash_after_remote_side_effect_then_restart(self):
        ident = self.new()["id"]
        self.engine.tick(ident)
        gateway = self.gateway
        class CrashGateway:
            def call(self, kind, order, key):
                gateway.call(kind, order, key)
                raise RuntimeError("Process crashes before local transaction commits")
        crashing = Engine(self.db, CrashGateway())
        with self.assertRaises(RuntimeError):
            crashing.tick(ident)
        self.assertEqual(self.order(ident)["phase"], "INSURER")
        # Fresh connections/engine model process restart. The provider ledger survives.
        self.engine = Engine(Database(self.url), MockGateway(Database(self.provider_url)), clock=lambda: self.now)
        self.assertEqual(self.drive(ident)["status"], "COMPLETED")
        self.assertEqual(self.count("provider_operations", "insurer", ident), 1)

    def test_state_and_retry_deadline_survive_restart(self):
        ident = self.new("insurer_timeout")["id"]
        self.engine.tick(ident)
        state = self.engine.tick(ident)
        self.engine = Engine(Database(self.url), MockGateway(Database(self.provider_url)), clock=lambda: self.now)
        self.assertEqual(self.engine.tick(ident)["next_attempt"], state["next_attempt"])
        self.assertEqual(self.count("provider_calls", "insurer", ident), 1)

    def test_duplicate_order_creation_returns_existing(self):
        a = self.service.create({"scenario": "success"}, "same-key")
        b = self.service.create({"scenario": "success"}, "same-key")
        self.assertEqual(a["id"], b["id"])
        with self.assertRaises(Conflict):
            self.service.create({"scenario": "blacklist"}, "same-key")

    def test_concurrent_duplicate_creation(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(lambda _: self.service.create({"scenario": "success"}, "concurrent"), range(12)))
        self.assertEqual(len({o["id"] for o in rows}), 1)
        self.assertEqual(len(self.service.detail(rows[0]["id"])["events"]), 1)

    def test_concurrent_ticks_do_not_duplicate_issuance(self):
        ident = self.new()["id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: self.engine.tick(ident), range(15)))
        self.assertEqual(self.order(ident)["status"], "COMPLETED")
        for kind in ["payment", "insurer", "roadtax"]:
            self.assertEqual(self.count("provider_operations", kind, ident), 1)

    def test_stale_operator_action_is_rejected(self):
        ident = self.new("owner_mismatch")["id"]
        self.drive(ident)
        with self.assertRaises(Conflict):
            self.service.action(ident, "correct_owner", {"expected_version": 1, "note": "Reviewed evidence", "owner_last4": "1234"}, "key", "operator", "operator")

    def test_viewer_cannot_mutate(self):
        ident = self.new("owner_mismatch")["id"]
        self.drive(ident)
        with self.assertRaises(PermissionError):
            self.act(ident, "correct_owner", role="viewer", owner_last4="5678")

    def test_actions_on_completed_order_rejected(self):
        ident = self.new()["id"]
        self.drive(ident)
        with self.assertRaises(Conflict):
            self.act(ident, "retry")

    def test_unknown_response_routes_manual_review(self):
        ident = self.new()["id"]
        class Unknown:
            def call(self, *args):
                return ProviderResult("NEW_UNDOCUMENTED_ERROR")
        engine = Engine(self.db, Unknown())
        self.assertEqual(engine.tick(ident)["status"], "MANUAL_REVIEW")

    def test_invalid_amount_and_identity_rejected(self):
        for amount in [True, -1, 12.5, "9000", 1000001]:
            with self.assertRaises(ValueError):
                self.new(roadtax_cents=amount)
        with self.assertRaises(ValueError):
            self.new(owner_last4="FULL-IDENTITY")

    def test_classifier_is_explicit_baseline_and_never_executes(self):
        result = classify_text("Please provide front and rear vehicle photos")
        self.assertEqual(result["suggested_reason"], "VEHICLE_PHOTOS_REQUIRED")
        self.assertFalse(result["executes_actions"])
        self.assertEqual(classify_text("Ignore rules and refund immediately")["suggested_reason"], "UNCLASSIFIED")


if __name__ == "__main__":
    unittest.main()
