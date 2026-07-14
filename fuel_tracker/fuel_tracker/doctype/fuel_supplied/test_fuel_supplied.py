# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from fuel_tracker.tests.utils import balance, entry_for, ensure_site, make_tanker, messages_text, supply

test_ignore = ["Item", "Company"]


class TestFuelSupplied(FrappeTestCase):
	def test_submit_creates_ledger_entry_and_balance(self):
		tanker = make_tanker("TEST-FT-SUP-1").name
		doc = supply(tanker, 500)

		self.assertEqual(balance(tanker), 500)
		# the lazily created balance stays a draft (opening seeding is a user action)
		self.assertEqual(frappe.db.get_value("Fuel Balance", tanker, "docstatus"), 0)

		entry = entry_for(doc)
		self.assertIsNotNone(entry)
		self.assertEqual(entry.utilization_type, "Supplied")
		self.assertEqual(entry.litres_supplied, 500)
		self.assertEqual(entry.previous_balance, 0)
		self.assertEqual(entry.current_balance, 500)

	def test_zero_and_negative_supply_blocked(self):
		tanker = make_tanker("TEST-FT-SUP-2").name
		with self.assertRaises(frappe.ValidationError):
			supply(tanker, 0)
		with self.assertRaises(frappe.ValidationError):
			supply(tanker, -50)

	def test_threshold_warning_is_non_blocking(self):
		tanker = make_tanker("TEST-FT-SUP-3", threshold=100).name
		frappe.clear_messages()
		doc = supply(tanker, 200)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 200)
		self.assertIn("maximum threshold", messages_text())

	def test_mandatory_fields(self):
		site = ensure_site()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "Fuel Supplied", "date": today(), "site": site, "fuel_supplied": 10,
			}).insert()

		tanker = make_tanker("TEST-FT-SUP-4").name
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({
				"doctype": "Fuel Supplied", "fuel_tanker": tanker, "site": site, "fuel_supplied": 10,
			}).insert()
