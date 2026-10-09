# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from fuel_tracker.tests.utils import adjust, balance, dispense, entry_for, make_resource, make_tanker, supply

test_ignore = ["Item", "Company"]


class TestFuelEntry(FrappeTestCase):
	def test_cancel_cascades_and_reverses_for_each_source(self):
		tanker = make_tanker("TEST-FT-FE-1").name
		truck = make_resource("TEST-FT-FE-TRK1", "Truck", reading=100).name

		sup = supply(tanker, 100)
		dis = dispense(tanker, truck, 30, odometer_km=200)
		adj = adjust(tanker, mode="Quantity", quantity=-20)
		self.assertEqual(balance(tanker), 50)

		entry_for(adj).cancel()
		self.assertEqual(balance(tanker), 70)
		self.assertEqual(frappe.db.get_value("Fuel Adjustment", adj.name, "docstatus"), 2)

		entry_for(dis).cancel()
		self.assertEqual(balance(tanker), 100)
		self.assertEqual(frappe.db.get_value("Fuel Used", dis.name, "docstatus"), 2)

		entry_for(sup).cancel()
		self.assertEqual(balance(tanker), 0)
		self.assertEqual(frappe.db.get_value("Fuel Supplied", sup.name, "docstatus"), 2)

	def test_cancel_restores_equipment_hours(self):
		# regression: the restore used to write a non-existent field
		# (current_hours_copy) and silently leave the hours stale
		tanker = make_tanker("TEST-FT-FE-2").name
		supply(tanker, 500)
		eq = make_resource("TEST-FT-FE-EQ1", "Equipment", reading=100).name

		doc = dispense(tanker, eq, 30, hours_copy=110)
		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 110)

		entry_for(doc).cancel()
		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 100)

	def test_mid_history_cancel_keeps_later_reading(self):
		tanker = make_tanker("TEST-FT-FE-3").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FE-TRK2", "Truck", reading=1000).name

		first = dispense(tanker, truck, 40, odometer_km=1100)
		second = dispense(tanker, truck, 25, odometer_km=1200)

		# cancelling the earlier entry must not rewind past the later one
		entry_for(first).cancel()
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1200)

		# with every fill cancelled the truck is back to its opening reading
		entry_for(second).cancel()
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1000)

	def test_direct_cancel_of_sources_blocked(self):
		tanker = make_tanker("TEST-FT-FE-4").name
		truck = make_resource("TEST-FT-FE-TRK3", "Truck", reading=100).name

		sup = supply(tanker, 100)
		dis = dispense(tanker, truck, 10, odometer_km=150)
		adj = adjust(tanker, mode="Quantity", quantity=-5)

		for doc in (sup, dis, adj):
			with self.assertRaises(frappe.LinkExistsError):
				frappe.get_doc(doc.doctype, doc.name).cancel()

	def test_direct_cancel_of_miscellaneous_issue_blocked(self):
		from fuel_tracker.tests.utils import issue_miscellaneous

		tanker = make_tanker("TEST-FT-FE-5").name
		supply(tanker, 100)
		misc = issue_miscellaneous(tanker, 10)

		# like every other source, it is unwound from its ledger entry
		with self.assertRaises(frappe.LinkExistsError):
			frappe.get_doc("Fuel Used", misc.name).cancel()

	def test_hand_made_ledger_lines_are_refused(self):
		"""Only source documents write to the ledger."""
		tanker = make_tanker("TEST-FT-FE-6").name
		supply(tanker, 100)
		site = frappe.db.get_value("Fuel Tanker", tanker, "site")

		def hand_made(**fields):
			return frappe.get_doc({
				"doctype": "Fuel Entry", "date": frappe.utils.today(), "fuel_tanker": tanker, "site": site,
				**fields,
			})

		for fields in (
			{"utilization_type": "Supplied", "litres_supplied": 500},  # no Fuel Supplied behind it
			{"utilization_type": "Suplied", "litres_supplied": 500},   # typo moved nothing
			{"utilization_type": None},
			{"utilization_type": "Opening Balance", "current_balance": 900},  # not from a Fuel Balance
		):
			with self.assertRaises(frappe.ValidationError, msg=str(fields)):
				hand_made(**fields).insert()

		self.assertEqual(balance(tanker), 100)
