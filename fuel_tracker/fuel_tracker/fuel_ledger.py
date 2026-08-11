# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Date-aware fuel ledger: balance-as-of lookups and reposting.

The `Fuel Balance` row is *current state* — the tail of the ledger. History
lives in `Fuel Entry`. Before this module existed, every source document read
the live `Fuel Balance` to work out its own `previous_balance`, which meant a
backdated entry was priced against today's balance and appended to the end of
the ledger no matter what date it carried. Balances "as at" a past date were
therefore wrong, and a backdated dispense could be refused for insufficient
fuel even though the tanker was full on the day it actually happened.

This module fixes that the way ERPNext's Stock Ledger does:

* every entry carries a `posting_datetime` (`date` + `posting_time`), and the
  ledger is ordered by `(posting_datetime, creation)` — `creation` breaks ties
  deterministically for two entries posted at the same instant;
* `get_balance_as_of()` answers "what did this tanker hold at that moment",
  reading the ledger rather than the live balance;
* `repost_tanker()` walks every entry at or after a point in time and rewrites
  its `previous_balance`/`current_balance` so the running balance stays
  continuous, then syncs `Fuel Balance` to the tail.

Submitting, cancelling or amending anything therefore keeps the whole ledger
consistent — including the entries that already sat after the affected date.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate, now_datetime, nowdate

#: Entry types that *add* to a tanker's balance.
INFLOW_TYPES = ("Supplied", "Transfer In")
#: Entry types that *subtract* from a tanker's balance.
OUTFLOW_TYPES = ("Dispensed", "Transfer Out")
#: An opening balance *sets* the running balance instead of moving it, so it
#: is never recomputed by a repost — it is the ledger's anchor.
OPENING_TYPE = "Opening Balance"

#: Precision used when storing balances, so float noise cannot accumulate
#: across a long repost chain.
PRECISION = 3


def make_posting_datetime(date, posting_time=None):
	"""Combine a posting date and time into the ledger's sort key.

	A missing time is treated as midnight, which keeps entries created before
	`posting_time` existed ordered by date then `creation` — exactly how the
	ledger behaved previously.
	"""
	return get_datetime("{0} {1}".format(getdate(date), posting_time or "00:00:00"))


def ensure_posting_time(doc, refresh=False):
	"""Settle a document's posting time and return its ledger sort key.

	The `default: "Now"` on the field only fires in the desk, so documents
	arriving from the REST API or a script would otherwise carry no time and
	silently post at midnight — ahead of everything else recorded that day.

	`refresh` is used at submit, and is what stops a stale draft posting into
	the past. A draft saved at 09:00 and submitted at 17:00 would otherwise
	still claim 09:00, so every entry recorded in between would be reposted on
	top of it. Unless the user has explicitly ticked *Set Posting Time* — the
	deliberate backdating path — the time is moved to the moment of submission.
	The *date* is always honoured as entered, so backdating a document by date
	alone keeps working without any extra ceremony.

	Sub-second precision is kept so documents submitted in the same second
	still order by when they were actually posted; `creation` remains the
	final tiebreaker.
	"""
	if (refresh and not doc.get("set_posting_time")) or not doc.get("posting_time"):
		doc.posting_time = now_datetime().strftime("%H:%M:%S.%f")

	return make_posting_datetime(doc.date, doc.posting_time)


def entry_delta(entry):
	"""Signed litres by which an entry moves its tanker's balance.

	`Opening Balance` returns 0: it does not *move* the balance, it *is* the
	balance at that point, and :func:`repost_tanker` handles it separately.
	"""
	utilization_type = entry.get("utilization_type")

	if utilization_type in INFLOW_TYPES:
		return flt(entry.get("litres_supplied"))
	if utilization_type in OUTFLOW_TYPES:
		return -flt(entry.get("litres_dispensed"))
	if utilization_type == "Adjustment":
		# litres_adjusted is already signed, so it moves the balance either way
		return flt(entry.get("litres_adjusted"))
	return 0.0


def get_ledger_entries(fuel_tanker, from_datetime=None, exclude=None, strict=False):
	"""Submitted entries for a tanker in ledger order.

	`from_datetime` limits the walk to entries at or after that moment, which
	is what makes a repost cost only the tail of the ledger rather than all of
	it; `strict` excludes that moment itself. `exclude` drops a specific
	entry — used while a document is mid-submit and its own row must not be
	counted twice.
	"""
	filters = {"fuel_tanker": fuel_tanker, "docstatus": 1}
	if from_datetime:
		filters["posting_datetime"] = [">" if strict else ">=", from_datetime]
	if exclude:
		filters["name"] = ["!=", exclude]

	return frappe.get_all(
		"Fuel Entry",
		filters=filters,
		fields=[
			"name",
			"utilization_type",
			"posting_datetime",
			"creation",
			"litres_supplied",
			"litres_dispensed",
			"litres_adjusted",
			"previous_balance",
			"current_balance",
		],
		order_by="posting_datetime asc, creation asc",
	)


def get_balance_as_of(fuel_tanker, posting_datetime=None, exclude=None, before_creation=None, strict=False):
	"""The tanker's balance at a moment in time, read from the ledger.

	This is the "previous balance" any entry posted at `posting_datetime`
	should see: the `current_balance` of the last submitted entry that sorts
	before it. Entries posted at the exact same instant are ordered by
	`creation`, so a new entry lands after the ones already recorded there.

	`before_creation` makes the cut-off exclusive on the full sort key
	`(posting_datetime, creation)` rather than on the timestamp alone, which
	is what the repost needs to seed itself from the entry *immediately*
	before a given one — including when the two are less than a second apart.

	`strict` excludes `posting_datetime` itself. Reports use it for an opening
	balance: everything posted *before* the period starts, so an opening
	balance entry stamped 00:00:00 on the first day falls inside the period
	rather than behind it.

	Returns 0 when the tanker has no ledger history yet, matching the lazy
	`Fuel Balance` creation the source doctypes rely on.
	"""
	if not fuel_tanker:
		return 0.0

	conditions = ["fuel_tanker = %(fuel_tanker)s", "docstatus = 1"]
	values = {"fuel_tanker": fuel_tanker}

	if posting_datetime:
		values["posting_datetime"] = get_datetime(posting_datetime)
		if before_creation:
			values["before_creation"] = before_creation
			conditions.append(
				"(posting_datetime < %(posting_datetime)s"
				" OR (posting_datetime = %(posting_datetime)s AND creation < %(before_creation)s))"
			)
		else:
			conditions.append("posting_datetime {0} %(posting_datetime)s".format("<" if strict else "<="))
	if exclude:
		conditions.append("name != %(exclude)s")
		values["exclude"] = exclude

	row = frappe.db.sql(
		"""
		SELECT current_balance
		FROM `tabFuel Entry`
		WHERE {conditions}
		ORDER BY posting_datetime DESC, creation DESC
		LIMIT 1
		""".format(conditions=" AND ".join(conditions)),
		values,
	)

	return flt(row[0][0]) if row else 0.0


def repost_tanker(fuel_tanker, from_datetime=None):
	"""Rewrite the running balance of a tanker's ledger from a point onward.

	Walks every submitted entry at or after `from_datetime` in ledger order
	and rewrites `previous_balance`/`current_balance` so each entry continues
	from the one before it. This is what lets a backdated entry slot into the
	middle of the history: everything already recorded after it is re-priced
	instead of being left stranded on a stale balance.

	`frappe.db.set_value` is used rather than the document API because these
	rows are submitted; the ledger figures are derived state, not user input,
	and rewriting them must not bump `modified` or re-run submit hooks.
	Untouched rows are skipped so a repost of an unchanged tail is free.
	"""
	if not fuel_tanker:
		return

	entries = get_ledger_entries(fuel_tanker, from_datetime)
	if not entries:
		sync_fuel_balance(fuel_tanker)
		return

	# Seed from the entry immediately before the first one being reposted, so
	# the rewritten chain continues from real history rather than from zero.
	# The cut-off is exclusive on the full (posting_datetime, creation) key —
	# entries recorded moments apart share a timestamp to the second, so a
	# time-only cut-off would silently drop the entry we need to continue from.
	running = get_balance_as_of(
		fuel_tanker,
		entries[0].posting_datetime,
		before_creation=entries[0].creation,
	)

	for entry in entries:
		if entry.utilization_type == OPENING_TYPE:
			# The anchor of the ledger: its current_balance is the entered
			# opening figure and is never recomputed, only continued from.
			running = flt(entry.current_balance, PRECISION)
			continue

		previous_balance = flt(running, PRECISION)
		current_balance = flt(previous_balance + entry_delta(entry), PRECISION)

		if (
			flt(entry.previous_balance, PRECISION) != previous_balance
			or flt(entry.current_balance, PRECISION) != current_balance
		):
			frappe.db.set_value(
				"Fuel Entry",
				entry.name,
				{"previous_balance": previous_balance, "current_balance": current_balance},
				update_modified=False,
			)

		running = current_balance

	sync_fuel_balance(fuel_tanker)


def sync_fuel_balance(fuel_tanker):
	"""Point the tanker's `Fuel Balance` at the tail of its ledger.

	`Fuel Balance` is current state, so after any ledger change it is simply
	the `current_balance` of the last submitted entry (0 when the ledger is
	empty). A cancelled balance row is left alone — it no longer holds a live
	figure, and touching it would fail because cancelled documents are frozen.
	"""
	if not fuel_tanker:
		return

	name = frappe.db.get_value("Fuel Balance", {"fuel_tanker": fuel_tanker}, "name")
	if not name:
		return
	if frappe.db.get_value("Fuel Balance", name, "docstatus") == 2:
		return

	last = frappe.db.sql(
		"""
		SELECT current_balance, date
		FROM `tabFuel Entry`
		WHERE fuel_tanker = %s AND docstatus = 1
		ORDER BY posting_datetime DESC, creation DESC
		LIMIT 1
		""",
		fuel_tanker,
		as_dict=True,
	)

	values = {"balance": flt(last[0].current_balance, PRECISION) if last else 0.0}
	if last and last[0].date:
		values["date"] = last[0].date

	frappe.db.set_value("Fuel Balance", name, values, update_modified=False)


def get_opening_datetime(fuel_tanker):
	"""Posting datetime of the tanker's opening balance entry, if any."""
	return frappe.db.get_value(
		"Fuel Entry",
		{"fuel_tanker": fuel_tanker, "utilization_type": OPENING_TYPE, "docstatus": 1},
		"posting_datetime",
	)


def validate_not_before_opening(fuel_tanker, posting_datetime):
	"""Refuse a transaction dated before the tanker's opening balance.

	The opening balance asserts what the tanker held at that moment, so every
	movement before it is already baked into that figure. Allowing one would
	double-count it. ERPNext guards its stock ledger the same way.
	"""
	opening = get_opening_datetime(fuel_tanker)
	if not opening:
		return

	if get_datetime(posting_datetime) < get_datetime(opening):
		frappe.throw(
			_("This transaction is dated {0}, before the opening balance of tanker {1} ({2}). Fuel cannot move before the opening balance was struck.")
			.format(
				frappe.format(posting_datetime, {"fieldtype": "Datetime"}),
				frappe.bold(fuel_tanker),
				frappe.format(opening, {"fieldtype": "Datetime"}),
			),
			title=_("Dated Before Opening Balance"),
		)


def validate_not_future_dated(date):
	"""Refuse a transaction dated after today.

	Every movement in this ledger records something physical that already
	happened — fuel delivered, issued, dipped or carted between sites — so a
	future date is a keying error, not an intention. Left through, it also
	splits the two figures users reconcile against each other: an "as at
	today" balance report excludes it while the `Fuel Balance` doctype, which
	is the tail of the whole ledger, counts it.
	"""
	if not date:
		return

	if getdate(date) > getdate(nowdate()):
		frappe.throw(
			_("This transaction is dated {0}, which is in the future. Fuel movements are recorded after they happen.")
			.format(frappe.format(getdate(date), {"fieldtype": "Date"})),
			title=_("Future Dated"),
		)


def warn_if_ledger_goes_negative(fuel_tanker, posting_datetime, delta, source_label=None):
	"""Warn when a movement drives the balance negative — then or later.

	A backdated withdrawal can be perfectly affordable on its own date yet
	overdraw the tanker further down the ledger, so both the balance at the
	posting moment and every balance after it are checked. This warns rather
	than blocks: the ledger records what physically happened, and a negative
	balance is a data problem to investigate, not a reason to lose the record.
	"""
	if not fuel_tanker or delta >= 0:
		return

	balance_at_posting = get_balance_as_of(fuel_tanker, posting_datetime)
	new_balance = flt(balance_at_posting + delta, PRECISION)

	if new_balance < 0:
		frappe.msgprint(
			_("{0} exceeds the balance of tanker {1} on {2} ({3} L); the balance will go negative ({4} L).")
			.format(
				source_label or _("This transaction"),
				frappe.bold(fuel_tanker),
				frappe.format(getdate(posting_datetime), {"fieldtype": "Date"}),
				balance_at_posting,
				new_balance,
			),
			indicator="orange",
			alert=True,
		)
	else:
		# Affordable on the day, but the entries already recorded after it
		# each shift down by `delta` — flag it if any of them break through 0.
		# Entries sharing this exact moment already sort *before* the one being
		# submitted (they were created earlier), so the cut-off is strict.
		later = get_ledger_entries(fuel_tanker, posting_datetime, strict=True)
		breach = next((e for e in later if flt(e.current_balance) + delta < 0), None)
		if breach:
			frappe.msgprint(
				_("Tanker {0} still has fuel on {1}, but inserting this transaction drives its balance negative later, from {2} onwards.")
				.format(
					frappe.bold(fuel_tanker),
					frappe.format(getdate(posting_datetime), {"fieldtype": "Date"}),
					frappe.format(getdate(breach.posting_datetime), {"fieldtype": "Date"}),
				),
				indicator="orange",
				alert=True,
			)


def warn_if_above_threshold(fuel_tanker, posting_datetime, delta):
	"""Warn when a movement takes the tanker above its maximum threshold."""
	if not fuel_tanker or delta <= 0:
		return

	threshold = flt(frappe.db.get_value("Fuel Tanker", fuel_tanker, "tanker_threshold"))
	if not threshold:
		return

	new_balance = flt(get_balance_as_of(fuel_tanker, posting_datetime) + delta, PRECISION)
	if new_balance > threshold:
		frappe.msgprint(
			_("This raises the balance of tanker {0} to {1} L, above its maximum threshold of {2} L.")
			.format(fuel_tanker, new_balance, threshold),
			indicator="orange",
			alert=True,
		)


def warn_if_below_minimum(fuel_tanker, posting_datetime, delta):
	"""Warn when a movement takes the tanker below its reorder level."""
	if not fuel_tanker or delta >= 0:
		return

	minimum_level = flt(frappe.db.get_value("Fuel Tanker", fuel_tanker, "minimum_level"))
	if not minimum_level:
		return

	new_balance = flt(get_balance_as_of(fuel_tanker, posting_datetime) + delta, PRECISION)
	if new_balance < minimum_level:
		frappe.msgprint(
			_("The balance of tanker {0} falls below its minimum level of {1} L (new balance: {2} L). Consider reordering fuel.")
			.format(fuel_tanker, minimum_level, new_balance),
			indicator="orange",
			alert=True,
		)


def get_or_create_fuel_balance(fuel_tanker, site, date):
	"""Return the tanker's `Fuel Balance`, creating a draft one if needed.

	Created as a draft on purpose: submitting a `Fuel Balance` seeds an
	opening-balance `Fuel Entry`, and that must stay a deliberate user action
	rather than a zero-litre side effect of the first movement.
	"""
	name = frappe.db.get_value("Fuel Balance", {"fuel_tanker": fuel_tanker}, "name")
	if name:
		return frappe.get_doc("Fuel Balance", name)

	balance = frappe.get_doc({
		"doctype": "Fuel Balance",
		"fuel_tanker": fuel_tanker,
		"balance": 0,
		"site": site,
		"date": date,
	})
	balance.flags.ignore_permissions = True
	balance.insert()
	return balance


@frappe.whitelist()
def get_tanker_balance_on(fuel_tanker, date, posting_time=None):
	"""Balance of a tanker as at a date/time — used by the desk forms.

	Lets a user keying a backdated document see the balance that actually
	applied on that date rather than today's figure.
	"""
	frappe.has_permission("Fuel Entry", throw=True)
	return get_balance_as_of(fuel_tanker, make_posting_datetime(date, posting_time))
