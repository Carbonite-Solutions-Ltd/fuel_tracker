# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`fuel_tracker` is a **Frappe v15 custom app** (Python 3.10+), not a standalone project. It lives inside a Frappe bench at `apps/fuel_tracker`; the bench root is two levels up (`fb-15-3/`). Almost every command runs from the **bench root**, not from this directory, and against a specific site. The app tracks bulk fuel supplied to tankers and fuel dispensed to resources (trucks/equipment), maintaining running balances through a ledger.

## Commands

Run from the **bench root** (`fb-15-3/`), substituting the actual site name for `<site>`:

```bash
# Run all app tests
bench --site <site> run-tests --app fuel_tracker

# Run tests for a single doctype (module path, not file path)
bench --site <site> run-tests --module fuel_tracker.fuel_tracker.doctype.fuel_entry.test_fuel_entry

# Apply code/schema changes after editing a doctype JSON or Python controller
bench --site <site> migrate

# Rebuild JS/CSS assets after editing client scripts
bench build --app fuel_tracker

# Tail logs / open a shell with the frappe context loaded
bench --site <site> console
```

CI (`.github/workflows/ci.yml`) provisions a fresh bench + MariaDB, installs the app onto `test_site`, sets `allow_tests true`, then runs `run-tests --app fuel_tracker`. There is no separate lint step configured.

## Architecture: the fuel ledger

The domain is a **date-aware, double-entry-style ledger** modelled on ERPNext's Stock Ledger. Understanding the flow between the doctypes is the key to this codebase — they are wired through Frappe document lifecycle hooks (`on_submit` / `on_cancel`), not direct calls.

### `fuel_tracker/fuel_tracker/fuel_ledger.py` is the core

All balance arithmetic lives in this one module; the doctype controllers only call into it. The rules it enforces:

- Every `Fuel Entry` carries a **`posting_datetime`** (`date` + `posting_time`). The ledger is ordered by `(posting_datetime, creation)` — `creation` is the tiebreaker for entries posted at the same instant.
- `get_balance_as_of(tanker, posting_datetime)` answers *"what did this tanker hold at that moment"* by reading the ledger. **Never** compute a previous balance from the live `Fuel Balance` — that is the bug this replaced, and it made backdated entries wrong.
- `repost_tanker(tanker, from_datetime)` walks every submitted entry at or after a point and rewrites its `previous_balance`/`current_balance` so the chain stays continuous. Submitting **or** cancelling any entry reposts the tail, which is what lets a backdated document slot into the middle of history.
- Reposts use `frappe.db.set_value(..., update_modified=False)`: these rows are submitted, and the balances are derived state, not user input. Consequently **never order ledger queries by `modified`** — it is deliberately not bumped.
- `get_balance_as_of(..., before_creation=X)` makes the cut-off exclusive on the *full* sort key. Entries recorded moments apart share a timestamp, so a time-only cut-off silently drops the entry a repost needs to continue from.

### Source documents

Source documents no longer compute balances at all — they create a `Fuel Entry`, which prices itself.

- **`Fuel Supply Request`** (submittable) — the authorisation that must exist before any supply. Tracks its own fulfilment (`Pending` → `Partially Supplied` → `Fully Supplied`) by rolling up submitted `Fuel Supplied` docs. Has a *Create → Fuel Supplied* mapper button.
- **`Fuel Supplied`** (submittable) — fuel arriving into a tanker. `fuel_supply_request` is **mandatory** and must be submitted and for the same tanker. On submit → `Fuel Entry` with `utilization_type="Supplied"`.
- **`Fuel Used`** (submittable) — fuel dispensed to a resource. On submit → refreshes the previous reading from the live `Resource`, validates it, creates a `Dispensed` entry, and writes the new reading back. All of that is **skipped when the resource has `has_faulty_meter`** set (see below).
- **`Fuel Adjustment`** (submittable) — stock corrections. *Measured Balance* mode compares against `get_balance_as_of(posting moment)`, so a backdated dip count is measured against that day's stock. Creates an `Adjustment` entry carrying the **signed** `litres_adjusted`.
- **`Fuel Transfer`** (submittable) — fuel moved between tankers, typically across sites. Balances live on tankers, so a site-to-site move is a tanker-to-tanker move. Produces **two** entries: `Transfer Out` (debits source, uses `litres_dispensed`) and `Transfer In` (credits destination, uses `litres_supplied`). Reusing the existing litres columns is why the reports needed no transfer-specific changes.
- **`Fuel Entry`** — the ledger line. `on_submit` reposts forward. `on_cancel` cascades a cancel to its source document (via `fuel_supplied_id` / `fuel_utilization_id` / `fuel_adjustment_id` / `fuel_transfer_id`), reposts, and recomputes the resource's reading from the remaining submitted `Fuel Used` docs. Cancellation logic lives here, so `Fuel Entry` is the single place state gets unwound. Never `frappe.db.commit()` inside these hooks — the whole cancel must stay one transaction.
- **`Fuel Balance`** — one row per `fuel_tanker` (autoname `field:fuel_tanker`). Pure current state: `sync_fuel_balance` simply points it at the tail of the ledger. On submit it seeds an `Opening Balance` entry at **00:00:00** of its date, which anchors the ledger — `validate_not_before_opening` then refuses any transaction dated earlier, since the opening figure already accounts for those. Once the tanker has a submitted `Fuel Entry` the balance is locked against cancel/delete.

Consequence: never mutate `Fuel Balance` or `Resource` readings directly. Route changes through submitting/cancelling a source document.

### Backdating and `set_posting_time`

The `date` on a source document is **always** honoured, so backdating is just changing the date. `posting_time` is stamped at submission unless the user ticks **Set Posting Time**, which is the deliberate "I know exactly when this happened" path. That is what stops a draft saved at 09:00 and submitted at 17:00 from posting into the past and reposting the whole day on top of itself.

### Resource type is a pervasive branch

A `Resource` is either a **`Truck`** (tracked by `odometer_km`) or **`Equipment`** (tracked by `hours_copy`). This distinction branches almost everywhere: validation (reading can't go backwards), which field gets fetched/written back, and consumption math in the reports. When adding logic that touches a resource, handle both arms.

### Faulty meters

A `Resource` with `has_faulty_meter` set can be fuelled without a reading: `Fuel Used` requires none, validates none, and writes none back. The resulting `Fuel Entry` carries `meter_faulty = 1`, and `average_fuel_consumption_ledger` reports those rows as `Meter Faulty` instead of scoring them. Float columns are **not nullable** in Frappe, so `diff_odometer`/`diff_hours_copy` read 0 on such entries — `meter_faulty` is the only reliable way to tell "travelled nothing" from "was never measured".

## REST API layer (`fuel_tracker/api/`)

`api/login.py`, `api/fuel_used.py`, and `api/dashboard.py` hold `@frappe.whitelist()` functions consumed by an **external mobile/web client** over Frappe's v2 REST API (`/api/v2/method/fuel_tracker.api.<module>.<fn>`; canonical URLs are listed in comments at the bottom of `fuel_used.py`). These read the JSON body via `frappe.request.get_data()` rather than positional args. `login.verify_login` authenticates and returns/generates the user's `api_key`/`api_secret` for subsequent calls.

The app declares `required_apps = ["erpnext"]` (Fuel Tanker links to Item and drives Asset Category/Item Group creation) and ships the `Item-custom_resource_type` Custom Field as a fixture (`fuel_tracker/fixtures/custom_field.json`) — re-export with `bench --site <site> export-fixtures --app fuel_tracker` if that field's definition changes.

## Reports (`fuel_tracker/report/`)

Query reports (`fuel_ledger`, `average_fuel_consumption_ledger`, `fuel_balance`) are Python `execute(filters)` functions running raw SQL that `LEFT JOIN` `tabFuel Entry` with `tabFuel Used`. They filter on `docstatus = 1` (submitted only) and read the resource-type-specific diff columns (`diff_odometer` vs `diff_hours_copy`). `average_fuel_consumption_ledger` computes per-resource consumption vs a stored `average_consumption` baseline and emits an `alert_status` (Good / Warning / High Alert) — that alerting logic is the report's main purpose.

## Conventions

- **Doctype naming:** doctype *labels* have spaces (`Fuel Used`, `Fuel Entry`); their folders/modules are snake_case (`fuel_used`). SQL table names are `tab<Label>` (`` `tabFuel Entry` ``).
- Each doctype dir holds the controller (`.py`), schema (`.json`), client script (`.js`), and test (`test_*.py`). Edit the JSON to change fields, then `migrate`.
- The single Frappe module is **Fuel Tracker** (`modules.txt`). New doctypes/reports must declare `"module": "Fuel Tracker"`.
- Client-side validation (e.g. `fuel_used.js`) is mirrored by server-side validation in the controller — keep both in sync; the server check is authoritative.
