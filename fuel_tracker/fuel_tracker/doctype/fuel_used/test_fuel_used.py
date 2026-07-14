# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from fuel_tracker.tests.utils import balance, dispense, entry_for, make_resource, make_tanker, messages_text, supply

test_ignore = ["Item", "Company"]


class TestFuelUsed(FrappeTestCase):
	def test_truck_dispense_updates_ledger_and_resource(self):
		tanker = make_tanker("TEST-FT-FU-1").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FU-TRK1", "Truck", reading=1000).name

		doc = dispense(tanker, truck, 50, odometer_km=1100)

		self.assertEqual(balance(tanker), 450)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1100)
		entry = entry_for(doc)
		self.assertEqual(entry.utilization_type, "Dispensed")
		self.assertEqual(entry.litres_dispensed, 50)
		self.assertEqual(entry.diff_odometer, 100)

	def test_equipment_dispense_updates_hours(self):
		tanker = make_tanker("TEST-FT-FU-2").name
		supply(tanker, 500)
		eq = make_resource("TEST-FT-FU-EQ1", "Equipment", reading=100).name

		doc = dispense(tanker, eq, 30, hours_copy=110)

		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 110)
		self.assertEqual(entry_for(doc).diff_hours_copy, 10)

	def test_stale_draft_refreshes_previous_reading(self):
		tanker = make_tanker("TEST-FT-FU-3").name
		supply(tanker, 500)
		eq = make_resource("TEST-FT-FU-EQ2", "Equipment", reading=100).name

		stale = dispense(tanker, eq, 50, hours_copy=110, submit=False)
		dispense(tanker, eq, 30, hours_copy=105)  # moves the live reading to 105
		stale.submit()
		stale.reload()

		# the draft's previous reading must be re-read from the live resource
		self.assertEqual(stale.previous_hours_copy, 105)
		self.assertEqual(entry_for(stale).diff_hours_copy, 5)
		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 110)

	def test_reading_below_live_blocked(self):
		tanker = make_tanker("TEST-FT-FU-4").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FU-TRK2", "Truck", reading=1200).name

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 20, odometer_km=1150)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1200)

	def test_zero_and_negative_litres_blocked(self):
		tanker = make_tanker("TEST-FT-FU-5").name
		truck = make_resource("TEST-FT-FU-TRK3", "Truck", reading=100).name
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 0, odometer_km=200)
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, -10, odometer_km=200)

	def test_overdraw_warning_is_non_blocking(self):
		tanker = make_tanker("TEST-FT-FU-6").name
		supply(tanker, 10)
		truck = make_resource("TEST-FT-FU-TRK4", "Truck", reading=100).name

		frappe.clear_messages()
		doc = dispense(tanker, truck, 50, odometer_km=200)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), -40)
		self.assertIn("exceeds the current balance", messages_text())

	def test_missing_previous_reading_blocked(self):
		# the resource must carry an initial reading before fuel can be
		# dispensed against it
		tanker = make_tanker("TEST-FT-FU-8").name
		supply(tanker, 100)
		truck = make_resource("TEST-FT-FU-TRK6", "Truck", reading=0).name
		eq = make_resource("TEST-FT-FU-EQ3", "Equipment", reading=0).name

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 10, odometer_km=500)
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, eq, 10, hours_copy=50)

	def test_quantity_and_current_reading_mandatory(self):
		tanker = make_tanker("TEST-FT-FU-9").name
		truck = make_resource("TEST-FT-FU-TRK7", "Truck", reading=100).name
		site = frappe.db.get_value("Fuel Tanker", tanker, "site")

		# the fuel quantity is hard-mandatory, even for drafts
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({
				"doctype": "Fuel Used", "date": today(), "fuel_tanker": tanker,
				"site": site, "resource": truck, "odometer_km": 200,
			}).insert()

		# a draft without the current reading may exist (incoming mobile
		# reports), but it cannot be submitted
		doc = frappe.get_doc({
			"doctype": "Fuel Used", "date": today(), "fuel_tanker": tanker,
			"site": site, "resource": truck, "fuel_issued_lts": 10,
		})
		doc.insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_below_minimum_level_warning(self):
		tanker = make_tanker("TEST-FT-FU-7", minimum_level=100).name
		supply(tanker, 150)
		truck = make_resource("TEST-FT-FU-TRK5", "Truck", reading=100).name

		frappe.clear_messages()
		doc = dispense(tanker, truck, 100, odometer_km=200)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 50)
		self.assertIn("minimum level", messages_text())
