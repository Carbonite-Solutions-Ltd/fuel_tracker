# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Every movement of fuel between tankers, and between sites.

Transfers are deliberately recorded in the ledger using the same litres
columns as ordinary supplies and dispenses, which keeps the balance reports
correct without special-casing them — but it also means a transfer is
invisible *as a transfer* there. This register is the view that shows the
movement whole: where the fuel left, where it landed, and whether the two
sides sit on different sites.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": _("Time"), "fieldname": "posting_time", "fieldtype": "Time", "width": 90},
		{"label": _("Transfer"), "fieldname": "name", "fieldtype": "Link", "options": "Fuel Transfer", "width": 130},
		{"label": _("From Site"), "fieldname": "from_site", "fieldtype": "Link", "options": "Site", "width": 180},
		{"label": _("From Tanker"), "fieldname": "from_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 170},
		{"label": _("To Site"), "fieldname": "to_site", "fieldtype": "Link", "options": "Site", "width": 180},
		{"label": _("To Tanker"), "fieldname": "to_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 170},
		{"label": _("Litres"), "fieldname": "litres_transferred", "fieldtype": "Float", "width": 110},
		{"label": _("Route"), "fieldname": "route", "fieldtype": "Data", "width": 110},
		{"label": _("Transported By"), "fieldname": "transported_by", "fieldtype": "Data", "width": 150},
		{"label": _("Received By"), "fieldname": "received_by", "fieldtype": "Data", "width": 150},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	conditions = ["ft.docstatus < 2"] if filters.get("include_cancelled") else ["ft.docstatus = 1"]
	values = {}

	if filters.get("from_date"):
		conditions.append("ft.date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		conditions.append("ft.date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("fuel_tanker"):
		# A tanker is interesting whether it gave the fuel up or received it.
		conditions.append("(ft.from_tanker IN %(fuel_tanker)s OR ft.to_tanker IN %(fuel_tanker)s)")
		values["fuel_tanker"] = tuple(as_list(filters.get("fuel_tanker")))
	if filters.get("site"):
		conditions.append("(ft.from_site IN %(site)s OR ft.to_site IN %(site)s)")
		values["site"] = tuple(as_list(filters.get("site")))

	rows = frappe.db.sql(
		"""
		SELECT
			ft.name, ft.date, ft.posting_time, ft.docstatus,
			ft.from_site, ft.from_tanker, ft.to_site, ft.to_tanker,
			ft.litres_transferred, ft.transported_by, ft.received_by
		FROM `tabFuel Transfer` ft
		WHERE {conditions}
		ORDER BY ft.date DESC, ft.posting_time DESC, ft.creation DESC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	for row in rows:
		row["route"] = _("Cross-site") if row.from_site != row.to_site else _("Same site")
		row["status"] = _("Cancelled") if row.docstatus == 2 else _("Submitted")
		row["litres_transferred"] = flt(row.litres_transferred)

	return rows


def as_list(value):
	return value if isinstance(value, (list, tuple)) else [value]
