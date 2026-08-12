# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Outstanding fuel supply requests and how far each has been fulfilled.

Every supply now answers a request, so the gap between what was asked for and
what actually arrived is the number worth watching: a request sitting at
Pending is fuel someone is still waiting for, and one stuck Partially Supplied
is a delivery that came up short. Both are invisible in the balance reports,
which only ever show fuel that did arrive.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Request"), "fieldname": "name", "fieldtype": "Link", "options": "Fuel Supply Request", "width": 140},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": _("Required By"), "fieldname": "required_by", "fieldtype": "Date", "width": 110},
		{"label": _("Age (days)"), "fieldname": "age", "fieldtype": "Int", "width": 100},
		{"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 180},
		{"label": _("Fuel Tanker"), "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 170},
		{"label": _("Requested"), "fieldname": "requested_litres", "fieldtype": "Float", "width": 110},
		{"label": _("Supplied"), "fieldname": "supplied_litres", "fieldtype": "Float", "width": 110},
		{"label": _("Outstanding"), "fieldname": "pending_litres", "fieldtype": "Float", "width": 120},
		{"label": _("Fulfilled %"), "fieldname": "fulfilled_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Deliveries"), "fieldname": "deliveries", "fieldtype": "Int", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
		{"label": _("Overdue"), "fieldname": "overdue", "fieldtype": "Data", "width": 90},
		{"label": _("Requested By"), "fieldname": "requested_by", "fieldtype": "Link", "options": "User", "width": 160},
	]


def get_data(filters):
	conditions = ["r.docstatus = 1"]
	values = {}

	if filters.get("from_date"):
		conditions.append("r.date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		conditions.append("r.date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("fuel_tanker"):
		conditions.append("r.fuel_tanker IN %(fuel_tanker)s")
		values["fuel_tanker"] = tuple(as_list(filters.get("fuel_tanker")))
	if filters.get("site"):
		conditions.append("r.site IN %(site)s")
		values["site"] = tuple(as_list(filters.get("site")))
	if filters.get("status"):
		conditions.append("r.status IN %(status)s")
		values["status"] = tuple(as_list(filters.get("status")))
	if filters.get("only_outstanding"):
		conditions.append("r.status IN ('Pending', 'Partially Supplied')")

	rows = frappe.db.sql(
		"""
		SELECT
			r.name, r.date, r.required_by, r.site, r.fuel_tanker, r.requested_by,
			r.requested_litres, r.supplied_litres, r.pending_litres, r.status,
			(SELECT COUNT(*) FROM `tabFuel Supplied` s
			 WHERE s.fuel_supply_request = r.name AND s.docstatus = 1) AS deliveries
		FROM `tabFuel Supply Request` r
		WHERE {conditions}
		ORDER BY r.date DESC, r.creation DESC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	today = getdate(nowdate())
	for row in rows:
		requested = flt(row.requested_litres)
		row["fulfilled_pct"] = flt(flt(row.supplied_litres) / requested * 100, 2) if requested else 0
		row["age"] = (today - getdate(row.date)).days if row.date else 0

		still_open = row.status in ("Pending", "Partially Supplied")
		row["overdue"] = (
			_("Yes") if still_open and row.required_by and getdate(row.required_by) < today else ""
		)

	return rows


def as_list(value):
	return value if isinstance(value, (list, tuple)) else [value]
