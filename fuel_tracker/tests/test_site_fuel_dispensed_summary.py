# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from fuel_tracker.fuel_tracker.report.site_fuel_dispensed_summary.site_fuel_dispensed_summary import (
	day_field,
	execute,
)
from fuel_tracker.tests.utils import dispense, ensure_site, make_resource, make_tanker, supply

test_ignore = ["Item", "Company"]

FROM, TO = "2026-10-01", "2026-10-31"


def stationed(resource, site):
	frappe.db.set_value("Resource", resource, "stationed_site", site)
	return resource


def run(**filters):
	filters = {"from_date": FROM, "to_date": TO, **filters}
	columns, data, _message = execute(filters)
	return columns, {row.resource: row for row in data}


class TestSiteFuelDispensedSummary(FrappeTestCase):
	def test_litres_are_laid_out_per_day_and_totalled(self):
		site = ensure_site("TEST-FT-SDS-SITE1")
		tanker = make_tanker("TEST-FT-SDS-T1", site=site).name
		supply(tanker, 5000, date="2026-10-01", posting_time="06:00:00")
		truck = stationed(make_resource("TEST-FT-SDS-TRK1", "Truck", reading=1000).name, site)

		dispense(tanker, truck, 100, odometer_km=1100, date="2026-10-02", posting_time="08:00:00")
		dispense(tanker, truck, 50, odometer_km=1150, date="2026-10-02", posting_time="15:00:00")
		dispense(tanker, truck, 80, odometer_km=1250, date="2026-10-05", posting_time="08:00:00")

		columns, rows = run(site=site)
		row = rows[truck]

		self.assertEqual(len([c for c in columns if c["fieldname"].startswith("d_")]), 31)
		self.assertEqual(row[day_field("2026-10-02")], 150, "two fills on one day are added together")
		self.assertEqual(row[day_field("2026-10-05")], 80)
		self.assertNotIn(day_field("2026-10-03"), row, "a day with no fill stays blank, not 0")
		self.assertEqual(row.total_litres, 230)
		self.assertEqual(row.fills, 3)

	def test_lists_the_sites_fleet_only(self):
		site = ensure_site("TEST-FT-SDS-SITE2")
		other = ensure_site("TEST-FT-SDS-SITE2B")
		tanker = make_tanker("TEST-FT-SDS-T2", site=site).name
		supply(tanker, 5000, date="2026-10-01", posting_time="06:00:00")
		fuelled = stationed(make_resource("TEST-FT-SDS-EQ2A", "Equipment", reading=10).name, site)
		idle = stationed(make_resource("TEST-FT-SDS-EQ2B", "Equipment", reading=10).name, site)
		elsewhere = stationed(make_resource("TEST-FT-SDS-EQ2C", "Equipment", reading=10).name, other)

		dispense(tanker, fuelled, 40, hours_copy=20, date="2026-10-03", posting_time="08:00:00")
		dispense(tanker, elsewhere, 40, hours_copy=20, date="2026-10-03", posting_time="09:00:00")

		_cols, rows = run(site=site)
		self.assertIn(fuelled, rows)
		self.assertNotIn(elsewhere, rows, "fuelled from this site's tanker, but stationed elsewhere")
		self.assertIn(idle, rows, "the sheet lists the whole fleet, fuelled or not")
		self.assertEqual(rows[idle].status, "No Fuel Drawn")
		self.assertTrue(rows[idle].status_note)

		_cols, rows = run(site=site, show_idle=0)
		self.assertNotIn(idle, rows)

	def test_consumption_is_measured_tank_to_tank(self):
		site = ensure_site("TEST-FT-SDS-SITE3")
		tanker = make_tanker("TEST-FT-SDS-T3", site=site).name
		supply(tanker, 5000, date="2026-10-01", posting_time="06:00:00")
		eq = stationed(
			make_resource("TEST-FT-SDS-EQ3", "Equipment", reading=100, average_consumption=5).name, site
		)

		dispense(tanker, eq, 100, hours_copy=110, date="2026-10-05", posting_time="08:00:00")
		dispense(tanker, eq, 50, hours_copy=120, date="2026-10-10", posting_time="08:00:00")

		_cols, rows = run(site=site)
		row = rows[eq]

		self.assertEqual(row.total_litres, 150)
		# Only the second fill measures an interval: 100 L burned over 10 h.
		# All litres over all hours (150 / 20) would count the 50 L not yet burned.
		self.assertEqual(row.measured_litres, 100)
		self.assertEqual(row.distance, 10)
		self.assertEqual(row.actual_consumption, 10)
		self.assertEqual(row.expected_litres, 50)  # 10 h at the 5 L/h baseline
		self.assertEqual(row.variance, 50)
		self.assertEqual(row.status, "High Alert")

	def test_refuses_a_period_too_long_to_lay_out_by_day(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"from_date": "2026-01-01", "to_date": "2026-06-30"})
