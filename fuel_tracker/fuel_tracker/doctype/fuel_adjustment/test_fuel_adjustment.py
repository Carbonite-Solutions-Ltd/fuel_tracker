# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from fuel_tracker.tests.utils import adjust, balance, entry_for, make_tanker, messages_text, supply

test_ignore = ["Item", "Company"]


class TestFuelAdjustment(FrappeTestCase):
	def test_measured_mode_without_existing_balance(self):
		tanker = make_tanker("TEST-FT-ADJ-1").name
		doc = adjust(tanker, mode="Measured Balance", measured=50)
		doc.reload()

		self.assertEqual(doc.system_balance, 0)
		self.assertEqual(doc.adjustment_litres, 50)
		self.assertEqual(balance(tanker), 50)
		entry = entry_for(doc)
		self.assertEqual(entry.utilization_type, "Adjustment")
		self.assertEqual(entry.litres_adjusted, 50)
		self.assertEqual(entry.previous_balance, 0)
		self.assertEqual(entry.current_balance, 50)

	def test_quantity_mode_is_signed(self):
		tanker = make_tanker("TEST-FT-ADJ-2").name
		supply(tanker, 100)
		doc = adjust(tanker, mode="Quantity", quantity=-10, reason="Spillage")
		doc.reload()

		self.assertEqual(doc.adjustment_litres, -10)
		self.assertEqual(balance(tanker), 90)
		self.assertEqual(entry_for(doc).litres_adjusted, -10)

	def test_stale_measured_draft_recomputed_at_submit(self):
		tanker = make_tanker("TEST-FT-ADJ-3").name
		supply(tanker, 100)
		stale = adjust(tanker, mode="Measured Balance", measured=90, submit=False)
		supply(tanker, 20)  # live balance moves to 120 while the draft waits
		stale.submit()
		stale.reload()

		self.assertEqual(stale.system_balance, 120)
		self.assertEqual(stale.adjustment_litres, -30)
		self.assertEqual(balance(tanker), 90)

	def test_zero_adjustment_blocked(self):
		tanker = make_tanker("TEST-FT-ADJ-4").name
		supply(tanker, 100)
		with self.assertRaises(frappe.ValidationError):
			adjust(tanker, mode="Measured Balance", measured=100)
		with self.assertRaises(frappe.ValidationError):
			adjust(tanker, mode="Quantity", quantity=0)
		# float noise rounds to zero at 3 decimals and must also be blocked
		with self.assertRaises(frappe.ValidationError):
			adjust(tanker, mode="Quantity", quantity=0.0004)

	def test_other_reason_requires_remarks(self):
		tanker = make_tanker("TEST-FT-ADJ-5").name
		with self.assertRaises(frappe.ValidationError):
			adjust(tanker, mode="Quantity", quantity=5, reason="Other")
		doc = adjust(tanker, mode="Quantity", quantity=5, reason="Other", remarks="found extra fuel")
		self.assertEqual(doc.docstatus, 1)

	def test_warnings_are_non_blocking(self):
		tanker = make_tanker("TEST-FT-ADJ-6", threshold=200, minimum_level=50).name
		supply(tanker, 100)

		frappe.clear_messages()
		doc = adjust(tanker, mode="Quantity", quantity=-120, reason="Theft")
		self.assertEqual(doc.docstatus, 1)
		msgs = messages_text()
		self.assertIn("(negative)", msgs)
		self.assertIn("minimum level", msgs)
		self.assertEqual(balance(tanker), -20)

		frappe.clear_messages()
		doc = adjust(tanker, mode="Quantity", quantity=500, reason="Data Entry Correction")
		self.assertEqual(doc.docstatus, 1)
		self.assertIn("maximum threshold", messages_text())
		self.assertEqual(balance(tanker), 480)

	def test_cancel_reverses_balance(self):
		tanker = make_tanker("TEST-FT-ADJ-7").name
		supply(tanker, 100)
		doc = adjust(tanker, mode="Quantity", quantity=40)
		self.assertEqual(balance(tanker), 140)

		entry_for(doc).cancel()

		self.assertEqual(balance(tanker), 100)
		self.assertEqual(frappe.db.get_value("Fuel Adjustment", doc.name, "docstatus"), 2)
