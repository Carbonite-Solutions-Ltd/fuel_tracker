# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from fuel_tracker.tests.utils import balance, entry_for, make_tanker, supply

test_ignore = ["Item", "Company"]


def make_balance(tanker, opening=0):
	doc = frappe.get_doc({
		"doctype": "Fuel Balance",
		"fuel_tanker": tanker,
		"balance": opening,
		"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		"date": today(),
	})
	doc.insert()
	return doc


def opening_entries(tanker, docstatus=1):
	return frappe.get_all(
		"Fuel Entry",
		filters={"fuel_tanker": tanker, "utilization_type": "Opening Balance", "docstatus": docstatus},
		fields=["name", "current_balance"],
	)


class TestFuelBalance(FrappeTestCase):
	def test_submit_seeds_opening_entry(self):
		tanker = make_tanker("TEST-FT-FB-1").name
		doc = make_balance(tanker, opening=250)
		doc.submit()

		seeded = opening_entries(tanker)
		self.assertEqual(len(seeded), 1)
		self.assertEqual(seeded[0].current_balance, 250)
		self.assertEqual(balance(tanker), 250)

	def test_no_seed_when_ledger_already_active(self):
		tanker = make_tanker("TEST-FT-FB-2").name
		supply(tanker, 100)  # lazily creates the draft balance and a Supplied entry

		doc = frappe.get_doc("Fuel Balance", tanker)
		doc.submit()

		self.assertEqual(len(opening_entries(tanker)), 0)
		self.assertEqual(balance(tanker), 100)

	def test_reseed_after_opening_entry_cancelled(self):
		tanker = make_tanker("TEST-FT-FB-3").name
		doc = make_balance(tanker, opening=250)
		doc.submit()

		frappe.get_doc("Fuel Entry", opening_entries(tanker)[0].name).cancel()
		doc.reload()
		doc.cancel()
		doc.delete()

		fresh = make_balance(tanker, opening=300)
		fresh.submit()
		seeded = opening_entries(tanker)
		self.assertEqual(len(seeded), 1)
		self.assertEqual(seeded[0].current_balance, 300)

	def test_cancel_and_trash_blocked_while_ledger_active(self):
		tanker = make_tanker("TEST-FT-FB-4").name
		doc = make_balance(tanker, opening=100)
		doc.submit()  # seeds an opening entry -> ledger is active

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Fuel Balance", tanker).cancel()

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Fuel Balance", tanker)
