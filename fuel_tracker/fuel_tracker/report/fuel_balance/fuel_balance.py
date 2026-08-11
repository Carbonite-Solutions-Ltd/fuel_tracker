# Copyright (c) 2024, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Per-tanker fuel balance for a period.

This report reads its closing figure straight from the ledger — the same
`get_balance_as_of` the `Fuel Balance` doctype is synced from — so the two can
never disagree. It used to re-derive the balance by summing every litres
column, which drifted from the doctype in three ways:

* it grouped by `(site, fuel_tanker)`, so a tanker whose entries carried more
  than one site name (the site on `Fuel Used` is keyed by hand) was split into
  several part-rows, none of which matched the tanker's real balance;
* it added up movements recorded *before* an `Opening Balance` entry, which
  the ledger deliberately discards — an opening balance asserts what the
  tanker held at that moment and supersedes whatever came before it;
* it silently dropped future-dated entries while the doctype counted them.

Balances belong to a tanker, so rows are per tanker and the site shown is the
tanker's own. The period columns then reconcile exactly:

    opening + supplied + transferred in
            - dispensed - transferred out
            + adjusted + opening entries = closing
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from fuel_tracker.fuel_tracker.fuel_ledger import (
	INFLOW_TYPES,
	OPENING_TYPE,
	OUTFLOW_TYPES,
	PRECISION,
	get_balance_as_of,
	make_posting_datetime,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})

	# `date` is the filter this report used to carry; keep honouring it so
	# saved filters and any existing links do not break.
	to_date = filters.get("to_date") or filters.get("date") or nowdate()
	to_datetime = make_posting_datetime(to_date, "23:59:59.999999")
	from_datetime = (
		make_posting_datetime(filters.get("from_date"), "00:00:00")
		if filters.get("from_date")
		else None
	)

	tankers = get_tankers(filters)
	if not tankers:
		return get_columns(), []

	movements = get_movements(tankers, from_datetime, to_datetime)
	resets = get_opening_resets(tankers, from_datetime, to_datetime)
	limits = get_tanker_limits(tankers)

	data = []
	for tanker in tankers:
		# Opening is everything posted strictly before the period; closing is
		# the ledger's own figure at the end of it. Both come from the ledger,
		# which is what keeps this report tied to the Fuel Balance doctype.
		opening = get_balance_as_of(tanker, from_datetime, strict=True) if from_datetime else 0.0
		closing = get_balance_as_of(tanker, to_datetime)
		moves = movements.get(tanker, {})
		limit = limits.get(tanker, frappe._dict())

		row = {
			"site": limit.site,
			"fuel_tanker": tanker,
			"opening_balance": flt(opening, PRECISION),
			"litres_supplied": flt(moves.get("supplied"), PRECISION),
			"transferred_in": flt(moves.get("transferred_in"), PRECISION),
			"litres_dispensed": flt(moves.get("dispensed"), PRECISION),
			"transferred_out": flt(moves.get("transferred_out"), PRECISION),
			"litres_adjusted": flt(moves.get("adjusted"), PRECISION),
			"opening_entry": flt(resets.get(tanker), PRECISION),
			"current_balance": flt(closing, PRECISION),
			"minimum_level": flt(limit.minimum_level, PRECISION),
		}

		# The row must add up. If it ever does not, the ledger itself is
		# damaged, and silently showing a plausible number would hide that.
		expected = flt(
			row["opening_balance"]
			+ row["litres_supplied"] + row["transferred_in"]
			- row["litres_dispensed"] - row["transferred_out"]
			+ row["litres_adjusted"] + row["opening_entry"],
			PRECISION,
		)
		row["difference"] = flt(row["current_balance"] - expected, PRECISION)
		row["status"] = get_status(row)

		data.append(row)

	data.sort(key=lambda r: (r["site"] or "", r["fuel_tanker"]))
	return get_columns(data), data


def get_status(row):
	if row["difference"]:
		return _("Check Ledger")
	if row["minimum_level"] and row["current_balance"] < row["minimum_level"]:
		return _("Low")
	return _("OK")


def get_tankers(filters):
	"""Tankers in scope: every one that has a balance row or ledger history.

	Driven off the tanker master rather than off the entries, so the site
	shown is the tanker's own and a tanker cannot be split across rows by
	inconsistent site values on its transactions.
	"""
	conditions = []
	values = {}

	if filters.get("fuel_tanker"):
		conditions.append("ft.name IN %(fuel_tanker)s")
		values["fuel_tanker"] = tuple(as_list(filters.get("fuel_tanker")))
	if filters.get("site"):
		conditions.append("ft.site IN %(site)s")
		values["site"] = tuple(as_list(filters.get("site")))

	where = (" AND " + " AND ".join(conditions)) if conditions else ""

	return frappe.db.sql_list(
		"""
		SELECT ft.name
		FROM `tabFuel Tanker` ft
		WHERE (
			EXISTS (SELECT 1 FROM `tabFuel Entry` fe
					WHERE fe.fuel_tanker = ft.name AND fe.docstatus = 1)
			OR EXISTS (SELECT 1 FROM `tabFuel Balance` fb
					WHERE fb.fuel_tanker = ft.name AND fb.docstatus < 2)
		) {where}
		ORDER BY ft.site, ft.name
		""".format(where=where),
		values,
	)


def get_movements(tankers, from_datetime, to_datetime):
	"""Sum each movement type per tanker over the period.

	Transfers are split out from ordinary supplies and dispenses: they reuse
	the same litres columns in the ledger, but on a balance report it matters
	whether fuel was bought in or moved from another tanker.
	"""
	conditions = ["fe.docstatus = 1", "fe.fuel_tanker IN %(tankers)s", "fe.posting_datetime <= %(to_datetime)s"]
	values = {"tankers": tuple(tankers), "to_datetime": to_datetime}

	if from_datetime:
		conditions.append("fe.posting_datetime >= %(from_datetime)s")
		values["from_datetime"] = from_datetime

	rows = frappe.db.sql(
		"""
		SELECT
			fe.fuel_tanker,
			SUM(CASE WHEN fe.utilization_type = 'Supplied' THEN fe.litres_supplied ELSE 0 END) AS supplied,
			SUM(CASE WHEN fe.utilization_type = 'Transfer In' THEN fe.litres_supplied ELSE 0 END) AS transferred_in,
			SUM(CASE WHEN fe.utilization_type = 'Dispensed' THEN fe.litres_dispensed ELSE 0 END) AS dispensed,
			SUM(CASE WHEN fe.utilization_type = 'Transfer Out' THEN fe.litres_dispensed ELSE 0 END) AS transferred_out,
			SUM(CASE WHEN fe.utilization_type = 'Adjustment' THEN fe.litres_adjusted ELSE 0 END) AS adjusted
		FROM `tabFuel Entry` fe
		WHERE {conditions}
		GROUP BY fe.fuel_tanker
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	return {row.fuel_tanker: row for row in rows}


def get_opening_resets(tankers, from_datetime, to_datetime):
	"""Net effect of any `Opening Balance` entry falling inside the period.

	An opening balance does not move the tanker's stock, it *declares* it, so
	its effect on the period is the jump from whatever the ledger held
	immediately before it to the figure it asserts. Without this the row would
	not reconcile for the period in which a tanker was first opened.
	"""
	conditions = [
		"docstatus = 1",
		"utilization_type = %(opening_type)s",
		"fuel_tanker IN %(tankers)s",
		"posting_datetime <= %(to_datetime)s",
	]
	values = {"tankers": tuple(tankers), "to_datetime": to_datetime, "opening_type": OPENING_TYPE}

	if from_datetime:
		conditions.append("posting_datetime >= %(from_datetime)s")
		values["from_datetime"] = from_datetime

	entries = frappe.db.sql(
		"""
		SELECT name, fuel_tanker, posting_datetime, creation, current_balance
		FROM `tabFuel Entry`
		WHERE {conditions}
		ORDER BY posting_datetime, creation
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	resets = {}
	for entry in entries:
		before = get_balance_as_of(
			entry.fuel_tanker, entry.posting_datetime, before_creation=entry.creation
		)
		resets[entry.fuel_tanker] = flt(resets.get(entry.fuel_tanker)) + flt(entry.current_balance) - before

	return resets


def get_tanker_limits(tankers):
	rows = frappe.get_all(
		"Fuel Tanker",
		filters={"name": ["in", tankers]},
		fields=["name", "site", "minimum_level"],
	)
	return {row.name: row for row in rows}


def as_list(value):
	return value if isinstance(value, (list, tuple)) else [value]


def get_columns(data=None):
	columns = [
		{"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 200},
		{"label": _("Fuel Tanker"), "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 190},
		{"label": _("Opening Balance"), "fieldname": "opening_balance", "fieldtype": "Float", "width": 140},
		{"label": _("Supplied"), "fieldname": "litres_supplied", "fieldtype": "Float", "width": 120},
		{"label": _("Transferred In"), "fieldname": "transferred_in", "fieldtype": "Float", "width": 130},
		{"label": _("Dispensed"), "fieldname": "litres_dispensed", "fieldtype": "Float", "width": 120},
		{"label": _("Transferred Out"), "fieldname": "transferred_out", "fieldtype": "Float", "width": 140},
		{"label": _("Adjusted"), "fieldname": "litres_adjusted", "fieldtype": "Float", "width": 120},
	]

	# Only worth a column when a tanker was actually opened inside the period.
	if any(row.get("opening_entry") for row in (data or [])):
		columns.append(
			{"label": _("Opening Entry"), "fieldname": "opening_entry", "fieldtype": "Float", "width": 130}
		)

	columns += [
		{"label": _("Closing Balance"), "fieldname": "current_balance", "fieldtype": "Float", "width": 150},
		{"label": _("Minimum Level"), "fieldname": "minimum_level", "fieldtype": "Float", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
	]

	# Surfaced only when the ledger fails to reconcile, which should never happen.
	if any(row.get("difference") for row in (data or [])):
		columns.append(
			{"label": _("Difference"), "fieldname": "difference", "fieldtype": "Float", "width": 120}
		)

	return columns
