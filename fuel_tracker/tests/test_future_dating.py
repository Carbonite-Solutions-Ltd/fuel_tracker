# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""Fuel cannot be recorded for a date that has not happened yet.

Every movement in this system records something physical — fuel delivered,
issued, dipped or carted between sites — so a future date is always a keying
error. Left through it also splits the two figures users reconcile against
each other: an "as at today" balance report excludes a future-dated entry
while the `Fuel Balance` doctype, which is the tail of the whole ledger,
counts it. That is exactly how a 130 L discrepancy went unnoticed on the live
data.

Backdating stays fully open: today is the ceiling, not the floor.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.tests.utils import (
	adjust,
	balance,
	dispense,
	ensure_site,
	make_resource,
	make_tanker,
	request_supply,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


class TestFutureDating(FrappeTestCase):
	def test_future_dated_supply_is_blocked(self):
		tanker = make_tanker("TEST-FT-FD-1").name

		with self.assertRaises(frappe.ValidationError):
			supply(tanker, 500, date=day(1))

		self.assertEqual(balance(tanker), 0)

	def test_future_dated_dispense_is_blocked(self):
		tanker = make_tanker("TEST-FT-FD-2").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FD-TRK1", "Truck", reading=1000).name

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 50, odometer_km=1100, date=day(1))

		self.assertEqual(balance(tanker), 500)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1000)

	def test_future_dated_adjustment_and_transfer_are_blocked(self):
		site_a = ensure_site("TEST-FT-FD-SITE-A")
		site_b = ensure_site("TEST-FT-FD-SITE-B")
		source = make_tanker("TEST-FT-FD-3A", site=site_a).name
		dest = make_tanker("TEST-FT-FD-3B", site=site_b).name
		supply(source, 800)

		with self.assertRaises(frappe.ValidationError):
			adjust(source, mode="Quantity", quantity=-10, reason="Spillage", date=day(1))
		with self.assertRaises(frappe.ValidationError):
			transfer(source, dest, 100, date=day(1))

		self.assertEqual(balance(source), 800)
		self.assertEqual(balance(dest), 0)

	def test_a_future_dated_draft_cannot_even_be_saved(self):
		"""Caught at save, not left to fail later at submit."""
		tanker = make_tanker("TEST-FT-FD-4").name
		request = request_supply(tanker, 300)

		doc = frappe.get_doc({
			"doctype": "Fuel Supplied",
			"date": day(3),
			"fuel_tanker": tanker,
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
			"fuel_supplied": 300,
			"fuel_supply_request": request.name,
		})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_today_is_allowed(self):
		tanker = make_tanker("TEST-FT-FD-5").name
		truck = make_resource("TEST-FT-FD-TRK2", "Truck", reading=1000).name

		supply(tanker, 400, date=today())
		doc = dispense(tanker, truck, 60, odometer_km=1100, date=today())

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 340)

	def test_backdating_is_still_allowed(self):
		"""Today is the ceiling; the past stays open."""
		tanker = make_tanker("TEST-FT-FD-6").name
		truck = make_resource("TEST-FT-FD-TRK3", "Truck", reading=1000).name

		supply(tanker, 900, date=day(-30), posting_time="08:00:00")
		doc = dispense(tanker, truck, 100, odometer_km=1400, date=day(-20), posting_time="08:00:00")

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 800)

	def test_mobile_api_cannot_file_a_future_dated_report(self):
		"""The desk picker stops at today; the API has to be stopped too."""
		from fuel_tracker.api.fuel_used import fuel_used as api_fuel_used

		tanker = make_tanker("TEST-FT-FD-7").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FD-TRK4", "Truck", reading=1000).name

		payload = frappe._dict({
			"date": day(2),
			"fuel_tanker": tanker,
			"resource": truck,
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
			"fuel_used": 40,
			"odometer_km": 1100,
		})
		frappe.local.request = frappe._dict(
			get_data=lambda as_text=False: frappe.as_json(payload)
		)
		try:
			with self.assertRaises(frappe.ValidationError):
				api_fuel_used()
		finally:
			frappe.local.request = None

		self.assertFalse(
			frappe.db.exists("Fuel Used", {"resource": truck, "date": day(2)}),
			"no document may be left behind by the rejected call",
		)

	def test_the_report_and_the_doctype_now_agree_by_construction(self):
		"""Blocking future dates is what keeps these two figures in step."""
		from fuel_tracker.fuel_tracker.report.fuel_balance.fuel_balance import execute

		tanker = make_tanker("TEST-FT-FD-8").name
		truck = make_resource("TEST-FT-FD-TRK5", "Truck", reading=1000).name
		supply(tanker, 700, date=day(-10), posting_time="08:00:00")
		dispense(tanker, truck, 120, odometer_km=1300, date=day(-4), posting_time="08:00:00")

		_cols, rows = execute({"to_date": today(), "fuel_tanker": [tanker]})

		self.assertEqual(rows[0]["current_balance"], balance(tanker))
		self.assertEqual(rows[0]["current_balance"], 580)
