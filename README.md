# RouteManager Autobridge

A genericized public snapshot of a live production system. The system runs unattended as two Zoho Catalyst serverless functions, bridging a CRM to a route-dispatch platform for a recurring-service business.

**Scope of this repository.** Client identity, CRM package names and pricing are replaced with generic equivalents. Run output, which contains customer addresses and property access codes, is excluded. Credentials and deployment identifiers are excluded. Application code and architecture are unmodified from production.

This repository is not the deployment source. Deployment runs from a separate private repository; the workflow here is guarded so it cannot deploy. Business rules are in [`PackageDescriptions.md`](PackageDescriptions.md).

---

## 1. What the system does

Customers hold recurring spa and hot-tub maintenance memberships at nine cadences, from one deep clean per year to twice-weekly visits. Membership records live in **Zoho CRM**; dispatch and routing happen in **WorkWave RouteManager**.

The two systems model the work differently. Zoho stores a membership as a description — a package name, a service-group number, a preferred weekday. WorkWave requires concrete dated orders, one per visit, geocoded and time-windowed. This system converts the former into the latter.

Once a month it:

1. Reads active maintenance members from Zoho CRM via a bulk export.
2. Expands each membership into a full year of dated service orders.
3. Filters that year to the target month.
4. Submits the resulting orders to WorkWave in batches.
5. Emails an audit report and records each submission in a Catalyst Datastore ledger.

A second function receives WorkWave's asynchronous callbacks and records them against the originating run.

### Visit types

- **Standard visit** — routine maintenance.
- **Drain & Detail (D&D)** — deeper service, modeled in WorkWave as a `drain` job plus a same-day `fill` job. A D&D replaces that week's standard visit; the two never fall on the same day.

### Pipeline

One `Property` (a Zoho row) is expanded by a membership **handler** into a year of `OrderInput` objects. A shared **scheduler** snaps each to a business day. The generator filters to the target month, stamps a `run_id`, and categorizes the results. The WorkWave client submits them in batches.

---

## 2. Architecture

```
Zoho CRM ──bulk read──▶ rm_autobridge (cron) ──POST orders──▶ WorkWave RouteManager
                              │                                         │
                              ├─▶ Catalyst Datastore (RmRunSubmissions) │
                              ├─▶ Catalyst File Store (logs + summary)  │
                              └─▶ Resend (audit / summary email)        │
                                                                        │
WorkWave ──async webhook (ordersChanged)──▶ rm_callback (HTTP) ──▶ Datastore (RmRunCallbacks)
```

Two independent Catalyst functions share one Datastore. `rm_autobridge` writes a submission row per WorkWave batch. `rm_callback` joins WorkWave's webhook back to that row by `requestId`.

### Module data flow

```
ZohoClient ──csv bytes──▶ OrderGenerator
                              │
                              ├─ CSVReader + PropertyValidator ──▶ List[Property]
                              ├─ MembershipFactory ──▶ a MembershipHandler per property
                              │       └─ handler.generate_orders() uses:
                              │            FrequencyCalculator (ideal dates)
                              │            GlobalScheduler   (snap to business day, balance load)
                              │            BusinessDayCalendar (weekends + holidays)
                              │            NoteBuilder       (technician notes)
                              ├─ filter to target month + stamp run_id
                              └─ categorize ──▶ GenerationResult (service / drain / fill / manual / errors)
                                                      │
                              WorkwaveClient ◀───────┘ (submit_orders, batched)
                              ReportBuilder + EmailClient ◀── errors ── (audit/summary email)
```

### Structural properties

- **Strategy and Factory for membership tiers.** Each of the nine cadences has its own handler. `MembershipFactory` routes a CRM package name to a frequency category via YAML config, then to the registered handler. Adding a tier requires a new handler file and one registration line.
- **One scheduler per run, shared across all properties.** `GlobalScheduler` holds a `daily_load` counter and moves a visit to a later business day when its ideal date is already crowded. Load balancing requires this global state, so the scheduler is constructed once per run and passed to every handler.
- **Generation covers a full year, then filters to one month.** D&D placement in a given month depends on where the preceding month's visits landed. Handlers select D&D dates from the already-scheduled visit list rather than from an independent ideal pattern.
- **Every order carries a `run_id`.** It is written to the WorkWave custom field `Autobridge Run`. `OrderInput.to_dict()` raises if `run_id` is unset.

---

## 3. Repository layout

```
routemanager-autobridge/
├── functions/                     ← the two deployable Catalyst functions
│   ├── rm_autobridge/             ← cron function: generate + submit
│   │   ├── main.py                ← Catalyst cron entry point (date routing)
│   │   ├── config/                ← YAML business config (tiers, service rules)
│   │   └── src/                   ← application code (see §4)
│   └── rm_callback/               ← HTTP function: receive WorkWave webhooks
│       └── main.py                ← single-file handler (HMAC verify + datastore write)
├── tests/                         ← pytest suite
│   └── manual/                    ← hand-run scripts, not collected by pytest (see §6)
├── trigger.py                     ← manual out-of-band CLI
├── deploy.sh                      ← injects .env into catalyst-config.json, deploys both
├── catalyst.json                  ← Catalyst project manifest (function targets)
└── PackageDescriptions.md         ← business rules
```

---

## 4. File reference

### Entry points

| File | Responsibility |
| --- | --- |
| `functions/rm_autobridge/main.py` | Cron handler. Fires daily at 14:00 UTC. Targets the next calendar month. Runs a dry-run audit on the last weekday before the 15th and before the 26th, and a live load on the last weekday on or before the 26th. Builds the `run_id` (`autobridge-YYYY-MM`), configures logging, initializes the Catalyst SDK, and calls `src/dry_run.py` and/or `src/main.py`. Contains the `_last_weekday_*` helpers. |
| `functions/rm_callback/main.py` | WorkWave webhook receiver (Catalyst AdvancedIO). Self-contained; does not import `src/`. Verifies the HMAC-SHA256 URL signature, parses the `event`/`data` payload, joins to `RmRunSubmissions` by `requestId` to recover the `run_id`, and inserts an `RmRunCallbacks` row. Returns 200 on success and 500 on persistence failure, which causes WorkWave to retry. Accepts UI-originated events, which arrive with `requestId` null. |

### Pipeline orchestration (`src/`)

| File | Responsibility |
| --- | --- |
| `src/main.py` | Live pipeline — `run(month, year, *, run_id, ...)`. Loads env, pulls from Zoho, runs `OrderGenerator`, writes CSV backups, submits to WorkWave, builds a run-summary JSON, uploads log artifacts, sends the post-run report email. Holds `_build_run_summary` and `_upload_run_artifacts`. |
| `src/dry_run.py` | Audit pipeline — the same pull-and-generate pass, stopping after the error report email. Does not contact WorkWave or the Datastore. |

### `src/models/`

| File | Responsibility |
| --- | --- |
| `enums.py` | `ServiceType` (STANDARD/DRAIN/FILL), `Frequency` (nine tier categories plus MANUAL), `MembershipStatus`, `DayOfWeek` with `from_code` for the M/T/W/R/F/S/U codes. |
| `property.py` | `Property` dataclass — one parsed Zoho row, ~30 fields covering identity, membership, scheduling groups, contacts, access codes and service specifics. Helpers: `get_contact_name/phone`, `get_property_display_name`, `parse_address`. |
| `order_input.py` | `OrderInput` dataclass — the WorkWave order payload. `to_dict()` serializes to WorkWave's JSON shape, mapping service, pickup and delivery variants and populating `customFields` including `Autobridge Run` and `Verification`. Raises if `run_id` is unset. |

### `src/io/`

| File | Responsibility |
| --- | --- |
| `zoho_client.py` | Zoho CRM client. OAuth refresh-token flow, bulk-read job polled to completion, CSV download and unzip, then `_normalize_columns` maps Zoho API field names to canonical names via `ZOHO_COLUMN_MAP` and resolves owner lookup IDs to names. |
| `workwave_client.py` | WorkWave submission client. `submit_orders()` batches orders 100 at a time behind a durable intent log; `reconcile()` compares intended orders against what WorkWave holds. Delivery semantics are in §8 and in the module docstring. |
| `csv_reader.py` | `CSVReader.read_properties()` parses the normalized CSV into `Property` objects, validating each row and collecting per-row errors. Determines whether a Monthly Service Group is required from the membership's frequency category. |
| `csv_writer.py` | `CSVWriter` writes categorized orders and errors to CSV backup files. |
| `validators.py` | `PropertyValidator` — row-level validation of membership status and required address and membership fields, plus the `safe_str`/`safe_int` coercion helpers. |

### `src/membership/`

| File | Responsibility |
| --- | --- |
| `base.py` | `MembershipHandler` ABC. `_create_base_order` builds an `OrderInput` with common fields; `_derive_verification_required` normalizes the "Must Confirm" drain flag; `_snap_dd_to_recurring_visits` moves a D&D onto an existing visit; `_parse_dd_service_group` maps a group name to an int via each subclass's `DD_GROUP_MAP`. |
| `factory.py` | `MembershipFactory` — maps a CRM membership-name string to a frequency category via config, then to a registered handler instance. |
| `__init__.py` | Imports every handler and registers each against its `Frequency`. |
| `annual.py` | `AnnualHandler` — 1 D&D per year; eligibility spans the whole target month. |
| `semi_annual.py` | `SemiAnnualHandler` — 2 D&D per year. |
| `quarterly.py` | `QuarterlyHandler` — 4 D&D per year. |
| `monthly.py` | `MonthlyHandler` — monthly standard visits plus quarterly D&D, selected from the monthly visit list. |
| `bimonthly.py` | `BiMonthlyHandler` — visits every two weeks plus quarterly D&D. |
| `weekly.py` | `WeeklyHandler`, an abstract base carrying the D&D cadence, plus the registered subclasses `WeeklyQuarterlyHandler` and `WeeklyMonthlyHandler`, which select D&D dates from the scheduled weekly visits. |
| `twice_weekly.py` | `TwiceWeeklyMonthlyHandler` — twice-weekly visits generated week by week honoring two preferred days, plus monthly D&D. |
| `custom_biweekly_dd.py` | `CustomBiWeeklyDDHandler` — weekly visits with alternating bi-weekly D&D (26 standard, 26 D&D). |

### `src/scheduling/`

| File | Responsibility |
| --- | --- |
| `business_day_calendar.py` | `BusinessDayCalendar(year)` precomputes business days (Monday–Friday minus a fixed and calculated US holiday set). Exposes `is_business_day`, `next_business_day`, `get_business_days_in_week/month`. |
| `global_scheduler.py` | `GlobalScheduler` snaps ideal dates to business days, honors a preferred weekday, and balances load via a `daily_load` counter; it is stateful and shared across all properties in a run. `FrequencyCalculator` provides static ideal-date patterns for weekly, biweekly, twice-weekly, monthly, quarterly, semi-annual and annual cadences. |
| `weekday_resolver.py` | `WeekdayResolver` parses preferred-day strings (`"M"`, `"T;R"`, `"Any Day"`) into weekday numbers and formats them for export. |
| `service_group_manager.py` | `ServiceGroupManager` maps service-group numbers to start dates and day ranges, and computes week-of-month. |

### `src/processors/`, `src/notifications/`, `src/config/`, `src/utils/`

| File | Responsibility |
| --- | --- |
| `processors/order_generator.py` | `OrderGenerator.generate()` reads properties, builds the calendar and scheduler, runs each property's handler across a full year, filters to the target month, stamps the `run_id`, and categorizes into `GenerationResult` (service, drain, fill, manual, errors). `write_output()` writes the CSV backups. Defines `GenerationResult`. |
| `processors/note_builder.py` | `NoteBuilder.build_notes()` assembles the technician-notes block — access codes, directions, sanitizer — from a `Property`. |
| `notifications/report_builder.py` | `ReportBuilder.build_error_report()` builds the email subject, HTML body and errors-CSV attachment, with distinct copy for the pre-run audit and the post-run summary. |
| `notifications/email_client.py` | `EmailClient` — wrapper over Resend, sends the report with attachments. |
| `config/settings.py` | `Config` and `get_config()` (singleton) load the two YAML files and expose `get_membership_category`, `get_service_time`, `get_service_group_range`. |
| `utils/logger.py` | Structured logging. A `run_id` `ContextVar` is injected into every record. A console handler emits human-readable output; an optional JSONL handler emits one machine-parseable record per event. |
| `utils/phone_validator.py` | `PhoneValidator` — validates, formats and normalizes phone numbers with fallbacks. |

---

## 5. Configuration and data contracts

### YAML business config — `functions/rm_autobridge/config/`

- **`membership_tiers.yaml`** — maps each frequency category to a list of exact CRM package-name strings, which is what the factory routes on. The names in this repository are generic equivalents; a deployment carries its own catalog.
- **`service_rules.yaml`** — service times (standard 20 min, drain 40, fill 20), service windows, service-group week ranges, recurrence patterns, D&D group mappings, and reference annual visit counts.

### Frequency categories

| Category | Per year | Handler |
| --- | --- | --- |
| `annual` | 1 D&D | `AnnualHandler` |
| `semi_annual` | 2 D&D | `SemiAnnualHandler` |
| `quarterly` | 4 D&D | `QuarterlyHandler` |
| `monthly` | 8 standard + 4 D&D | `MonthlyHandler` |
| `bi_monthly` | 22 standard + 4 D&D | `BiMonthlyHandler` |
| `weekly` | 48 standard + 4 D&D | `WeeklyQuarterlyHandler` |
| `weekly_monthly` | 40 standard + 12 D&D | `WeeklyMonthlyHandler` |
| `twice_weekly` | 92 standard + 12 D&D | `TwiceWeeklyMonthlyHandler` |
| `custom_biweekly_dd` | 26 standard + 26 D&D | `CustomBiWeeklyDDHandler` |

### Environment variables

Injected at deploy time. See `.env.example` in each function directory.

| Variable(s) | Function | Purpose |
| --- | --- | --- |
| `ZOHO_ACCOUNTS_URL`, `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_API_DOMAIN` | rm_autobridge | Zoho OAuth bulk read |
| `WORKWAVE_API_KEY`, `WORKWAVE_TERRITORY_ID` | rm_autobridge | WorkWave submission |
| `RESEND_API_KEY`, `RESEND_FROM_ADDRESS` | rm_autobridge | Report email |
| `CALLBACK_SHARED_SECRET` | rm_callback | WorkWave HMAC verification |

### Catalyst Datastore tables

- **`RmRunSubmissions`** — one row per WorkWave batch: `requestId`, `runId`, `batchNum`, `orderCount`, `zohoIds`, `submittedAt`. The row is written before the POST with `requestId` empty, and `requestId` is set once WorkWave acknowledges.
- **`RmRunCallbacks`** — one row per received webhook: derived created, updated and deleted counts plus a truncated raw payload, joined to a run by `requestId`.

---

## 6. Tests

```bash
pytest tests/ -v
```

| File | Covers |
| --- | --- |
| `tests/test_business_day_calendar.py` | holiday and weekend/business-day logic |
| `tests/test_global_scheduler.py` | frequency calculators, load balancing |
| `tests/test_scheduling_integration.py` | calendar → scheduler → calculator end to end |
| `tests/test_workwave_idempotency.py` | delivery semantics: which failures retry, which abort, the run re-entry guard, reconciliation |

`tests/manual/` holds hand-run diagnostics. They are named outside `python_files` and excluded by `norecursedirs`, so pytest does not collect them. One submits real orders to WorkWave. See [`tests/manual/README.md`](tests/manual/README.md).

Unit test coverage is present for the scheduling core and the WorkWave delivery semantics. It is absent for `rm_callback`, the Zoho integration, the email layer, the CSV writer, validation, and `OrderGenerator` as a whole.

---

## 7. Deployment

Catalyst config files cannot hold secrets in git. `deploy.sh`:

1. Reads each function's `.env`.
2. Injects the key/value pairs into that function's `catalyst-config.json` under `env_variables`.
3. Runs `catalyst deploy --only functions`, deploying both `rm_autobridge` and `rm_callback`.
4. Restores the clean config files via an `EXIT` trap, on success or failure.

Both functions pin the `python_3_9` Catalyst stack. `rm_autobridge` is a `cron` deployment at 256 MB; `rm_callback` is an `advancedio` HTTP deployment at 256 MB.

### Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp functions/rm_autobridge/.env.example functions/rm_autobridge/.env   # then fill in
cp functions/rm_callback/.env.example functions/rm_callback/.env       # then fill in
pytest tests/ -v
```

### Continuous deployment

`.github/workflows/deploy.yml` runs on pushes to `main` and on pull requests:

1. `pytest tests/ -v` on Python 3.9, matching the deployed Catalyst stack.
2. On a push to `main` in the private production repository only, `.env` files are reconstructed from Actions secrets and `deploy.sh` runs non-interactively via `CATALYST_TOKEN`.

The deploy job is gated on `github.event_name == 'push' && github.repository == '<private repo>'`. Pull-request runs are test-only, because pull-request branches can read repository secrets. This public snapshot holds no credentials and never deploys.

The Catalyst CLI deploys only to a project's Development environment; promotion to a paid Production tier is a manual action in the Zoho console with no CLI or API equivalent. Only a Development environment is configured, and it is the environment the monthly cron submits real orders from. There is no manual approval gate between a merge to `main` and a deploy.

---

## 8. Delivery semantics

WorkWave's `addOrders` endpoint is asynchronous and has no documented server-side deduplication. A 2xx response means the batch is queued, not applied. Resending an identical batch creates a second set of orders.

The client therefore does not infer a batch's outcome from a status code it did not receive.

### Retry policy

| Outcome | Reached the queue | Behavior |
| --- | --- | --- |
| HTTP 429 | No — rejected before queueing | Retry with exponential backoff |
| `ConnectTimeout` | No — TCP connect did not complete | Retry with exponential backoff |
| HTTP 4xx other than 429 | No — rejected | Report as a failed batch; no retry |
| `ReadTimeout` | Unknown — request sent, reply lost | Raise `AmbiguousBatchError`; abort the run |
| HTTP 5xx | Unknown — may have been committed | Raise `AmbiguousBatchError`; abort the run |
| Other transport errors | Unknown — may have dropped mid-flight | Raise `AmbiguousBatchError`; abort the run |

An aborted run stops before later batches, and still emits its run summary and report email with `needs_reconciliation` set.

### Intent log

A row is written to `RmRunSubmissions` before each POST, carrying the batch's `zohoIds` and an empty `requestId`. The real `requestId` is written only after WorkWave acknowledges. An empty `requestId` therefore identifies a batch whose outcome is unknown, and survives a crash or a cold start.

### Run re-entry guard

`submit_orders()` reads the ledger before submitting. Batches already carrying a `requestId` are skipped. If any batch for the run lacks one, no batch is submitted and `AmbiguousBatchError` is raised. If the ledger cannot be read, no batch is submitted. This applies to a redelivered cron invocation, an operator re-trigger and a resumed partial run.

### Reconciliation

`WorkwaveClient.reconcile()` reads the territory's orders, filters to the current `run_id`, and returns the intended orders not present. `trigger.py reconcile` exposes it, reporting by default and submitting with `--submit`.

Two constraints apply to that comparison:

- Orders created by cloning in the WorkWave UI inherit the `customFields` of their source, including `Autobridge Run`, and carry an additional `Copied From` field. They are excluded. Matching against a clone would classify a real order as already submitted.
- Comparison is by multiset, not set. An order whose eligibility is `{"type": "any"}` carries no dates, so two distinct visits in the same month serialize identically and differ only by the identifier WorkWave assigns.

---

## 9. Known limitations

- **Callback data is recorded but not compared.** `rm_callback` writes `RmRunCallbacks` rows, and nothing compares callback-reported creation counts against submitted counts. A discrepancy is discoverable but not surfaced.
- **Package routing is exact-string matching.** `membership_tiers.yaml` maps literal CRM package names to categories. A package added or renamed in the CRM matches nothing, generates no orders, and appears only as a row in the errors report.
- **File Store archiving is non-functional.** `src/main.py` gates run-artifact archiving on `CATALYST_RUN_ARTIFACTS_FOLDER_ID`. Catalyst's deploy API rejects any function `env_variables` key prefixed `CATALYST_` as reserved, returning HTTP 400, so the variable cannot be set through the deploy path under that name. Enabling it requires renaming `FILESTORE_FOLDER_ENV` in `src/main.py`.
- **The scheduler honors one preferred day.** `GlobalScheduler` uses only the first preferred day. `TwiceWeeklyMonthlyHandler` resolves its two days independently.
- **CSV backup headers are inconsistent.** An empty result writes the flat legacy columns from `CSVWriter._default_headers()`; a populated result writes the nested shape produced by `OrderInput.to_dict()`.

---

## 10. Operations

### A customer is not scheduled

Check the monthly errors report or `Errors.csv` for the property. Confirm the exact CRM membership string appears verbatim under the correct category in `functions/rm_autobridge/config/membership_tiers.yaml`. Matching is exact, including whitespace and punctuation.

### Adding or renaming a membership package

1. Add the exact CRM string to the correct category list in `membership_tiers.yaml`.
2. For a new cadence, add a handler in `src/membership/`, register it in `src/membership/__init__.py`, and add its `Frequency` to `src/models/enums.py`.
3. Add expected annual visit counts to `tests/manual/regression_completed_handlers.py`.
4. Run `python trigger.py preview` before the next live run.

### Running out of band

| Command | Effect |
| --- | --- |
| `python trigger.py check` | Reports which dates the cron would act on. No external calls. |
| `python trigger.py preview` | Generates and categorizes orders, writes them locally. No submission. |
| `python trigger.py dry-run` | Full audit pass including the error email. No submission. |
| `python trigger.py reconcile` | Compares a run against WorkWave and reports what is missing. `--submit` sends only those orders. |
| `python trigger.py live` | Submits to WorkWave. |

Run artifacts are written to `run-artifacts/`, which is gitignored. They are the only record of a manual run.

### Confirming a run

1. Check the summary email for submitted and error counts.
2. Query `RmRunSubmissions` for the `runId`. Each row is one batch; every row should carry a `requestId`.
3. Query `RmRunCallbacks` for the same run via `requestId`.
4. In WorkWave, filter the territory on the `Autobridge Run` custom field.

### A run aborted with `AmbiguousBatchError`

Run `python trigger.py reconcile` to see which orders are missing, then `--submit` to send those. Re-running `live` is refused by the ledger guard while any batch is unreconciled.

### Deploying and rolling back

A merge to `main` in the private repository deploys once tests pass. To roll back, revert the commit on `main` and let the pipeline redeploy; there is no separate release artifact. `./deploy.sh` after `catalyst login` performs the same deployment from a local checkout.

---

Business rules: [`PackageDescriptions.md`](PackageDescriptions.md).
