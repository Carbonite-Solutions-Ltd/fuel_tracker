# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Every litre issued for site use rather than to a vehicle or machine.

Miscellaneous issues — cleaning tools after work and the like — leave the
tanker like a dispense, so the balance reports count them, but they belong to
no resource and say nothing about consumption. What matters about them is
*why* the fuel went out and who gave it, which is exactly what the balance
and consumption reports cannot show. This register lists them with their
descriptions, and charts the litres per site so heavy site use stands out.
"""

import frappe
from frappe import _
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import MISCELLANEOUS_TYPE


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(filters), data, None, get_chart(data)


def get_columns(filters):
	columns = [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": _("Time"), "fieldname": "posting_time", "fieldtype": "Time", "width": 90},
		{"label": _("Fuel Used"), "fieldname": "name", "fieldtype": "Link", "options": "Fuel Used", "width": 120},
		{"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 170},
		{"label": _("Fuel Tanker"), "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 170},
		{"label": _("Litres"), "fieldname": "litres", "fieldtype": "Float", "width": 100},
	]

	if filters.get("include_cancelled"):
		columns.append(
			{"label": _("Cancelled Litres"), "fieldname": "cancelled_litres", "fieldtype": "Float", "width": 130}
		)

	columns += [
		{"label": _("Description"), "fieldname": "description", "fieldtype": "Small Text", "width": 300},
		{"label": _("Fuel Chit No."), "fieldname": "requisition_number", "fieldtype": "Data", "width": 120},
		{"label": _("Issued By"), "fieldname": "owner", "fieldtype": "Link", "options": "User", "width": 200},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]
	return columns


def get_data(filters):
	conditions = ["fu.entry_type = %(entry_type)s"]
	conditions.append("fu.docstatus IN (1, 2)" if filters.get("include_cancelled") else "fu.docstatus = 1")
	values = {"entry_type": MISCELLANEOUS_TYPE}

	if filters.get("from_date"):
		conditions.append("fu.date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		conditions.append("fu.date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("fuel_tanker"):
		conditions.append("fu.fuel_tanker IN %(fuel_tanker)s")
		values["fuel_tanker"] = tuple(as_list(filters.get("fuel_tanker")))
	if filters.get("site"):
		conditions.append("fu.site IN %(site)s")
		values["site"] = tuple(as_list(filters.get("site")))

	rows = frappe.db.sql(
		"""
		SELECT
			fu.name, fu.date, fu.posting_time, fu.docstatus, fu.site, fu.fuel_tanker,
			fu.fuel_issued_lts AS litres, fu.description, fu.requisition_number, fu.owner
		FROM `tabFuel Used` fu
		WHERE {conditions}
		ORDER BY fu.posting_datetime DESC, fu.creation DESC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	for row in rows:
		row["litres"] = flt(row.litres)
		row["status"] = _("Submitted")
		if row.docstatus == 2:
			# Listed for the audit trail only: a cancelled issue moved no fuel,
			# so its quantity is kept out of the Litres total and the chart.
			row["status"] = _("Cancelled")
			row["cancelled_litres"] = row["litres"]
			row["litres"] = 0

	return rows


def get_chart(data):
	"""Litres issued per site, largest first."""
	by_site = {}
	for row in data:
		if row.get("litres"):
			site = row.get("site") or _("Not Set")
			by_site[site] = flt(by_site.get(site)) + flt(row["litres"])

	if not by_site:
		return None

	sites = sorted(by_site, key=by_site.get, reverse=True)
	return {
		"data": {
			"labels": sites,
			"datasets": [{"name": _("Litres"), "values": [by_site[site] for site in sites]}],
		},
		"type": "bar",
		"colors": ["#e17055"],
	}


def as_list(value):
	return value if isinstance(value, (list, tuple)) else [value]
