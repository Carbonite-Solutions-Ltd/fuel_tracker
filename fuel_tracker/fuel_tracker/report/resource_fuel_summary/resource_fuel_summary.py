# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""One line per resource: fuel drawn, distance covered, consumption achieved.

The Average Fuel Consumption Ledger scores every individual fill, which is the
right grain for spotting a single suspicious issue but too fine to see how a
vehicle is behaving overall. This aggregates a period into one row per
resource and derives the consumption actually *observed* over that period.

That observed figure is what a baseline should be set from, so it has to be
measured exactly the way the ledger alerts against it. It is therefore built
from the ledger's own scored fills (`fuel_tracker.consumption`): the litres
attributed to each scored fill over the distance it covered — the
distance-weighted result of the ledger's rows. Dividing *all* litres drawn by
*all* distance instead counted fuel not yet burned (the last fill) and
distance covered on fuel from before the period (the first), and disagreed
with the ledger by more than 10% on most resources.

Fills that cannot be scored — a faulty meter, a first fill, a reading that
went backwards — still count towards the litres drawn, but stay out of the
consumption maths rather than silently skewing it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from fuel_tracker.fuel_tracker.consumption import PRECISION, as_list, band, get_fills, in_period
from fuel_tracker.fuel_tracker.resource_ledger import READING_FIELDS


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data


def get_columns():
	return [
		{"label": _("Resource"), "fieldname": "resource", "fieldtype": "Link", "options": "Resource", "width": 190},
		{"label": _("Type"), "fieldname": "resource_type", "fieldtype": "Data", "width": 100},
		{"label": _("Reg. No"), "fieldname": "reg_no", "fieldtype": "Data", "width": 120},
		{"label": _("Stationed Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 170},
		{"label": _("Fills"), "fieldname": "fills", "fieldtype": "Int", "width": 80},
		{"label": _("Litres Drawn"), "fieldname": "litres", "fieldtype": "Float", "width": 120},
		{"label": _("Measured Litres"), "fieldname": "measured_litres", "fieldtype": "Float", "width": 130},
		{"label": _("Measured Distance / Hours"), "fieldname": "distance", "fieldtype": "Float", "width": 180},
		{"label": _("Observed"), "fieldname": "observed_consumption", "fieldtype": "Float", "precision": 4, "width": 120},
		{"label": _("Baseline"), "fieldname": "average_consumption", "fieldtype": "Float", "precision": 4, "width": 110},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Float", "precision": 4, "width": 110},
		{"label": _("Variance %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Unmetered Fills"), "fieldname": "faulty_fills", "fieldtype": "Int", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
	]


def get_data(filters):
	fills = get_fills(
		resource=filters.get("resource"),
		resource_type=filters.get("resource_type"),
		to_date=filters.get("to_date"),
	)
	# A per-resource report, so the site is where the resource is stationed.
	# Filtering on the site keyed on each fill would score a resource on
	# whichever of its fills happened there — a broken sequence.
	sites = set(as_list(filters.get("site"))) if filters.get("site") else None

	rows = {}
	for fill in fills:
		if not in_period(fill, filters.get("from_date"), filters.get("to_date")):
			continue
		if sites and fill.stationed_site not in sites:
			continue

		row = rows.get(fill.resource)
		if not row:
			row = rows[fill.resource] = frappe._dict(
				resource=fill.resource,
				resource_type=fill.resource_type,
				reg_no=fill.reg_no,
				site=fill.stationed_site,
				average_consumption=flt(fill.average_consumption),
				fills=0,
				litres=0.0,
				measured_litres=0.0,
				distance=0.0,
				faulty_fills=0,
				backwards_readings=0,
			)

		row.fills += 1
		row.litres += flt(fill.litres_in)
		if fill.meter_faulty:
			row.faulty_fills += 1
		if fill.backwards:
			row.backwards_readings += 1
		if fill.scored:
			row.measured_litres += flt(fill.litres)
			row.distance += flt(fill.distance)

	data = []
	for row in sorted(rows.values(), key=lambda r: r.litres, reverse=True):
		baseline = flt(row.average_consumption)
		observed = flt(row.measured_litres / row.distance, PRECISION) if row.distance > 0 else 0

		row.litres = flt(row.litres, PRECISION)
		row.measured_litres = flt(row.measured_litres, PRECISION)
		row.distance = flt(row.distance, PRECISION)
		row.observed_consumption = observed
		row.status = get_status(row, observed, baseline)

		if observed and baseline > 0:
			row.variance = flt(observed - baseline, PRECISION)
			row.variance_pct = flt((observed - baseline) / baseline * 100, 2)

		if filters.get("only_without_baseline") and baseline > 0:
			continue

		data.append(row)

	return data


def get_status(row, observed, baseline):
	if row.backwards_readings:
		return _("Check Readings")
	if row.resource_type not in READING_FIELDS:
		return _("Not Metered")
	if not observed:
		return _("Not Measurable")
	if baseline <= 0:
		# The point of this report: no baseline means nothing is being alerted
		# on, and the Observed column is the figure to set it from.
		return _("Set Baseline")
	return band(observed, baseline)
