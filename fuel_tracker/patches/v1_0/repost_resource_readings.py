# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Rebuild every resource's odometer / hour-meter sequence in posting order.

Readings used to be measured from whatever the `Resource` happened to hold at
the moment a `Fuel Used` was submitted, rather than from the fill recorded
before it. Any document entered out of order therefore recorded its distance
from the wrong point — and that distance is what the consumption report
divides litres by, so the resulting km/L was wrong for those rows.

Walking each resource in posting order rewrites every stored previous reading
and every distance on the ledger, and leaves the resource holding the newest
reading. This runs as its own patch rather than inside
`backfill_posting_datetime` so sites that already applied that one still pick
the repair up.
"""

import frappe


def execute():
	backfill_fuel_used_posting_datetime()
	repost_all_resource_readings()


def backfill_fuel_used_posting_datetime():
	"""Give Fuel Used the sort key the reading sequence is ordered by."""
	if not frappe.db.has_column("Fuel Used", "posting_datetime"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabFuel Used`
		SET posting_time = TIME(creation)
		WHERE posting_time IS NULL
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabFuel Used`
		SET posting_datetime = TIMESTAMP(date, posting_time)
		WHERE date IS NOT NULL
		"""
	)


def repost_all_resource_readings():
	from fuel_tracker.fuel_tracker.resource_ledger import repost_resource_readings

	rows = frappe.get_all(
		"Fuel Used",
		filters={"docstatus": 1},
		distinct=True,
		fields=["resource", "resource_type"],
	)
	resources = {row.resource: row.resource_type for row in rows if row.resource}

	for resource, resource_type in resources.items():
		repost_resource_readings(resource, resource_type)

	# No commit: the patch runner commits on success and rolls back on failure.
	print("Reposted odometer/hour readings for {0} resource(s).".format(len(resources)))
