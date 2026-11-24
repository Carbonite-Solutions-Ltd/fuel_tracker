# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""Cancelling source documents directly, singly and in bulk from the list.

A source document (Fuel Used, Fuel Supplied, Fuel Adjustment) used to be
refused when cancelled directly: its `Fuel Entry` was still submitted and
linked to it. The desk form got round that with "Cancel All", but a bulk
cancel from the list has no such step, so every document failed — and from
20 documents up, where Frappe runs the job in the background, it failed
silently.
"""

from unittest.mock import patch

import frappe
from frappe.desk.doctype.bulk_update.bulk_update import _bulk_action
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.tests.utils import (
	adjust,
	balance,
	dispense,
	entry_for,
	issue_miscellaneous,
	make_resource,
	make_tanker,
	request_supply,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]

#: More than Frappe's 20-document cut-off for running a bulk action inline.
BULK = 25


def day(offset):
	return add_days(today(), offset)


def bulk_cancel(doctype, names):
	"""Run Frappe's own bulk action — what the list view's Cancel runs.

	It commits after every document and rolls back on failure; both are
	stubbed so the test's data stays inside the test transaction.
	"""
	with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback"):
		return _bulk_action(doctype, names, "cancel", None)


def docstatuses(doctype, names):
	return set(frappe.get_all(doctype, filters={"name": ["in", names]}, pluck="docstatus"))


class TestBulkCancel(FrappeTestCase):
	def test_bulk_cancel_fuel_used_unwinds_fuel_and_readings(self):
		tanker = make_tanker("TEST-FT-BC-1").name
		truck = make_resource("TEST-FT-BC-TRK1", "Truck", reading=1000).name
		supply(tanker, 10000, date=day(-60), posting_time="08:00:00")
		fills = [
			dispense(tanker, truck, 10, odometer_km=1100 + i * 100, date=day(-50 + i), posting_time="08:00:00")
			for i in range(BULK)
		]
		self.assertEqual(balance(tanker), 10000 - 10 * BULK)

		failed = bulk_cancel("Fuel Used", [d.name for d in fills])

		self.assertEqual(failed, [])
		self.assertEqual(docstatuses("Fuel Used", [d.name for d in fills]), {2})
		self.assertTrue(all(entry_for(d) is None for d in fills), "every ledger line cancelled")
		self.assertEqual(balance(tanker), 10000)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1000)

	def test_bulk_cancel_part_of_a_history_reposts_what_is_left(self):
		tanker = make_tanker("TEST-FT-BC-2").name
		truck = make_resource("TEST-FT-BC-TRK2", "Truck", reading=1000).name
		supply(tanker, 10000, date=day(-60), posting_time="08:00:00")
		fills = [
			dispense(tanker, truck, 10, odometer_km=1100 + i * 100, date=day(-50 + i), posting_time="08:00:00")
			for i in range(BULK + 5)
		]
		# cancel the middle 25, keeping the first and the last few
		middle = fills[2:2 + BULK]

		self.assertEqual(bulk_cancel("Fuel Used", [d.name for d in middle]), [])

		survivor = fills[2 + BULK]
		self.assertEqual(entry_for(survivor).diff_odometer, survivor.odometer_km - fills[1].odometer_km)
		self.assertEqual(balance(tanker), 10000 - 10 * 5)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), fills[-1].odometer_km)

	def test_bulk_cancel_miscellaneous_issues(self):
		tanker = make_tanker("TEST-FT-BC-3").name
		supply(tanker, 1000, date=day(-60), posting_time="08:00:00")
		issues = [issue_miscellaneous(tanker, 5, date=day(-50 + i), posting_time="08:00:00") for i in range(BULK)]

		self.assertEqual(bulk_cancel("Fuel Used", [d.name for d in issues]), [])
		self.assertEqual(balance(tanker), 1000)

	def test_bulk_cancel_fuel_supplied_updates_the_request(self):
		tanker = make_tanker("TEST-FT-BC-4").name
		request = request_supply(tanker, 100 * BULK, date=day(-60))
		supplies = [
			supply(tanker, 100, date=day(-50 + i), posting_time="08:00:00", request=request.name)
			for i in range(BULK)
		]
		self.assertEqual(frappe.db.get_value("Fuel Supply Request", request.name, "status"), "Fully Supplied")

		self.assertEqual(bulk_cancel("Fuel Supplied", [d.name for d in supplies]), [])

		self.assertEqual(docstatuses("Fuel Supplied", [d.name for d in supplies]), {2})
		self.assertEqual(balance(tanker), 0)
		self.assertEqual(frappe.db.get_value("Fuel Supply Request", request.name, "status"), "Pending")

	def test_bulk_cancel_fuel_adjustment(self):
		tanker = make_tanker("TEST-FT-BC-5").name
		supply(tanker, 1000, date=day(-60), posting_time="08:00:00")
		adjustments = [
			adjust(tanker, quantity=-2, date=day(-50 + i), posting_time="08:00:00") for i in range(BULK)
		]
		self.assertEqual(balance(tanker), 1000 - 2 * BULK)

		self.assertEqual(bulk_cancel("Fuel Adjustment", [d.name for d in adjustments]), [])
		self.assertEqual(balance(tanker), 1000)

	def test_bulk_cancel_fuel_transfer(self):
		source = make_tanker("TEST-FT-BC-6A").name
		destination = make_tanker("TEST-FT-BC-6B").name
		supply(source, 1000, date=day(-60), posting_time="08:00:00")
		transfers = [
			transfer(source, destination, 10, date=day(-50 + i), posting_time="08:00:00") for i in range(BULK)
		]

		self.assertEqual(bulk_cancel("Fuel Transfer", [d.name for d in transfers]), [])
		self.assertEqual((balance(source), balance(destination)), (1000, 0))

	def test_bulk_cancel_from_the_fuel_entry_side_still_works(self):
		tanker = make_tanker("TEST-FT-BC-7").name
		truck = make_resource("TEST-FT-BC-TRK7", "Truck", reading=1000).name
		supply(tanker, 10000, date=day(-60), posting_time="08:00:00")
		fills = [
			dispense(tanker, truck, 10, odometer_km=1100 + i * 100, date=day(-50 + i), posting_time="08:00:00")
			for i in range(BULK)
		]

		self.assertEqual(bulk_cancel("Fuel Entry", [entry_for(d).name for d in fills]), [])
		self.assertEqual(docstatuses("Fuel Used", [d.name for d in fills]), {2})
		self.assertEqual(balance(tanker), 10000)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1000)

	def test_cancelling_a_source_directly_cancels_its_entry(self):
		tanker = make_tanker("TEST-FT-BC-8").name
		truck = make_resource("TEST-FT-BC-TRK8", "Truck", reading=1000).name
		supply(tanker, 500, date=day(-60), posting_time="08:00:00")
		fill = dispense(tanker, truck, 50, odometer_km=1200, date=day(-5), posting_time="08:00:00")
		entry = entry_for(fill).name

		fill.cancel()

		self.assertEqual(frappe.db.get_value("Fuel Entry", entry, "docstatus"), 2)
		self.assertEqual(balance(tanker), 500)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1000)

	def test_manager_without_fuel_entry_rights_can_still_cancel_a_fill(self):
		"""Being allowed to cancel the source is what authorises its entry."""
		tanker = make_tanker("TEST-FT-BC-9").name
		truck = make_resource("TEST-FT-BC-TRK9", "Truck", reading=1000).name
		supply(tanker, 500, date=day(-60), posting_time="08:00:00")
		fill = dispense(tanker, truck, 50, odometer_km=1200, date=day(-5), posting_time="08:00:00")

		role = "Test FT Fill Canceller"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
		from frappe.permissions import add_permission, update_permission_property

		add_permission("Fuel Used", role, 0)
		for right in ("cancel", "submit", "write"):
			update_permission_property("Fuel Used", role, 0, right, 1)
		email = "test-ft-bc-canceller@example.com"
		if not frappe.db.exists("User", email):
			user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Canceller", "send_welcome_email": 0}).insert()
			user.add_roles(role)
		self.assertFalse(frappe.has_permission("Fuel Entry", "cancel", user=email))

		frappe.set_user(email)
		try:
			frappe.get_doc("Fuel Used", fill.name).cancel()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Fuel Used", fill.name, "docstatus"), 2)
		self.assertEqual(balance(tanker), 500)
