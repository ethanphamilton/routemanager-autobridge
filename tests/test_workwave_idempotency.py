"""Delivery-semantics tests for WorkwaveClient.

WorkWave has no server-side dedupe on addOrders, so the rule these tests
pin down is: retry only what provably never reached the queue; treat
everything else as unknown and resolve it by reading WorkWave back.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

from src.io.workwave_client import (
    AmbiguousBatchError,
    WorkwaveClient,
    ORDERS_PER_BATCH,
)
from src.models import OrderInput, ServiceType


def make_order(n: int) -> OrderInput:
    o = OrderInput(
        name=f"Customer {n}: Weekly",
        company="Example Spa Services",
        zoho_id=f"zoho-{n}",
        customer_phone="6155550000",
        auto_texting_phone="6155550000",
        service_street="1 Example Way",
        service_city="Asheville",
        service_state="NC",
        service_zip="28801",
        service_type=ServiceType.STANDARD,
        service_time=20,
        eligibility_start=date(2026, 10, 5),
        eligibility_end=date(2026, 10, 5),
        notes="",
        maintenance_frequency="Weekly",
        preferred_days="M",
    )
    o.run_id = "autobridge-2026-10"
    return o


def client(**kw) -> WorkwaveClient:
    return WorkwaveClient(api_key="k", territory_id="t", **kw)


def response(status, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


# --- ambiguous outcomes must never resend -------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        requests.ReadTimeout("read timed out"),
        requests.ConnectionError("connection reset mid-flight"),
        requests.RequestException("something else"),
    ],
)
def test_ambiguous_transport_errors_abort_without_resending(failure):
    c = client()
    c.session = MagicMock()
    c.session.post.side_effect = failure

    with pytest.raises(AmbiguousBatchError):
        c.submit_orders([make_order(1)], run_id="autobridge-2026-10")

    assert c.session.post.call_count == 1, "an unknown outcome must not be resent"


def test_5xx_aborts_without_resending():
    c = client()
    c.session = MagicMock()
    c.session.post.return_value = response(503, text="upstream unavailable")

    with pytest.raises(AmbiguousBatchError):
        c.submit_orders([make_order(1)], run_id="autobridge-2026-10")

    assert c.session.post.call_count == 1


# --- provably-unsent outcomes are still retried -------------------------


def test_connect_timeout_is_retried_then_succeeds():
    c = client()
    c.session = MagicMock()
    c.session.post.side_effect = [
        requests.ConnectTimeout("connect timed out"),
        response(200, {"requestId": "req-1"}),
    ]
    request_ids, failures, attempts = c.submit_orders([make_order(1)], run_id="autobridge-2026-10")
    assert request_ids == ["req-1"]
    assert attempts == [2] and not failures


def test_429_is_retried_then_succeeds():
    c = client()
    c.session = MagicMock()
    c.session.post.side_effect = [
        response(429, text="slow down"),
        response(200, {"requestId": "req-2"}),
    ]
    request_ids, _, attempts = c.submit_orders([make_order(1)], run_id="autobridge-2026-10")
    assert request_ids == ["req-2"] and attempts == [2]


def test_4xx_rejection_is_not_ambiguous_and_not_retried():
    c = client()
    c.session = MagicMock()
    c.session.post.return_value = response(400, text="bad payload")

    _, failures, _ = c.submit_orders([make_order(1)], run_id="autobridge-2026-10")

    assert c.session.post.call_count == 1
    assert len(failures) == 1, "a rejected batch is reported, not retried"


# --- abort stops the whole run ------------------------------------------


def test_ambiguous_batch_stops_later_batches():
    c = client()
    c.session = MagicMock()
    c.session.post.side_effect = [
        response(200, {"requestId": "req-1"}),
        requests.ReadTimeout("lost"),
    ]
    orders = [make_order(i) for i in range(ORDERS_PER_BATCH + 5)]

    with pytest.raises(AmbiguousBatchError):
        c.submit_orders(orders, run_id="autobridge-2026-10")

    assert c.session.post.call_count == 2, "must not submit past an unknown batch"


# --- the batch-level guard ----------------------------------------------


def _app_with_rows(rows):
    app = MagicMock()
    app.datastore.return_value.zcql.return_value.execute_zcql_query.return_value = rows
    app.datastore.return_value.table.return_value.insert_row.return_value = {"ROWID": "r1"}
    return app


def test_confirmed_batches_are_skipped_on_reinvocation():
    c = client(
        catalyst_app=_app_with_rows([{"RmRunSubmissions": {"batchNum": 1, "requestId": "req-1"}}])
    )
    c.session = MagicMock()
    c.session.post.return_value = response(200, {"requestId": "req-2"})
    orders = [make_order(i) for i in range(ORDERS_PER_BATCH + 5)]

    request_ids, _, _ = c.submit_orders(orders, run_id="autobridge-2026-10")

    assert c.session.post.call_count == 1, "batch 1 already landed; only batch 2 sent"
    assert request_ids == ["req-2"]


def test_unconfirmed_batch_blocks_all_submission():
    c = client(
        catalyst_app=_app_with_rows([{"RmRunSubmissions": {"batchNum": 1, "requestId": ""}}])
    )
    c.session = MagicMock()

    with pytest.raises(AmbiguousBatchError, match="unreconciled"):
        c.submit_orders([make_order(1)], run_id="autobridge-2026-10")

    c.session.post.assert_not_called()


def test_unreadable_ledger_fails_closed():
    app = MagicMock()
    app.datastore.return_value.zcql.return_value.execute_zcql_query.side_effect = RuntimeError(
        "datastore down"
    )
    c = client(catalyst_app=app)
    c.session = MagicMock()

    with pytest.raises(AmbiguousBatchError, match="ledger unreadable"):
        c.submit_orders([make_order(1)], run_id="autobridge-2026-10")

    c.session.post.assert_not_called()


def test_intent_is_recorded_before_the_post():
    calls = []
    app = _app_with_rows([])
    app.datastore.return_value.table.return_value.insert_row.side_effect = lambda row: calls.append(
        "intent"
    ) or {"ROWID": "r1"}
    c = client(catalyst_app=app)
    c.session = MagicMock()
    c.session.post.side_effect = lambda *a, **k: calls.append("post") or response(
        200, {"requestId": "req-1"}
    )
    c.submit_orders([make_order(1)], run_id="autobridge-2026-10")
    assert calls[:2] == ["intent", "post"], "intent must be durable before sending"


# --- reconciliation ------------------------------------------------------


def _wire(zoho_id, name, dates, service_type="Weekly", copied_from=None):
    fields = {
        "Zoho Id": zoho_id,
        "Service Type": service_type,
        "Autobridge Run": "autobridge-2026-10",
    }
    if copied_from:
        fields["Copied From"] = copied_from
    return {
        "name": name,
        "eligibility": {"onDates": list(dates)},
        "delivery": {"customFields": fields},
    }


def test_reconcile_returns_only_missing_orders():
    c = client()
    c.session = MagicMock()
    c.session.get.return_value = response(
        200,
        {
            "orders": {
                "a": _wire("zoho-0", "Customer 0: Weekly", ["20261005"]),
            }
        },
    )
    orders = [make_order(0), make_order(1)]
    missing, present = c.reconcile(orders, run_id="autobridge-2026-10")
    assert [o.zoho_id for o in missing] == ["zoho-1"]
    assert len(present) == 1


def test_reconcile_ignores_dispatcher_clones():
    """A clone inherits our run tag; treating it as ours would drop a real visit."""
    c = client()
    c.session = MagicMock()
    c.session.get.return_value = response(
        200,
        {
            "orders": {
                "clone": _wire(
                    "zoho-0",
                    "Customer 0: Install Filter",
                    ["20261005"],
                    copied_from="Customer 0: Weekly",
                ),
            }
        },
    )
    missing, present = c.reconcile([make_order(0)], run_id="autobridge-2026-10")
    assert [o.zoho_id for o in missing] == [
        "zoho-0"
    ], "the real weekly visit is still missing and must be submitted"
    assert present == []


def test_reconcile_ignores_other_runs():
    c = client()
    c.session = MagicMock()
    other = _wire("zoho-0", "Customer 0: Weekly", ["20261005"])
    other["delivery"]["customFields"]["Autobridge Run"] = "autobridge-2026-09"
    c.session.get.return_value = response(200, {"orders": {"x": other}})
    missing, _ = c.reconcile([make_order(0)], run_id="autobridge-2026-10")
    assert len(missing) == 1


def test_reconcile_counts_duplicates_rather_than_deduping():
    """Two legitimately identical visits must not collapse to one.

    A member whose eligibility is {"type": "any"} produces orders with no
    dates, so two distinct visits in a month serialize identically. If only
    one landed, the second is still missing and must be resubmitted.
    """
    c = client()
    c.session = MagicMock()
    c.session.get.return_value = response(
        200,
        {
            "orders": {
                "a": _wire("zoho-0", "Customer 0: Weekly", ["20261005"]),
            }
        },
    )
    intended = [make_order(0), make_order(0)]  # two identical visits
    missing, present = c.reconcile(intended, run_id="autobridge-2026-10")
    assert len(present) == 1
    assert len(missing) == 1, "one of the two identical visits still needs sending"


def test_reconcile_submits_nothing_when_both_duplicates_landed():
    c = client()
    c.session = MagicMock()
    c.session.get.return_value = response(
        200,
        {
            "orders": {
                "a": _wire("zoho-0", "Customer 0: Weekly", ["20261005"]),
                "b": _wire("zoho-0", "Customer 0: Weekly", ["20261005"]),
            }
        },
    )
    missing, _ = c.reconcile([make_order(0), make_order(0)], run_id="autobridge-2026-10")
    assert missing == []
