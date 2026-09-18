"""WorkWave RouteManager API client.

`submit_orders()` is the only entry point for a normal run. `reconcile()`
resolves a run whose outcome is uncertain.

Delivery model
--------------
WorkWave's addOrders is asynchronous and has no server-side dedupe: a 2xx
means *queued*, not *applied*, and an identical resend creates a second set
of orders. HTTP status is therefore a proxy for the only question that
matters -- did this batch land? -- and the two disagree exactly when it
counts, on a lost response.

This client resolves that by never inferring the answer from a status code
it did not receive:

  1. A durable intent row is written to RmRunSubmissions BEFORE each POST,
     carrying the batch's zohoIds and an empty requestId. The real requestId
     is stamped on only after WorkWave acknowledges. An empty requestId is
     therefore an unambiguous "outcome unknown" marker that survives a
     crash, a timeout or a cold start.
  2. Only failures that provably never reached the queue are retried --
     HTTP 429 and a TCP connect timeout. A read timeout, a 5xx or any other
     transport error aborts the run with AmbiguousBatchError rather than
     resending.
  3. An unknown batch is resolved by reading WorkWave back and submitting
     only the difference (`reconcile`), which is safe because every order
     carries the run's unique `Autobridge Run` tag -- an idempotency key the
     vendor does not provide but this pipeline already emits.
  4. Re-entry into an already-submitted run is blocked by the same intent
     log: confirmed batches are skipped, and an unconfirmed one refuses all
     further submission until reconciled.

Orders created by cloning in the WorkWave UI inherit our customFields --
run tag included -- and are identified by a 'Copied From' field. They are
excluded everywhere, since treating one as our own would make a real order
look already-submitted and silently drop a customer visit.
"""

import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

from ..models import OrderInput
from ..utils import get_logger

logger = get_logger()

MAX_RETRIES = 5
ORDERS_PER_BATCH = 100

# A batch is only ever retried when we can prove the request never reached
# WorkWave's queue. Everything else is ambiguous and must be resolved by
# reading WorkWave back, never by resending -- WorkWave has no server-side
# dedupe on addOrders, so a blind resend of an ambiguous batch duplicates it.
#
#   429            -> rejected before queueing         -> safe
#   ConnectTimeout -> TCP connect never completed      -> safe
#   ReadTimeout    -> request sent, reply lost         -> AMBIGUOUS
#   5xx            -> server may have committed it     -> AMBIGUOUS
#   other network  -> may have dropped mid-flight      -> AMBIGUOUS
#
# requests.ConnectTimeout subclasses both ConnectionError and Timeout, so it
# must be tested before the broader classes.
SAFE_TO_RETRY_EXCEPTIONS = (requests.ConnectTimeout,)


class AmbiguousBatchError(Exception):
    """A batch's outcome could not be determined.

    Raised instead of retrying. The batch's intent row is already durable in
    RmRunSubmissions with an empty requestId, which is the signal that it
    needs reconciliation against WorkWave before anything else is sent.
    """

    def __init__(self, batch_num: int, reason: str):
        self.batch_num = batch_num
        self.reason = reason
        super().__init__(f"batch {batch_num} outcome unknown: {reason}")


class WorkwaveClient:
    BASE_URL = "https://wwrm.workwave.com/api/v1"

    def __init__(self, api_key: str, territory_id: str, catalyst_app=None):
        self.territory_id = territory_id
        self.catalyst_app = catalyst_app
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-WorkWave-Key": api_key,
                "Content-Type": "application/json",
            }
        )

    def submit_orders(
        self,
        orders: List[OrderInput],
        *,
        run_id: str,
    ) -> Tuple[List[str], List[dict], List[int]]:
        """Submit orders to WorkWave in batches of up to ORDERS_PER_BATCH.

        Args:
            orders: Orders to submit. Must already carry run_id via OrderGenerator.
            run_id: Autobridge run identifier; tagged into Datastore submission
                rows and every log record produced by this call.

        Returns:
            (request_ids, failed_orders, attempts_per_batch)
              request_ids: WorkWave requestId UUID per successful batch POST.
              failed_orders: Error dicts for orders whose batch exhausted retries.
              attempts_per_batch: 1-indexed list of HTTP attempt counts per batch,
                aligned with batches in submission order. Used by the run summary.
        """
        if not run_id:
            raise ValueError("WorkwaveClient.submit_orders: run_id must be non-empty")

        if not orders:
            return [], [], []

        request_ids: List[str] = []
        failed_orders: List[dict] = []
        attempts_per_batch: List[int] = []

        total_batches = (len(orders) + ORDERS_PER_BATCH - 1) // ORDERS_PER_BATCH

        # Batch-level guard. A re-invocation of a run that already submitted
        # (Catalyst redelivering the cron, an operator re-trigger, a resumed
        # partial run) must not resend. Confirmed batches are skipped; an
        # unconfirmed batch means a previous attempt's outcome is unknown and
        # nothing may be sent until it is reconciled against WorkWave.
        confirmed_batches, unconfirmed_batches = self._submitted_batches(run_id)
        if unconfirmed_batches:
            raise AmbiguousBatchError(
                sorted(unconfirmed_batches)[0],
                f"run {run_id} has unreconciled batch(es) "
                f"{sorted(unconfirmed_batches)} from a previous attempt; "
                f"reconcile against WorkWave before submitting anything further",
            )
        if confirmed_batches:
            logger.warning(
                f"WorkWave: run {run_id} already has {len(confirmed_batches)} "
                f"confirmed batch(es) {sorted(confirmed_batches)} — skipping those",
                extra={
                    "event": "workwave.guard.resume",
                    "fields": {
                        "run_id": run_id,
                        "confirmed_batches": sorted(confirmed_batches),
                        "total_batches": total_batches,
                    },
                },
            )

        logger.info(
            f"WorkWave: starting submission — {len(orders)} orders, {total_batches} batch(es)",
            extra={
                "event": "workwave.submit.start",
                "fields": {
                    "run_id": run_id,
                    "order_count": len(orders),
                    "batch_count": total_batches,
                    "max_retries": MAX_RETRIES,
                    "batch_size": ORDERS_PER_BATCH,
                },
            },
        )

        for batch_num, batch_start in enumerate(range(0, len(orders), ORDERS_PER_BATCH), start=1):
            batch = orders[batch_start : batch_start + ORDERS_PER_BATCH]

            if batch_num in confirmed_batches:
                logger.info(
                    f"WorkWave: batch {batch_num} already confirmed for {run_id} — skipping",
                    extra={
                        "event": "workwave.batch.skipped",
                        "fields": {
                            "run_id": run_id,
                            "batch_num": batch_num,
                            "order_count": len(batch),
                        },
                    },
                )
                continue

            try:
                intent_row = self._record_intent(run_id=run_id, batch_num=batch_num, batch=batch)
                request_id, attempts = self._post_with_retry(
                    batch,
                    batch_num=batch_num,
                    run_id=run_id,
                )
                self._confirm_intent(
                    intent_row,
                    request_id=request_id,
                    run_id=run_id,
                    batch_num=batch_num,
                )
                request_ids.append(request_id)
                attempts_per_batch.append(attempts)
                logger.info(
                    f"WorkWave: batch {batch_num} accepted — {len(batch)} orders, "
                    f"requestId={request_id}, attempts={attempts}",
                    extra={
                        "event": "workwave.batch.accepted",
                        "fields": {
                            "run_id": run_id,
                            "batch_num": batch_num,
                            "order_count": len(batch),
                            "request_id": request_id,
                            "attempts": attempts,
                        },
                    },
                )
            except AmbiguousBatchError:
                # Do not continue to later batches: WorkWave processes a
                # territory's queue FIFO, so submitting more on top of an
                # unresolved batch makes the reconciliation harder, not easier.
                logger.error(
                    f"WorkWave: batch {batch_num} outcome unknown — aborting run {run_id}. "
                    f"{len(request_ids)} batch(es) confirmed before this point. "
                    f"Reconcile against WorkWave before re-running.",
                    extra={
                        "event": "workwave.run.aborted",
                        "fields": {
                            "run_id": run_id,
                            "batch_num": batch_num,
                            "confirmed_batches": len(request_ids),
                        },
                    },
                )
                raise

            except Exception as exc:
                attempts_per_batch.append(MAX_RETRIES)
                logger.error(
                    f"WorkWave: batch {batch_num} rejected: {exc}",
                    extra={
                        "event": "workwave.batch.failed",
                        "fields": {
                            "run_id": run_id,
                            "batch_num": batch_num,
                            "order_count": len(batch),
                            "error": str(exc),
                        },
                    },
                )
                for order in batch:
                    failed_orders.append(
                        {
                            "Property Name": order.name,
                            "Record Id": order.zoho_id,
                            "Error Reason": f"WorkWave submission failed: {exc}",
                        }
                    )

        return request_ids, failed_orders, attempts_per_batch

    def _post_with_retry(
        self,
        orders: List[OrderInput],
        *,
        batch_num: int,
        run_id: str,
    ) -> Tuple[str, int]:
        """POST a single batch with exponential backoff on 429 / 5xx / network.

        Returns:
            (request_id, attempt_count) on success.

        Raises:
            RuntimeError after MAX_RETRIES exhausted attempts.
        """
        url = f"{self.BASE_URL}/territories/{self.territory_id}/orders"
        payload = {
            "orders": [o.to_dict() for o in orders],
            "strict": False,
            "acceptBadGeocodes": False,
        }
        zoho_ids = [o.zoho_id for o in orders]
        backoff = 1.0

        for attempt in range(1, MAX_RETRIES + 1):
            attempt_started = time.monotonic()
            logger.info(
                f"WorkWave: batch {batch_num} attempt {attempt} POST {url}",
                extra={
                    "event": "workwave.attempt.start",
                    "fields": {
                        "run_id": run_id,
                        "batch_num": batch_num,
                        "attempt": attempt,
                        "order_count": len(orders),
                        "zoho_ids": zoho_ids,
                        "url": url,
                    },
                },
            )

            try:
                resp = self.session.post(url, json=payload, timeout=30)
                duration_ms = int((time.monotonic() - attempt_started) * 1000)

                if resp.status_code == 429:
                    if attempt == MAX_RETRIES:
                        self._log_terminal(
                            batch_num,
                            attempt,
                            run_id,
                            status_code=429,
                            response_text=resp.text,
                            duration_ms=duration_ms,
                            error_class="RateLimited",
                            error_message="HTTP 429 after max retries",
                        )
                        raise RuntimeError(f"Rate limited (HTTP 429) after {MAX_RETRIES} attempts")
                    self._log_retry(
                        batch_num,
                        attempt,
                        run_id,
                        status_code=429,
                        response_text=resp.text,
                        duration_ms=duration_ms,
                        error_class="RateLimited",
                        error_message="HTTP 429",
                        retry_in_sec=backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if resp.status_code >= 500:
                    # AMBIGUOUS: WorkWave may have committed the batch before
                    # failing to respond. Resending would duplicate it.
                    self._log_terminal(
                        batch_num,
                        attempt,
                        run_id,
                        status_code=resp.status_code,
                        response_text=resp.text,
                        duration_ms=duration_ms,
                        error_class="ServerError",
                        error_message=f"HTTP {resp.status_code} - outcome unknown, not retrying",
                    )
                    raise AmbiguousBatchError(
                        batch_num, f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )

                # 4xx other than 429: a rejection, nothing was queued.
                if 400 <= resp.status_code < 500:
                    self._log_terminal(
                        batch_num,
                        attempt,
                        run_id,
                        status_code=resp.status_code,
                        response_text=resp.text,
                        duration_ms=duration_ms,
                        error_class="ClientError",
                        error_message=f"HTTP {resp.status_code} - rejected, nothing queued",
                    )
                    raise RuntimeError(
                        f"WorkWave rejected batch {batch_num} "
                        f"(HTTP {resp.status_code}): {resp.text[:200]}"
                    )

                request_id = resp.json()["requestId"]
                logger.info(
                    f"WorkWave: batch {batch_num} attempt {attempt} OK "
                    f"({duration_ms} ms) requestId={request_id}",
                    extra={
                        "event": "workwave.attempt.success",
                        "fields": {
                            "run_id": run_id,
                            "batch_num": batch_num,
                            "attempt": attempt,
                            "status_code": resp.status_code,
                            "request_id": request_id,
                            "duration_ms": duration_ms,
                        },
                    },
                )
                return request_id, attempt

            except requests.RequestException as exc:
                duration_ms = int((time.monotonic() - attempt_started) * 1000)

                if not isinstance(exc, SAFE_TO_RETRY_EXCEPTIONS):
                    # The request may have been delivered and applied. Stop.
                    self._log_terminal(
                        batch_num,
                        attempt,
                        run_id,
                        status_code=None,
                        response_text="",
                        duration_ms=duration_ms,
                        error_class=type(exc).__name__,
                        error_message=f"{exc} - outcome unknown, not retrying",
                    )
                    raise AmbiguousBatchError(batch_num, f"{type(exc).__name__}: {exc}")

                # Provably never reached the queue (TCP connect timed out).
                if attempt == MAX_RETRIES:
                    self._log_terminal(
                        batch_num,
                        attempt,
                        run_id,
                        status_code=None,
                        response_text="",
                        duration_ms=duration_ms,
                        error_class=type(exc).__name__,
                        error_message=str(exc),
                    )
                    raise RuntimeError(f"Could not connect after {MAX_RETRIES} attempts: {exc}")
                self._log_retry(
                    batch_num,
                    attempt,
                    run_id,
                    status_code=None,
                    response_text="",
                    duration_ms=duration_ms,
                    error_class=type(exc).__name__,
                    error_message=str(exc),
                    retry_in_sec=backoff,
                )
                time.sleep(backoff)
                backoff *= 2

        raise RuntimeError("Exhausted all retries")

    @staticmethod
    def _log_retry(
        batch_num: int,
        attempt: int,
        run_id: str,
        *,
        status_code: Optional[int],
        response_text: str,
        duration_ms: int,
        error_class: str,
        error_message: str,
        retry_in_sec: float,
    ) -> None:
        logger.warning(
            f"WorkWave: batch {batch_num} attempt {attempt} FAILED "
            f"{error_class}: {error_message} — retrying in {retry_in_sec:.0f}s",
            extra={
                "event": "workwave.attempt.retry",
                "fields": {
                    "run_id": run_id,
                    "batch_num": batch_num,
                    "attempt": attempt,
                    "status_code": status_code,
                    "error_class": error_class,
                    "error_message": error_message,
                    "response_snippet": response_text[:500],
                    "duration_ms": duration_ms,
                    "retry_in_sec": retry_in_sec,
                },
            },
        )

    @staticmethod
    def _log_terminal(
        batch_num: int,
        attempt: int,
        run_id: str,
        *,
        status_code: Optional[int],
        response_text: str,
        duration_ms: int,
        error_class: str,
        error_message: str,
    ) -> None:
        logger.error(
            f"WorkWave: batch {batch_num} attempt {attempt} TERMINAL "
            f"{error_class}: {error_message}",
            extra={
                "event": "workwave.attempt.failed",
                "fields": {
                    "run_id": run_id,
                    "batch_num": batch_num,
                    "attempt": attempt,
                    "status_code": status_code,
                    "error_class": error_class,
                    "error_message": error_message,
                    "response_snippet": response_text[:500],
                    "duration_ms": duration_ms,
                },
            },
        )

    # ------------------------------------------------------------------
    # Durable intent log (RmRunSubmissions)
    #
    # A row is written BEFORE the POST with an empty requestId, and stamped
    # with the real requestId only once WorkWave has acknowledged it. So:
    #
    #   requestId non-empty -> batch definitely reached the queue
    #   requestId empty     -> outcome unknown, needs reconciliation
    #
    # This needs no schema change to the existing table.
    # ------------------------------------------------------------------

    def _record_intent(self, *, run_id: str, batch_num: int, batch: List[OrderInput]):
        """Persist the intent to submit a batch. Returns the row id, or None.

        Written before the POST so an unknown outcome is always recoverable.
        A failure here aborts the batch: without a durable intent row we
        cannot safely distinguish 'never sent' from 'sent and lost'.
        """
        if self.catalyst_app is None:
            return None
        row = {
            "requestId": "",
            "runId": run_id,
            "batchNum": batch_num,
            "orderCount": len(batch),
            "zohoIds": json.dumps([o.zoho_id for o in batch]),
            "submittedAt": datetime.now(timezone.utc).isoformat(),
        }
        table = self.catalyst_app.datastore().table("RmRunSubmissions")
        inserted = table.insert_row(row)
        row_id = (inserted or {}).get("ROWID")
        logger.info(
            f"WorkWave: batch {batch_num} intent recorded (row {row_id})",
            extra={
                "event": "workwave.intent.recorded",
                "fields": {
                    "run_id": run_id,
                    "batch_num": batch_num,
                    "row_id": row_id,
                    "order_count": len(batch),
                },
            },
        )
        return row_id

    def _confirm_intent(self, row_id, *, request_id: str, run_id: str, batch_num: int) -> None:
        """Stamp the real requestId onto an intent row once WorkWave accepted it."""
        if self.catalyst_app is None or row_id is None:
            return
        try:
            table = self.catalyst_app.datastore().table("RmRunSubmissions")
            table.update_row({"ROWID": row_id, "requestId": request_id})
        except Exception as exc:
            # The batch DID land; we just failed to record that. Surfaces later
            # as an unconfirmed row and gets resolved by reconciliation, which
            # is safe -- reconciliation reads WorkWave rather than resending.
            logger.error(
                f"WorkWave: failed to confirm intent row {row_id} for batch {batch_num}: {exc}",
                extra={
                    "event": "workwave.intent.confirm_failed",
                    "fields": {
                        "run_id": run_id,
                        "batch_num": batch_num,
                        "row_id": row_id,
                        "request_id": request_id,
                        "error_message": str(exc),
                    },
                },
                exc_info=True,
            )

    def _submitted_batches(self, run_id: str) -> Tuple[set, set]:
        """Return (confirmed_batch_nums, unconfirmed_batch_nums) for a run.

        This is the batch-level guard: a re-invocation of an already-submitted
        run sees its own prior intent rows and refuses to resend them.
        """
        if self.catalyst_app is None:
            return set(), set()
        confirmed, unconfirmed = set(), set()
        try:
            zcql = self.catalyst_app.datastore().zcql()
            safe = run_id.replace("'", "''")
            rows = (
                zcql.execute_zcql_query(
                    f"SELECT batchNum, requestId FROM RmRunSubmissions WHERE runId = '{safe}'"
                )
                or []
            )
            for r in rows:
                row = r.get("RmRunSubmissions", r)
                try:
                    bn = int(row.get("batchNum"))
                except (TypeError, ValueError):
                    continue
                (confirmed if row.get("requestId") else unconfirmed).add(bn)
        except Exception as exc:
            # Fail closed: if we cannot read our own ledger we cannot prove a
            # batch has not already been sent, so refuse to submit.
            raise AmbiguousBatchError(0, f"ledger unreadable, refusing to submit: {exc}")
        return confirmed, unconfirmed

    def fetch_run_orders(self, run_id: str) -> List[dict]:
        """Read back the orders WorkWave actually holds for this run.

        Excludes orders carrying a 'Copied From' custom field: those are
        clones a dispatcher made in the WorkWave UI, which inherit our
        customFields (run tag included) but are not ours. Matching against
        them would make a real order look already-submitted and silently
        drop a customer visit.
        """
        url = f"{self.BASE_URL}/territories/{self.territory_id}/orders"
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()
        orders = (resp.json() or {}).get("orders", {}) or {}
        out = []
        for order in orders.values():
            fields = {}
            for step in ("pickup", "delivery"):
                candidate = order.get(step)
                if isinstance(candidate, dict) and isinstance(candidate.get("customFields"), dict):
                    fields = candidate["customFields"]
                    break
            if fields.get("Autobridge Run") != run_id:
                continue
            if fields.get("Copied From"):
                continue
            out.append(order)
        return out

    @staticmethod
    def order_identity(order: dict) -> tuple:
        """Business key for an order as WorkWave returns it."""
        fields = {}
        for step in ("pickup", "delivery"):
            candidate = order.get(step)
            if isinstance(candidate, dict) and isinstance(candidate.get("customFields"), dict):
                fields = candidate["customFields"]
                break
        dates = tuple((order.get("eligibility") or {}).get("onDates") or [])
        return (fields.get("Zoho Id"), fields.get("Service Type"), order.get("name"), dates)

    @staticmethod
    def input_identity(order: OrderInput) -> tuple:
        """Same business key, computed from an outgoing OrderInput."""
        payload = order.to_dict()
        dates = tuple((payload.get("eligibility") or {}).get("onDates") or [])
        return (order.zoho_id, order.service_type.value, order.name, dates)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(
        self, orders: List[OrderInput], *, run_id: str
    ) -> Tuple[List[OrderInput], List[dict]]:
        """Compare intended orders against what WorkWave actually holds.

        Returns (missing, present) — `missing` are the orders that still need
        submitting, `present` are the WorkWave orders already there for this
        run. This is how an unknown batch is resolved: read the authoritative
        system, then send only the difference. Never resend blind.

        Because `run_id` is unique per run and dispatcher clones are excluded
        by `Copied From`, everything returned by fetch_run_orders() for a
        fresh run is something this pipeline created.
        """
        present = self.fetch_run_orders(run_id)

        # Multiset, not set. An order whose eligibility is {"type": "any"}
        # carries no dates, so two legitimately distinct visits in the same
        # month serialize identically and differ only by the id WorkWave
        # assigns. Set membership would treat the second as already-present
        # and silently drop a visit, so compare counts and submit the deficit.
        landed = Counter(self.order_identity(o) for o in present)
        missing = []
        for order in orders:
            identity = self.input_identity(order)
            if landed.get(identity, 0) > 0:
                landed[identity] -= 1
            else:
                missing.append(order)
        logger.info(
            f"WorkWave: reconcile {run_id} — {len(orders)} intended, "
            f"{len(present)} already in WorkWave, {len(missing)} missing",
            extra={
                "event": "workwave.reconcile",
                "fields": {
                    "run_id": run_id,
                    "intended": len(orders),
                    "present": len(present),
                    "missing": len(missing),
                },
            },
        )
        return missing, present
