# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from fuel_tracker.fuel_tracker.report.average_fuel_consumption_ledger.average_fuel_consumption_ledger import (
	execute as avg_execute,
)
from fuel_tracker.fuel_tracker.report.fuel_balance.fuel_balance import execute as fb_execute
from fuel_tracker.fuel_tracker.report.fuel_ledger.fuel_ledger import execute as fl_execute
from fuel_tracker.tests.utils import adjust, balance, dispense, make_resource, make_tanker, supply

test_ignore = ["Item", "Company"]


def submit_opening_balance(tanker, opening):
	doc = frappe.get_doc({
		"doctype": "Fuel Balance",
		"fuel_tanker": tanker,
		"balance": opening,
		"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		"date": today(),
	})
	doc.insert()
	doc.submit()
	return doc


class TestReports(FrappeTestCase):
	def test_fuel_balance_report_tallies_with_doctype(self):
		tanker = make_tanker("TEST-FT-RPT-1", minimum_level=1000).name
		submit_opening_balance(tanker, 200)
		supply(tanker, 120)
		truck = make_resource("TEST-FT-RPT-TRK1", "Truck", reading=100).name
		dispense(tanker, truck, 30, odometer_km=200)
		adjust(tanker, mode="Quantity", quantity=-40)

		_, rows = fb_execute(frappe._dict({"date": today(), "fuel_tanker": [tanker]}))
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["opening_entry"], 200)
		self.assertEqual(row["litres_supplied"], 120)
		self.assertEqual(row["litres_dispensed"], 30)
		self.assertEqual(row["litres_adjusted"], -40)
		self.assertEqual(row["current_balance"], 250)
		self.assertEqual(row["current_balance"], balance(tanker))
		# balance 250 < minimum_level 1000
		self.assertEqual(row["status"], "Low")

	def test_fuel_balance_report_status_ok(self):
		tanker = make_tanker("TEST-FT-RPT-2", minimum_level=5).name
		supply(tanker, 100)

		_, rows = fb_execute(frappe._dict({"date": today(), "fuel_tanker": [tanker]}))
		self.assertEqual(rows[0]["status"], "OK")

	def test_fuel_ledger_report_rows_totals_and_order(self):
		tanker = make_tanker("TEST-FT-RPT-3").name
		submit_opening_balance(tanker, 200)
		supply(tanker, 120)
		truck = make_resource("TEST-FT-RPT-TRK2", "Truck", reading=100).name
		dispense(tanker, truck, 30, odometer_km=200)
		adjust(tanker, mode="Quantity", quantity=-40)

		_, rows = fl_execute(frappe._dict({"fuel_tanker": [tanker]}))
		data_rows, total_row = rows[:-1], rows[-1]

		self.assertEqual(len(data_rows), 4)
		self.assertEqual({r["utilization_type"] for r in data_rows},
			{"Opening Balance", "Supplied", "Dispensed", "Adjustment"})
		self.assertEqual(total_row["litres_supplied"], 120)
		self.assertEqual(total_row["litres_dispensed"], 30)
		self.assertEqual(total_row["litres_adjusted"], -40)

		names = [r["name"] for r in data_rows]
		self.assertEqual(names, sorted(names))  # chronological (same date -> entry order)

	def test_average_consumption_alert_bands(self):
		tanker = make_tanker("TEST-FT-RPT-4").name
		supply(tanker, 10000)

		# consumption = previous fill's litres / current interval's hours diff;
		# every resource gets two fills with a 10 h interval, so the first
		# fill's litres set the band: avg 10 L/h -> 100 L = 10.0 (Good),
		# 105 L = 10.5 (+5%, Above Average), 115 L = 11.5 (+15%, Warning),
		# 130 L = 13.0 (+30%, High Alert); avg 0 -> No Baseline.
		bands = {
			"TEST-FT-RPT-EQ-GOOD": (10, 100, "Good"),
			"TEST-FT-RPT-EQ-ABOVE": (10, 105, "Above Average"),
			"TEST-FT-RPT-EQ-WARN": (10, 115, "Warning"),
			"TEST-FT-RPT-EQ-HIGH": (10, 130, "High Alert"),
			"TEST-FT-RPT-EQ-NOBASE": (0, 50, "No Baseline"),
		}
		for chassis, (avg, first_fill, _expected) in bands.items():
			make_resource(chassis, "Equipment", reading=100, average_consumption=avg)
			dispense(tanker, chassis, first_fill, hours_copy=110)
			dispense(tanker, chassis, 10, hours_copy=120)

		_, rows = avg_execute(frappe._dict({}))
		for chassis, (_avg, first_fill, expected) in bands.items():
			matches = [r for r in rows
				if r["resource"] == chassis and r["litres_dispensed"] == first_fill]
			self.assertEqual(len(matches), 1, f"expected one second-fill row for {chassis}")
			self.assertEqual(matches[0]["alert_status"], expected, f"band for {chassis}")
