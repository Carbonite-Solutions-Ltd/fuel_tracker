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

The domain is a **double-entry-style ledger**. Understanding the flow between four doctypes is the key to this codebase — they are wired through Frappe document lifecycle hooks (`on_submit` / `on_cancel`), not direct calls.

- **`Fuel Supplied`** (submittable) — fuel arriving into a tanker. On submit → creates a `Fuel Entry` with `utilization_type="Supplied"` that *adds* to the balance.
- **`Fuel Used`** (submittable) — fuel dispensed from a tanker to a resource. On submit → refreshes the previous odometer/hours reading from the live `Resource` (drafts can go stale) and validates the new reading against it, creates a `Fuel Entry` with `utilization_type="Dispensed"` that *subtracts* from the balance, and writes the new reading back to the `Resource`.
- **`Fuel Entry`** — the immutable ledger line. Its own `on_submit` mutates the per-tanker `Fuel Balance`. Its `on_cancel` reverses the balance change **and cascades a cancel to the source `Fuel Supplied`/`Fuel Used` doc** (via `fuel_supplied_id` / `fuel_utilization_id`), and recomputes the resource's odometer/hours from the remaining submitted `Fuel Used` docs (falling back to the cancelled doc's previous reading only when none remain). Cancellation logic lives here, so `Fuel Entry` is the single place balance and resource state get unwound. Never `frappe.db.commit()` inside these hooks — the whole cancel must stay one transaction.
- **`Fuel Balance`** — one running-balance row per `fuel_tanker` (autoname `field:fuel_tanker`, unique). Created lazily the first time a tanker is touched. This is current-state, not history; history is the set of `Fuel Entry` rows. On submit (`on_submit`), if the tanker has no *active* `Fuel Entry` yet (cancelled entries, `docstatus=2`, don't count), it seeds an opening entry (`utilization_type="Opening Balance"`) carrying `date`/`site`/`fuel_tanker` and the opening `balance` into `current_balance`, so the ledger starts from the entered balance. Once the tanker has a submitted `Fuel Entry`, the balance is locked: `on_cancel`/`on_trash` block cancel/delete, and the client script (`fuel_balance.js`) makes all fields read-only. Releasing it means cancelling the `Fuel Entry` first. **Do not** add a server-side guard that blocks *editing* a submitted balance — `FuelEntry.update_fuel_balance` saves this doc on every ledger change, so an edit-block would break the ledger.

Consequence: never mutate `Fuel Balance` or `Resource` readings directly. Route changes through submitting/cancelling `Fuel Supplied` or `Fuel Used` so the ledger, balance, and resource state stay consistent.

### Resource type is a pervasive branch

A `Resource` is either a **`Truck`** (tracked by `odometer_km`) or **`Equipment`** (tracked by `hours_copy`). This distinction branches almost everywhere: validation (reading can't go backwards), which field gets fetched/written back, and consumption math in the reports. When adding logic that touches a resource, handle both arms.

## REST API layer (`fuel_tracker/api/`)

`api/login.py`, `api/fuel_used.py`, and `api/dashboard.py` hold `@frappe.whitelist()` functions consumed by an **external mobile/web client** over Frappe's v2 REST API (`/api/v2/method/fuel_tracker.api.<module>.<fn>`; canonical URLs are listed in comments at the bottom of `fuel_used.py`). These read the JSON body via `frappe.request.get_data()` rather than positional args. `login.verify_login` authenticates and returns/generates the user's `api_key`/`api_secret` for subsequent calls.

**Gotcha:** the `doc_events` block in `hooks.py` maps placeholder doctypes `Doctype1`..`Doctype11` to these API functions. Those doctypes do not exist, so those hooks never fire — the block is effectively dead config. The API functions are reached only through the whitelisted REST endpoints above, not through document events. Don't treat that block as live wiring.

## Reports (`fuel_tracker/report/`)

Query reports (`fuel_ledger`, `average_fuel_consumption_ledger`, `fuel_balance`) are Python `execute(filters)` functions running raw SQL that `LEFT JOIN` `tabFuel Entry` with `tabFuel Used`. They filter on `docstatus = 1` (submitted only) and read the resource-type-specific diff columns (`diff_odometer` vs `diff_hours_copy`). `average_fuel_consumption_ledger` computes per-resource consumption vs a stored `average_consumption` baseline and emits an `alert_status` (Good / Warning / High Alert) — that alerting logic is the report's main purpose.

## Conventions

- **Doctype naming:** doctype *labels* have spaces (`Fuel Used`, `Fuel Entry`); their folders/modules are snake_case (`fuel_used`). SQL table names are `tab<Label>` (`` `tabFuel Entry` ``).
- Each doctype dir holds the controller (`.py`), schema (`.json`), client script (`.js`), and test (`test_*.py`). Edit the JSON to change fields, then `migrate`.
- The single Frappe module is **Fuel Tracker** (`modules.txt`). New doctypes/reports must declare `"module": "Fuel Tracker"`.
- Client-side validation (e.g. `fuel_used.js`) is mirrored by server-side validation in the controller — keep both in sync; the server check is authoritative.
