"""Catalyst HTTP function: receives WorkWave RouteManager callbacks.

WorkWave Route Manager is asynchronous. POST /api/v1/territories/{tid}/orders
returns a `requestId` immediately and queues the work. When processing
completes (or fails), WorkWave POSTs to the callback URL we register via
`POST /api/v1/callback`. The body carries `requestId`, `territoryId`,
`event` (e.g. "ordersChanged"), and `data` describing what changed.

This handler:
  1. Verifies WorkWave's HMAC-SHA256 signature appended to the callback URL.
  2. Parses the `event` + `data` payload.
  3. Joins to RmRunSubmissions by `requestId` to recover our `runId`.
  4. Inserts a row into RmRunCallbacks with counts derived from `data`
     plus the full raw payload for forensic replay.
  5. Returns 200 on success. Returns 500 on persistence failure so
     WorkWave retries (per docs: 5 retries at 20, 40, 60, 80, 100s).

WorkWave signature scheme (verified via api docs):
  - On callback registration, we provide `signaturePassword` to WorkWave.
  - On every callback POST, WorkWave appends `nonce` and `signature` query
    params to the URL. `signature` = base64(HmacSHA256(urlWithoutSignature,
    signaturePassword)), where urlWithoutSignature is the full request URL
    with the `signature` param removed (nonce stays).

Required env vars:
  CALLBACK_SHARED_SECRET — same string passed to WorkWave as
                           `signaturePassword` when registering the URL.

Open items (still uncertain — adjust if WorkWave behavior differs):
  - Exact event name for addOrders. Inferred as "ordersChanged" from the
    documented `<resource>Changed` pattern (companiesChanged,
    territoryChanged, depotsChanged, etc.). Verify on first live callback.
  - Shape of `data` for failed inserts. We log the full payload, so
    forensics are intact; derived counts may need adjustment.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime, timezone

from flask import Request, jsonify, make_response

sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(
        logging.Formatter(
            "%(asctime)s - rm_callback - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(_h)

SECRET_ENV = "CALLBACK_SHARED_SECRET"


def _respond(status_code: int, body: dict):
    return make_response(jsonify(body), status_code)


def _verify_signature(request: Request) -> bool:
    """Verify WorkWave's HMAC-SHA256 callback signature.

    signature = base64(HmacSHA256(urlWithoutSignature, signaturePassword))
    """
    password = os.getenv(SECRET_ENV, "")
    if not password:
        logger.error(f"rm_callback: {SECRET_ENV} not set — rejecting all callers")
        return False

    parsed = urllib.parse.urlparse(request.url)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

    provided_signature = None
    remaining = []
    for k, v in query_pairs:
        if k == "signature":
            provided_signature = v
        else:
            remaining.append((k, v))

    if not provided_signature:
        logger.warning("rm_callback: no signature query param")
        return False

    # Catalyst sits behind a TLS-terminating proxy: request.url often shows
    # http:// and the internal host, while WorkWave signed the public https://
    # URL. Try several scheme/host combinations and accept if any matches.
    xf_proto = request.headers.get("X-Forwarded-Proto")
    xf_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
    query_str = urllib.parse.urlencode(remaining)

    candidates = set()
    for scheme in (parsed.scheme, xf_proto, "https", "http"):
        if not scheme:
            continue
        for netloc in (parsed.netloc, xf_host):
            if not netloc:
                continue
            candidates.add(
                urllib.parse.urlunparse(
                    (scheme, netloc, parsed.path, parsed.params, query_str, parsed.fragment)
                )
            )

    for candidate in candidates:
        computed = base64.b64encode(
            hmac.new(
                password.encode("utf-8"),
                candidate.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        if hmac.compare_digest(computed, provided_signature):
            return True

    logger.warning(
        f"rm_callback: signature mismatch (tried {len(candidates)} URL forms); "
        f"request.url={request.url!r} xf_proto={xf_proto!r} xf_host={xf_host!r}"
    )
    return False


def _lookup_run_id(app, request_id: str):
    """Find runId in RmRunSubmissions by requestId. Returns None on miss."""
    try:
        ds = app.datastore()
        zcql = ds.zcql()
        # Single-quote in ZCQL — requestId is a UUID so injection risk is bounded,
        # but escape any embedded quotes defensively.
        safe_id = request_id.replace("'", "''")
        result = zcql.execute_zcql_query(
            f"SELECT runId FROM RmRunSubmissions WHERE requestId = '{safe_id}' LIMIT 1"
        )
        if result and len(result) > 0:
            row = result[0].get("RmRunSubmissions", result[0])
            return row.get("runId")
    except Exception as exc:
        logger.error(
            f"rm_callback: ZCQL lookup failed for {request_id}: {exc}",
            exc_info=True,
        )
    return None


def _count_data(data: dict) -> dict:
    """Pull integer counts from a `<resource>Changed`-style data block.

    Returns counts for keys 'created', 'updated', 'deleted' if present;
    each defaults to 0 if absent or non-list.
    """
    counts = {"created": 0, "updated": 0, "deleted": 0}
    if not isinstance(data, dict):
        return counts
    for key in counts:
        v = data.get(key)
        if isinstance(v, list):
            counts[key] = len(v)
    return counts


def _insert_callback_row(app, row: dict) -> None:
    table = app.datastore().table("RmRunCallbacks")
    table.insert_row(row)


def handler(request: Request):
    """Catalyst AdvancedI/O entry point."""
    if request.method != "POST":
        return _respond(405, {"error": "method not allowed"})

    if not _verify_signature(request):
        logger.warning("rm_callback: rejected — signature mismatch")
        return _respond(401, {"error": "unauthorized"})

    body = request.get_json(silent=True)
    if body is None:
        logger.error("rm_callback: malformed or missing JSON body")
        return _respond(400, {"error": "malformed body"})

    request_id = body.get("requestId")
    territory_id = body.get("territoryId", "")
    event = body.get("event", "")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    counts = _count_data(data)

    try:
        import zcatalyst_sdk

        app = zcatalyst_sdk.initialize(getattr(request, "context", None))
    except Exception as exc:
        logger.error(f"rm_callback: catalyst init failed: {exc}", exc_info=True)
        return _respond(500, {"error": "init failed"})

    # requestId is null when the change originated in the WWRM UI rather than
    # an API call we made — accept it and persist without a run_id mapping.
    if request_id:
        run_id = _lookup_run_id(app, request_id)
        if run_id is None:
            logger.warning(
                f"rm_callback: no submission row for requestId={request_id} "
                f"(orphan callback or pre-write race) — recording without run_id"
            )
    else:
        run_id = None
        logger.info(f"rm_callback: UI-originated event={event} (no requestId)")

    row = {
        "requestId": request_id or "",
        "runId": run_id or "",
        "territoryId": territory_id,
        "event": event,
        "ordersCreatedCount": counts["created"],
        "ordersUpdatedCount": counts["updated"],
        "ordersDeletedCount": counts["deleted"],
        "rawPayload": json.dumps(body)[:8000],
        "receivedAt": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _insert_callback_row(app, row)
    except Exception as exc:
        logger.error(
            f"rm_callback: Datastore insert failed for requestId={request_id}: {exc}",
            exc_info=True,
        )
        return _respond(500, {"error": "persistence failed"})

    logger.info(
        f"rm_callback: recorded requestId={request_id} run_id={run_id} "
        f"event={event} created={counts['created']} updated={counts['updated']} "
        f"deleted={counts['deleted']}"
    )
    return _respond(200, {"ok": True})
