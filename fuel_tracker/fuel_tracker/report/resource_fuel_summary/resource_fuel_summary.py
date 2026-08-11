# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""One line per resource: fuel drawn, distance covered, consumption achieved.

The Average Fuel Consumption Ledger scores every individual fill, which is the
right grain for spotting a single suspicious issue but too fine to see how a
vehicle is behaving overall. This aggregates a period into one row per
resource and, crucially, derives the consumption actually *observed* over that
period — total litres divided by total distance.

That observed figure is what a baseline should be set from. Until a resource
carries an `average_consumption`, the alerting in the consumption ledger has
nothing to compare against and every row falls through as "No Baseline", so
this report doubles as the worksheet for populating them: run it over a
representative period, and the Observed column is the number to enter.

Fills recorded against a faulty meter contribute their litres but no distance,
so they are counted separately and excluded from the consumption maths rather
than silently deflating it.
"""

import frappe
from frappe import _
from frappe.utils import flt

#: Litres per km is a small number; two decimals would round it to nothing.
PRECISION = 4


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data


def get_columns():
	return [
		{"label": _("Resource"), "fieldname": "resource", "fieldtype": "Link", "options": "Resource", "width": 190},
		{"label": _("Type"), "fieldname": "resource_type", "fieldtype": "Data", "width": 100},
		{"label": _("Reg. No"), "fieldname": "reg_no", "fieldtype": "Data", "width": 120},
		{"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 170},
		{"label": _("Fills"), "fieldname": "fills", "fieldtype": "Int", "width": 80},
		{"label": _("Litres"), "fieldname": "litres", "fieldtype": "Float", "width": 110},
		{"label": _("Distance / Hours"), "fieldname": "distance", "fieldtype": "Float", "width": 140},
		{"label": _("Observed"), "fieldname": "observed_consumption", "fieldtype": "Float", "precision": 4, "width": 120},
		{"label": _("Baseline"), "fieldname": "average_consumption", "fieldtype": "Float", "precision": 4, "width": 110},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Float", "precision": 4, "width": 110},
		{"label": _("Variance %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Unmetered Fills"), "fieldname": "faulty_fills", "fieldtype": "Int", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
	]


def get_data(filters):
	conditions = ["fe.docstatus = 1", "fe.utilization_type = 'Dispensed'", "fe.resource IS NOT NULL"]
	values = {}

	if filters.get("from_date"):
		conditions.append("fe.date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		conditions.append("fe.date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("resource_type"):
		conditions.append("fe.resource_type = %(resource_type)s")
		values["resource_type"] = filters.get("resource_type")
	if filters.get("site"):
		conditions.append("fe.site IN %(site)s")
		values["site"] = tuple(as_list(filters.get("site")))
	if filters.get("resource"):
		conditions.append("fe.resource IN %(resource)s")
		values["resource"] = tuple(as_list(filters.get("resource")))

	rows = frappe.db.sql(
		"""
		SELECT
			fe.resource,
			fe.resource_type,
			MAX(r.reg_no) AS reg_no,
			MAX(r.stationed_site) AS site,
			MAX(r.average_consumption) AS average_consumption,
			COUNT(*) AS fills,
			SUM(fe.litres_dispensed) AS litres,
			SUM(CASE WHEN IFNULL(fe.meter_faulty, 0) = 1 THEN 1 ELSE 0 END) AS faulty_fills,
			-- Only metered fills contribute distance, and a negative diff means
			-- the reading went backwards, which is bad data rather than travel.
			SUM(CASE WHEN IFNULL(fe.meter_faulty, 0) = 0 AND fe.diff_odometer > 0
					 THEN fe.diff_odometer ELSE 0 END) AS distance_km,
			SUM(CASE WHEN IFNULL(fe.meter_faulty, 0) = 0 AND fe.diff_hours_copy > 0
					 THEN fe.diff_hours_copy ELSE 0 END) AS distance_hours,
			SUM(CASE WHEN IFNULL(fe.meter_faulty, 0) = 0
					  AND (fe.diff_odometer < 0 OR fe.diff_hours_copy < 0)
					 THEN 1 ELSE 0 END) AS backwards_readings
		FROM `tabFuel Entry` fe
		LEFT JOIN `tabResource` r ON r.name = fe.resource
		WHERE {conditions}
		GROUP BY fe.resource, fe.resource_type
		ORDER BY SUM(fe.litres_dispensed) DESC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	data = []
	for row in rows:
		distance = flt(row.distance_hours if row.resource_type == "Equipment" else row.distance_km)
		litres = flt(row.litres)
		baseline = flt(row.average_consumption)

		observed = flt(litres / distance, PRECISION) if distance > 0 else 0
		row["distance"] = distance
		row["observed_consumption"] = observed
		row["status"] = get_status(row, observed, baseline)

		if observed and baseline > 0:
			row["variance"] = flt(observed - baseline, PRECISION)
			row["variance_pct"] = flt((observed - baseline) / baseline * 100, 2)

		if filters.get("only_without_baseline") and baseline > 0:
			continue

		data.append(row)

	return data


def get_status(row, observed, baseline):
	if row.backwards_readings:
		return _("Check Readings")
	if not observed:
		return _("Not Measurable")
	if baseline <= 0:
		# The point of this report: no baseline means nothing is being alerted
		# on, and the Observed column is the figure to set it from.
		return _("Set Baseline")

	variance_pct = (observed - baseline) / baseline * 100
	if variance_pct > 20:
		return _("High Alert")
	if variance_pct > 10:
		return _("Warning")
	if variance_pct > 0:
		return _("Above Average")
	return _("Good")


def as_list(value):
	return value if isinstance(value, (list, tuple)) else [value]
