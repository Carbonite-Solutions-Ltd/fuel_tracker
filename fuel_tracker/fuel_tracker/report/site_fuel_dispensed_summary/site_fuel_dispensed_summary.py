# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Fuel dispensed at a site, day by day, one row per resource.

This is the monthly sheet sites used to keep by hand in Excel ("Summary of
fuel dispensed at <site>"): every resource stationed at the site down the
side, one column per day, the litres each was given that day, then the
month's total against what the distance covered says it should have burned.
The stock position the sheet kept under the grid (opening, received,
closing) is left to the Fuel Balance report.

Built from the ledger instead of typed in, with two deliberate differences
from the sheet:

* The daily litres are every submitted `Dispensed` entry, so they always match
  the Fuel Ledger. Miscellaneous issues belong to no resource, so they are not
  in the grid; `fuel_balance` and the Miscellaneous Fuel Register carry them.
* The consumption columns are the ledger's tank-to-tank figures
  (`fuel_tracker.consumption`), the same ones the Resource Fuel Summary and
  the Consumption Ledger use. The sheet divided *all* litres by *all*
  distance, which counts fuel that has not been burned yet (the last fill)
  and distance covered on fuel from before the month (the first), so its
  variance was off by up to a whole tank. Here "Expected" is the measured
  distance times the resource's baseline, and the variance is the measured
  litres minus that — litres over or under, not a ratio.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, format_date, get_first_day, get_last_day, getdate, nowdate

from fuel_tracker.fuel_tracker.consumption import PRECISION, as_list, get_fills, in_period
from fuel_tracker.fuel_tracker.report.resource_fuel_summary.resource_fuel_summary import (
	get_status as summary_status,
)
from fuel_tracker.fuel_tracker.report.resource_fuel_summary.resource_fuel_summary import (
	status_note as summary_note,
)

#: One column per day; past this the grid is unreadable and a period summary
#: (Resource Fuel Summary) is the better report.
MAX_DAYS = 62

TYPE_ORDER = {"Truck": 0, "Equipment": 1, "Others": 2}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.get("to_date") or get_last_day(nowdate()))
	from_date = getdate(filters.get("from_date") or get_first_day(to_date))
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))
	if date_diff(to_date, from_date) + 1 > MAX_DAYS:
		frappe.throw(
			_("Pick a period of at most {0} days — one column is shown per day.").format(MAX_DAYS)
		)
	filters.from_date, filters.to_date = from_date, to_date

	days = [add_days(from_date, i) for i in range(date_diff(to_date, from_date) + 1)]
	return get_columns(days), get_data(filters, days), get_message(filters)


def day_field(day):
	return "d_" + getdate(day).strftime("%Y%m%d")


def get_columns(days):
	columns = [
		{"label": _("Reg. No / Machine Code"), "fieldname": "reg_no", "fieldtype": "Data", "width": 150},
		{"label": _("Type"), "fieldname": "resource_type", "fieldtype": "Data", "width": 90},
		{"label": _("Chassis Number"), "fieldname": "resource", "fieldtype": "Link", "options": "Resource", "width": 180},
		{"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 160},
	]
	columns += [
		{
			"label": format_date(day, "dd MMM"),
			"fieldname": day_field(day),
			"fieldtype": "Float",
			"precision": 2,
			"width": 75,
		}
		for day in days
	]
	columns += [
		{"label": _("Total Dispensed"), "fieldname": "total_litres", "fieldtype": "Float", "precision": 2, "width": 130},
		{"label": _("Fills"), "fieldname": "fills", "fieldtype": "Int", "width": 70},
		# km and hours do not add up to anything, so no totals on these
		{"label": _("Km / Hours Used"), "fieldname": "distance", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 130},
		{"label": _("Measured Litres"), "fieldname": "measured_litres", "fieldtype": "Float", "precision": 2, "width": 130},
		{"label": _("Fuel Supposed to be Used"), "fieldname": "expected_litres", "fieldtype": "Float", "precision": 2, "width": 170},
		{"label": _("Actual Consumption"), "fieldname": "actual_consumption", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
		{"label": _("Average Consumption"), "fieldname": "average_consumption", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 160},
		{"label": _("Variance (L)"), "fieldname": "variance", "fieldtype": "Float", "precision": 2, "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
		{"label": _("What It Means"), "fieldname": "status_note", "fieldtype": "Data", "width": 380},
	]
	return columns


def get_data(filters, days):
	day_fields = {getdate(day): day_field(day) for day in days}
	rows = {}

	def row_for(resource):
		row = rows.get(resource.name)
		if not row:
			row = rows[resource.name] = frappe._dict(
				resource=resource.name,
				reg_no=resource.reg_no,
				resource_type=resource.resource_type,
				site=resource.stationed_site,
				average_consumption=flt(resource.average_consumption),
				fills=0,
				total_litres=0.0,
				measured_litres=0.0,
				distance=0.0,
				backwards_readings=0,
			)
		return row

	resources = get_resources(filters)
	for resource in resources.values():
		if filters.get("show_idle", 1):
			row_for(resource)

	fills = get_fills(
		resource=list(resources) or None,
		resource_type=filters.get("resource_type"),
		to_date=filters.to_date,
	) if resources else []

	for fill in fills:
		if not in_period(fill, filters.from_date, filters.to_date):
			continue
		resource = resources.get(fill.resource)
		if not resource:
			continue

		row = row_for(resource)
		field = day_fields[getdate(fill.date)]
		row[field] = flt(row.get(field)) + flt(fill.litres_in)
		row.fills += 1
		row.total_litres += flt(fill.litres_in)
		if fill.backwards:
			row.backwards_readings += 1
		if fill.scored:
			row.measured_litres += flt(fill.litres)
			row.distance += flt(fill.distance)

	data = []
	for row in rows.values():
		finish(row, day_fields.values())
		data.append(row)

	data.sort(key=lambda r: (TYPE_ORDER.get(r.resource_type, 9), r.reg_no or "", r.resource))
	return data


def finish(row, fields):
	"""Round the figures and work out the consumption columns and status."""
	for field in fields:
		if field in row:
			row[field] = flt(row[field], 2)
	row.total_litres = flt(row.total_litres, 2)
	row.measured_litres = flt(row.measured_litres, PRECISION)
	row.distance = flt(row.distance, PRECISION)

	baseline = row.average_consumption
	observed = flt(row.measured_litres / row.distance, PRECISION) if row.distance > 0 else 0
	row.actual_consumption = observed
	if row.distance > 0 and baseline > 0:
		row.expected_litres = flt(row.distance * baseline, 2)
		row.variance = flt(row.measured_litres - row.expected_litres, 2)

	if not row.fills:
		row.status = _("No Fuel Drawn")
	else:
		row.status = summary_status(row, observed, baseline)
	row.status_note = status_note(row.status)
	row.pop("backwards_readings", None)


def status_note(status):
	"""One line saying what a row's status means."""
	if status == _("No Fuel Drawn"):
		return _("Stationed here, but no fuel was dispensed to it in this period.")
	return summary_note(status)


def get_resources(filters):
	"""Resources in scope, keyed by name.

	The site is where the resource is *stationed*, as on the Resource Fuel
	Summary: the sheet lists the site's own fleet, and filtering on the site
	keyed on each fill would show a resource only on the days it happened to
	be fuelled there.
	"""
	conditions = {}
	if filters.get("site"):
		conditions["stationed_site"] = ["in", as_list(filters.site)]
	if filters.get("resource_type"):
		conditions["resource_type"] = filters.resource_type
	if filters.get("resource"):
		conditions["name"] = ["in", as_list(filters.resource)]

	rows = frappe.get_all(
		"Resource",
		filters=conditions,
		fields=["name", "reg_no", "resource_type", "stationed_site", "average_consumption"],
	)
	return {row.name: row for row in rows}


def get_message(filters):
	site = ", ".join(as_list(filters.site)) if filters.get("site") else _("All Sites")
	title = _("Summary of Fuel Dispensed at {0}").format(frappe.bold(frappe.utils.escape_html(site)))
	period = _("{0} to {1}").format(format_date(filters.from_date), format_date(filters.to_date))
	return f"<div style='text-align:center'><h5>{title}</h5><p class='text-muted'>{period}</p></div>"

