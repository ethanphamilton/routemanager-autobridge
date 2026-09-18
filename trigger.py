#!/usr/bin/env python3
"""Manual entry point for RM-Autobridge.

The deployed Catalyst function (`functions/rm_autobridge/main.py`) is a pure
cron handler, hard-gated on today's date with no override. This script is the
out-of-band way to run the same pipeline without redeploying: it reproduces
what the cron handler does (logger setup, run_id binding, date routing) and
then calls the same `src.dry_run.run` / `src.main.run` entry points.

Modes
-----
  check      Verify deps, .env keys, and show the cron schedule. Touches nothing.
  preview    Pull Zoho + generate orders. No WorkWave submit, no email.
  dry-run    Pull Zoho + generate + email the error audit. No WorkWave submit.
  live       Full pipeline. SUBMITS REAL ORDERS TO WORKWAVE and emails a report.

Usage
-----
  ./trigger.py check
  ./trigger.py preview --month 9 --year 2026
  ./trigger.py dry-run
  ./trigger.py live --month 9 --year 2026

Month/year default to the NEXT calendar month, matching cron semantics.

Caveats
-------
* Running locally passes `catalyst_app=None`, so no `RmRunSubmissions` rows are
  written and no artifacts are uploaded to File Store. The files under
  `run-artifacts/` are the only record of a manual run — keep them.
* WorkWave `addOrders` has no server-side dedupe. Re-running a month that
  already loaded creates duplicates. `live` warns when the scheduled load day
  for the target month has already passed.
* If a run aborted with an unknown batch outcome, use `reconcile` — it reads
  WorkWave back and submits only what is genuinely missing. Never re-run
  `live` to recover from an aborted run.
"""

import argparse
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
FUNCTION_DIR = REPO_ROOT / "functions" / "rm_autobridge"

# The pipeline imports as `src.*`, exactly as it does inside Catalyst.
sys.path.insert(0, str(FUNCTION_DIR))

ARTIFACTS_DIR = REPO_ROOT / "run-artifacts"

ZOHO_KEYS = (
    "ZOHO_ACCOUNTS_URL",
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "ZOHO_API_DOMAIN",
)
WORKWAVE_KEYS = ("WORKWAVE_API_KEY", "WORKWAVE_TERRITORY_ID")
EMAIL_KEYS = ("RESEND_API_KEY", "RESEND_FROM_ADDRESS")


# ---------------------------------------------------------------------------
# Date routing — mirrors functions/rm_autobridge/main.py
# ---------------------------------------------------------------------------


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _cron_days_for(year, month):
    """The three gate days in `month`, as the cron handler computes them.

    Returns (dry_run_days, load_day). A run on `load_day` targets the month
    after `month`.
    """
    import main as cron_entry  # the deployed handler, for its date helpers

    return (
        sorted(
            {
                cron_entry._last_weekday_before(15, year, month),
                cron_entry._last_weekday_before(26, year, month),
            }
        ),
        cron_entry._last_weekday_on_or_before(26, year, month),
    )


def _scheduled_load_day_for_target(target_year, target_month):
    """The day the cron would have loaded `target_year`-`target_month`.

    Loads run in the month *before* the one they target.
    """
    prev_year, prev_month = (
        (target_year - 1, 12) if target_month == 1 else (target_year, target_month - 1)
    )
    _, load_day = _cron_days_for(prev_year, prev_month)
    return load_day


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_env():
    from dotenv import load_dotenv

    env_path = FUNCTION_DIR / ".env"
    if not env_path.exists():
        sys.exit(f"error: no .env at {env_path}")
    load_dotenv(env_path)
    return env_path


def _require(keys, what):
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        sys.exit(f"error: missing {what} env vars: {', '.join(missing)}")


def _init_logging(run_id, level="INFO"):
    from src.utils import setup_logger, set_run_id

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    setup_logger(
        level=level,
        log_file=ARTIFACTS_DIR / f"run-{run_id}.log",
        jsonl_file=ARTIFACTS_DIR / f"run-{run_id}.log.jsonl",
    )
    set_run_id(run_id)


def _backup_output(output_dir, run_id):
    """Copy existing CSVs aside — write_output() overwrites them in place."""
    existing = sorted(output_dir.glob("*.csv")) if output_dir.exists() else []
    if not existing:
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = output_dir / f"backup_{run_id}_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in existing:
        shutil.copy2(f, dest / f.name)
    print(f"  backed up {len(existing)} CSV(s) → {dest.relative_to(REPO_ROOT)}")
    return dest


def _print_result(result):
    print(
        f"\n  properties : {result.total_properties} "
        f"({result.successful_properties} ok, {result.failed_properties} failed)"
    )
    print(f"  service    : {len(result.service_orders)}")
    print(f"  drain      : {len(result.drain_orders)}")
    print(f"  fill       : {len(result.fill_orders)}")
    print(f"  manual     : {len(result.manual_orders)}")
    submittable = len(result.service_orders) + len(result.drain_orders) + len(result.fill_orders)
    print(f"  submittable: {submittable}")
    if result.errors:
        print(f"\n  {len(result.errors)} error(s):")
        for e in result.errors:
            name = (
                e.get("Property Name")
                or e.get("Property Name if one is used")
                or e.get("Record Id", "?")
            )
            print(f"    - {name}: {e.get('Error Reason', 'unknown')}")
    return submittable


def _confirm_live(month, year, run_id, submittable):
    target = f"{date(year, month, 1):%B %Y}".upper()
    load_day = _scheduled_load_day_for_target(year, month)

    print("\n" + "=" * 68)
    print("  LIVE SUBMISSION — this writes real orders into WorkWave")
    print("=" * 68)
    print(f"  target month : {date(year, month, 1):%B %Y}")
    print(f"  run_id       : {run_id}")
    print(f"  orders       : {submittable}")
    print(f"  territory    : {os.getenv('WORKWAVE_TERRITORY_ID')}")
    print("  ledger       : DISABLED (local run — no RmRunSubmissions rows)")

    if load_day <= date.today():
        print()
        print(f"  !! The scheduled cron load for {date(year, month, 1):%B %Y} was")
        print(f"  !! {load_day:%A %Y-%m-%d}, which has already passed.")
        print(f"  !! If that run fired, these {submittable} orders are DUPLICATES —")
        print("  !! WorkWave has no server-side dedupe and will accept them.")
    print("=" * 68)

    typed = input(f'\nType "{target}" to submit, anything else to abort: ').strip()
    return typed.upper() == target


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def cmd_check(args):
    env_path = _load_env()
    print(f"env file     : {env_path}")

    print("\ndependencies:")
    ok = True
    for mod in ("pandas", "yaml", "requests", "dotenv", "resend", "zcatalyst_sdk"):
        try:
            __import__(mod)
            print(f"  [ok]      {mod}")
        except ImportError:
            ok = False
            note = " (needed only inside Catalyst)" if mod == "zcatalyst_sdk" else ""
            print(f"  [MISSING] {mod}{note}")
    if not ok:
        print(f"\n  install with: pip install -r {FUNCTION_DIR / 'requirements.txt'}")
        print("  (the root requirements.txt is stale — it lists sendgrid, not resend)")

    print("\nenv vars:")
    for group, keys in (("zoho", ZOHO_KEYS), ("workwave", WORKWAVE_KEYS), ("email", EMAIL_KEYS)):
        for k in keys:
            print(f"  [{'ok' if os.getenv(k) else '--'}]  {group:<9} {k}")

    today = date.today()
    dry_days, load_day = _cron_days_for(today.year, today.month)
    nxt_y, nxt_m = _next_month(today.year, today.month)
    print(f"\ncron schedule for {today:%B %Y} (targets {date(nxt_y, nxt_m, 1):%B %Y}):")
    for d in dry_days:
        print(f"  dry-run  {d:%A %Y-%m-%d}{'   <- today' if d == today else ''}")
    print(f"  LOAD     {load_day:%A %Y-%m-%d}{'   <- today' if load_day == today else ''}")
    if today not in dry_days and today != load_day:
        print(f"\n  today ({today}) is not a gate day — the deployed cron would skip.")


def cmd_preview(args):
    _load_env()
    _require(ZOHO_KEYS, "Zoho")
    _init_logging(args.run_id, args.log_level)

    from src.io.zoho_client import ZohoClient
    from src.processors.order_generator import OrderGenerator

    print(f"preview {args.month}/{args.year} — run_id={args.run_id}")
    zoho = ZohoClient(
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL"),
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
        api_domain=os.getenv("ZOHO_API_DOMAIN"),
    )
    csv_bytes = zoho.get_properties()
    print(f"  fetched {len(csv_bytes):,} bytes from Zoho")

    generator = OrderGenerator()
    result = generator.generate(csv_bytes, month=args.month, year=args.year, run_id=args.run_id)
    _print_result(result)

    out = args.output_dir or (ARTIFACTS_DIR / f"preview-{args.run_id}")
    generator.write_output(result, out)
    print(f"\n  CSVs written to {out}")
    print("  nothing submitted, no email sent")


def cmd_reconcile(args):
    """Resolve a run whose submission outcome is unknown.

    Regenerates the run's intended orders, reads back what WorkWave actually
    holds for that run_id, and reports the difference. With --submit it sends
    only the missing orders. This is the safe way out of an aborted run:
    never resend a batch, always ask WorkWave what landed first.
    """
    _load_env()
    _require(ZOHO_KEYS, "Zoho")
    _require(["WORKWAVE_API_KEY", "WORKWAVE_TERRITORY_ID"], "WorkWave")
    _init_logging(args.run_id, args.log_level)

    from src.io.zoho_client import ZohoClient
    from src.io.workwave_client import WorkwaveClient
    from src.processors.order_generator import OrderGenerator

    print(f"reconcile {args.month}/{args.year} — run_id={args.run_id}")

    zoho = ZohoClient(
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL"),
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
        api_domain=os.getenv("ZOHO_API_DOMAIN"),
    )
    result = OrderGenerator().generate(
        zoho.get_properties(), month=args.month, year=args.year, run_id=args.run_id
    )
    intended = result.service_orders + result.drain_orders + result.fill_orders

    workwave = WorkwaveClient(
        api_key=os.getenv("WORKWAVE_API_KEY"),
        territory_id=os.getenv("WORKWAVE_TERRITORY_ID"),
        catalyst_app=None,
    )
    missing, present = workwave.reconcile(intended, run_id=args.run_id)

    print("\n" + "=" * 68)
    print(f"  intended orders        : {len(intended)}")
    print(f"  already in WorkWave    : {len(present)}")
    print(f"  missing (not submitted): {len(missing)}")
    print("=" * 68)
    print("  (dispatcher clones carrying 'Copied From' are excluded)")

    if not missing:
        print("\n  Nothing missing — this run is fully loaded. No action needed.")
        return
    if not args.submit:
        print(f"\n  {len(missing)} order(s) would be submitted. Re-run with --submit to send them.")
        for o in missing[:10]:
            print(f"    - {o.name}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")
        return

    target = f"{date(args.year, args.month, 1):%B %Y}".upper()
    print(f"\n  This submits {len(missing)} order(s) to WorkWave.")
    if not args.yes:
        typed = input(f'  Type "{target}" to submit, anything else to abort: ').strip()
        if typed.upper() != target:
            print("  aborted.")
            return
    request_ids, failures, _ = workwave.submit_orders(missing, run_id=args.run_id)
    print(f"  submitted: {len(request_ids)} batch(es), {len(failures)} failed")


def cmd_dry_run(args):
    _load_env()
    _require(ZOHO_KEYS, "Zoho")
    _require(EMAIL_KEYS[:1], "Resend")
    _init_logging(args.run_id, args.log_level)

    from src.dry_run import run as dry_run

    print(f"dry-run {args.month}/{args.year} — run_id={args.run_id}")
    print("  (emails the error audit; submits nothing)")
    dry_run(month=args.month, year=args.year, run_id=args.run_id)
    print(f"\n  artifacts: {ARTIFACTS_DIR}/run-{args.run_id}.log[.jsonl]")


def cmd_live(args):
    _load_env()
    _require(ZOHO_KEYS, "Zoho")
    _require(WORKWAVE_KEYS, "WorkWave")
    _require(EMAIL_KEYS[:1], "Resend")
    _init_logging(args.run_id, args.log_level)

    from src.io.zoho_client import ZohoClient
    from src.processors.order_generator import OrderGenerator
    from src.main import run as pipeline

    output_dir = args.output_dir or (FUNCTION_DIR / "output")

    # Generate first so the confirmation prompt can state a real order count.
    # src.main.run() re-pulls and re-generates; this pass is read-only.
    if not args.yes:
        print(f"generating {args.month}/{args.year} to preview the submission...")
        zoho = ZohoClient(
            accounts_url=os.getenv("ZOHO_ACCOUNTS_URL"),
            client_id=os.getenv("ZOHO_CLIENT_ID"),
            client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
            refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
            api_domain=os.getenv("ZOHO_API_DOMAIN"),
        )
        result = OrderGenerator().generate(
            zoho.get_properties(),
            month=args.month,
            year=args.year,
            run_id=args.run_id,
        )
        submittable = _print_result(result)
        if submittable == 0:
            sys.exit("\naborted: nothing to submit")
        if not _confirm_live(args.month, args.year, args.run_id, submittable):
            sys.exit("\naborted — nothing submitted")

    if not args.no_backup:
        _backup_output(output_dir, args.run_id)

    print(f"\nsubmitting {args.month}/{args.year} — run_id={args.run_id}\n")
    pipeline(
        month=args.month,
        year=args.year,
        run_id=args.run_id,
        output_dir=output_dir,
        catalyst_app=None,
        log_artifacts_dir=ARTIFACTS_DIR,
    )
    print(f"\n  summary  : {ARTIFACTS_DIR}/run-{args.run_id}.summary.json")
    print(f"  log      : {ARTIFACTS_DIR}/run-{args.run_id}.log[.jsonl]")
    print("  these files are the ONLY record of this run — no ledger rows were written")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    today = date.today()
    def_year, def_month = _next_month(today.year, today.month)

    parser = argparse.ArgumentParser(
        prog="trigger.py",
        description="Manually trigger RM-Autobridge without redeploying to Catalyst.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Month/year default to the next calendar month "
        f"({def_month}/{def_year}), matching cron semantics.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    def add_common(p, with_month=True):
        if with_month:
            p.add_argument(
                "--month",
                type=int,
                default=def_month,
                choices=range(1, 13),
                metavar="1-12",
                help="target month (default: %(default)s)",
            )
            p.add_argument(
                "--year", type=int, default=def_year, help="target year (default: %(default)s)"
            )
            p.add_argument("--run-id", default=None, help="default: autobridge-YYYY-MM-manual")
            p.add_argument("--output-dir", type=Path, default=None)
        p.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))

    p_check = sub.add_parser("check", help="verify deps/env and show the cron schedule")
    add_common(p_check, with_month=False)
    p_check.set_defaults(func=cmd_check)

    p_prev = sub.add_parser("preview", help="generate orders; no submit, no email")
    add_common(p_prev)
    p_prev.set_defaults(func=cmd_preview)

    p_dry = sub.add_parser("dry-run", help="generate + email error audit; no submit")
    add_common(p_dry)
    p_dry.set_defaults(func=cmd_dry_run)

    p_live = sub.add_parser("live", help="full pipeline — SUBMITS TO WORKWAVE")
    add_common(p_live)
    p_live.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt (for non-interactive use)"
    )
    p_live.add_argument(
        "--no-backup",
        action="store_true",
        help="do not back up existing output CSVs before overwriting",
    )
    p_live.set_defaults(func=cmd_live)

    p_rec = sub.add_parser(
        "reconcile", help="compare a run against WorkWave; submit only what is missing"
    )
    add_common(p_rec)
    p_rec.add_argument(
        "--submit",
        action="store_true",
        help="actually submit the missing orders (default: report only)",
    )
    p_rec.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt (for non-interactive use)"
    )
    p_rec.set_defaults(func=cmd_reconcile)

    args = parser.parse_args()
    if getattr(args, "month", None) and not args.run_id:
        args.run_id = f"autobridge-{args.year}-{args.month:02d}-manual"
    args.func(args)


if __name__ == "__main__":
    main()
