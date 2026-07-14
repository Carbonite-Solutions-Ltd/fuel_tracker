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
