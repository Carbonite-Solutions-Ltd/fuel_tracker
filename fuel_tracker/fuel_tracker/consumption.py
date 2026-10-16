# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Tank-to-tank fuel consumption, shared by every consumption report.

The Average Fuel Consumption Ledger scores individual fills and the Resource
Fuel Summary rolls a period up into one figure per resource. They used to
compute consumption separately — the summary as *all* litres over *all*
distance in the period — and disagreed by more than 10% on most resources.
That mattered, because the summary is where baselines are set and the ledger
is where they are alerted on: a baseline taken from one method raised false
alerts in the other. Both now read the same per-fill figures from here, and
the summary's figure is simply the distance-weighted result of the ledger's.

A metered fill is scored as the litres put in since the previous *metered*
fill — that fill, plus any faulty-meter fills in between, whose fuel was
burned over the same stretch — divided by the distance recorded since it.
Only counting the single previous fill halved the figure whenever a faulty
fill sat in between, which is precisely the pattern that hides fuel going
missing.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from fuel_tracker.fuel_tracker.resource_ledger import READING_FIELDS

#: Litres per km on a truck is a small number, so two decimals would round a
#: genuine reading away to zero and leave the row looking unscored.
PRECISION = 4


def get_fills(resource=None, resource_type=None, to_date=None):
	"""Every submitted dispense with its tank-to-tank figures, oldest first.

	Each resource's history is walked from its very first fill regardless of
	any report period: the first fill inside a period is scored with the fuel
	put in *before* the period, so the walk cannot start at the boundary.
	Fills after `to_date` cannot change the score of anything before it, so
	the walk stops there.

	Every row gains `litres` (fuel attributed to the interval), `distance`,
	`consumption`, `status`, `scored` (a real figure was produced) and
	`backwards` (the reading went down).
	"""
	conditions = [
		"fe.docstatus = 1",
		"fe.utilization_type = 'Dispensed'",
		"IFNULL(fe.resource, '') != ''",
	]
	values = {}

	if resource:
		conditions.append("fe.resource IN %(resource)s")
		values["resource"] = tuple(as_list(resource))
	if resource_type:
		conditions.append("IFNULL(r.resource_type, fe.resource_type) = %(resource_type)s")
		values["resource_type"] = resource_type
	if to_date:
		conditions.append("fe.date <= %(to_date)s")
		values["to_date"] = getdate(to_date)

	entries = frappe.db.sql(
		"""
		SELECT
			fe.name, fe.date, fe.posting_datetime, fe.creation, fe.resource,
			IFNULL(r.resource_type, fe.resource_type) AS resource_type,
			r.reg_no, r.stationed_site, IFNULL(r.average_consumption, 0) AS average_consumption,
			fe.site, fe.fuel_tanker, fe.utilization_type, fe.litres_dispensed AS litres_in,
			fe.diff_odometer, fe.diff_hours_copy, IFNULL(fe.meter_faulty, 0) AS meter_faulty,
			fe.fuel_utilization_id, fu.odometer_km, fu.hours_copy
		FROM `tabFuel Entry` fe
		LEFT JOIN `tabResource` r ON r.name = fe.resource
		LEFT JOIN `tabFuel Used` fu ON fu.name = fe.fuel_utilization_id
		WHERE {conditions}
		ORDER BY fe.resource, fe.posting_datetime, fu.creation, fe.creation
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	current = None
	for entry in entries:
		if entry.resource != current:
			# litres put in since the last metered fill, waiting to be scored
			current, pending, metered_before = entry.resource, 0.0, False

		fields = READING_FIELDS.get(entry.resource_type)
		entry.distance = flt(entry.get(fields[2])) if fields else 0.0
		entry.litres = 0.0
		entry.backwards = False

		if not fields:
			# "Others" carry no meter at all, so there is nothing to measure
			# against — not the same thing as a machine that stood idle.
			entry.consumption, entry.status = 0, _("Not Metered")
		elif entry.meter_faulty:
			# No reading, so this fill cannot be scored itself — but its fuel
			# was burned over the stretch the next metered fill measures.
			entry.consumption, entry.status = 0, _("Meter Faulty")
			if metered_before:
				pending += flt(entry.litres_in)
		else:
			entry.litres = pending if metered_before else 0.0
			entry.backwards = entry.distance < 0
			entry.consumption, entry.status = score(
				entry.litres, entry.distance, flt(entry.average_consumption), first=not metered_before
			)
			pending, metered_before = flt(entry.litres_in), True

		entry.scored = bool(entry.consumption)

	return entries


def score(litres, distance, baseline, first=False):
	"""Consumption for one interval, and the band it falls in.

	Returns `(consumption, status)`. Anything that cannot honestly be scored
	gets a status naming the reason rather than a zero that reads like a
	measurement — a blank or a 0.00 km/L is indistinguishable from a real
	result, and that is how bad meter data hides.
	"""
	if distance < 0:
		# The reading went *down* between fills — a mis-keyed odometer, a
		# replaced meter, or two machines sharing a record.
		return 0, _("Check Reading")

	if first:
		# No earlier metered fill, so there is no tank-to-tank interval: the
		# distance since the opening reading was covered on unknown fuel.
		return 0, _("First Fill")

	if not distance:
		# Measured, but the resource had not moved: consumption is undefined
		# rather than zero.
		return 0, _("No Movement")

	consumption = flt(litres / distance, PRECISION)
	return consumption, band(consumption, baseline)


def band(consumption, baseline):
	"""Where a consumption figure falls against the resource's baseline."""
	if baseline <= 0:
		return _("No Baseline")

	# Below the baseline means burning less than expected, which is good.
	if consumption <= baseline:
		return _("Good")

	variance_pct = (consumption - baseline) / baseline * 100
	if variance_pct > 20:
		return _("High Alert")
	if variance_pct > 10:
		return _("Warning")
	return _("Above Average")


def status_note(status):
	"""One line saying what a consumption status means, for the reports."""
	return {
		_("Good"): _("Burned no more fuel than the resource's baseline."),
		_("Above Average"): _("Up to 10% over the baseline — normal variation."),
		_("Warning"): _("10–20% over the baseline — keep an eye on this resource."),
		_("High Alert"): _("More than 20% over the baseline — check for leaks, theft or a mis-keyed fill."),
		_("No Baseline"): _("Measured, but the resource has no Average Consumption set to compare against."),
		_("First Fill"): _("No earlier metered fill, so there is no interval to measure yet."),
		_("No Movement"): _("The reading has not changed since the last fill, so consumption cannot be worked out."),
		_("Meter Faulty"): _("Fuelled without a reading because the meter is flagged faulty — not scored."),
		_("Check Reading"): _("The reading is lower than the one before it — likely a typing error or a replaced meter."),
		_("Not Metered"): _("This resource has no odometer or hour meter, so it is never scored."),
	}.get(status, "")


def in_period(entry, from_date=None, to_date=None):
	if from_date and entry.date < getdate(from_date):
		return False
	if to_date and entry.date > getdate(to_date):
		return False
	return True


def as_list(value):
	return value if isinstance(value, (list, tuple)) else [value]
