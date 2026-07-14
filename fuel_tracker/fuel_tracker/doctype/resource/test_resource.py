# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from fuel_tracker.tests.utils import dispense, make_resource, make_tanker, supply

test_ignore = ["Item", "Company"]


class TestResource(FrappeTestCase):
	def test_reading_locked_after_first_set(self):
		truck = make_resource("TEST-FT-RES-1", "Truck", reading=0)

		# setting the initial reading from empty is allowed
		truck.current_odometer = 100
		truck.save()

		# changing an established reading by hand is not
		truck.current_odometer = 120
		with self.assertRaises(frappe.ValidationError):
			truck.save()

		eq = make_resource("TEST-FT-RES-2", "Equipment", reading=50)
		eq.current_hours = 60
		with self.assertRaises(frappe.ValidationError):
			eq.save()

	def test_fuel_flow_still_updates_locked_reading(self):
		tanker = make_tanker("TEST-FT-RES-3").name
		supply(tanker, 100)
		truck = make_resource("TEST-FT-RES-TRK1", "Truck", reading=100).name

		dispense(tanker, truck, 10, odometer_km=150)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 150)

	def test_reset_reading_updates_and_logs(self):
		truck = make_resource("TEST-FT-RES-5", "Truck", reading=150)

		# resets may go backwards (meter replacement) despite the lock
		truck.reset_reading(60, "odometer replaced")
		self.assertEqual(frappe.db.get_value("Resource", truck.name, "current_odometer"), 60)
		comments = frappe.get_all("Comment",
			filters={"reference_doctype": "Resource", "reference_name": truck.name},
			pluck="content")
		self.assertTrue(any("odometer replaced" in c for c in comments))

		eq = make_resource("TEST-FT-RES-6", "Equipment", reading=500)
		eq.reset_reading(0, "hour meter reset")
		self.assertEqual(frappe.db.get_value("Resource", eq.name, "current_hours"), 0)

	def test_reset_reading_requires_reason_and_change(self):
		truck = make_resource("TEST-FT-RES-7", "Truck", reading=100)
		with self.assertRaises(frappe.ValidationError):
			truck.reset_reading(50, "")
		with self.assertRaises(frappe.ValidationError):
			truck.reset_reading(100, "same value")
		with self.assertRaises(frappe.ValidationError):
			truck.reset_reading(-5, "negative")

	def test_reset_reading_system_manager_only(self):
		truck = make_resource("TEST-FT-RES-8", "Truck", reading=100)
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				truck.reset_reading(50, "not allowed")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Resource", truck.name, "current_odometer"), 100)

	def test_delete_blocked_after_submitted_use(self):
		tanker = make_tanker("TEST-FT-RES-4").name
		supply(tanker, 100)
		truck = make_resource("TEST-FT-RES-TRK2", "Truck", reading=100).name
		dispense(tanker, truck, 10, odometer_km=150)

		# the on_trash guard runs before frappe's link check and blocks
		# normal and force deletes alike
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Resource", truck)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Resource", truck, force=1)
