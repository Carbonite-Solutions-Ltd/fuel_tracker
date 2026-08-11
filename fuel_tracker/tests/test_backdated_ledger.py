# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""The date-aware ledger: backdating, reposting and balance-as-of."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.fuel_tracker.fuel_ledger import get_ledger_entries
from fuel_tracker.tests.utils import (
	adjust,
	balance,
	balance_on,
	dispense,
	entry_for,
	make_resource,
	make_tanker,
	messages_text,
	supply,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


class TestBackdatedLedger(FrappeTestCase):
	def test_backdated_dispense_is_allowed_when_fuel_existed_that_day(self):
		"""The regression this whole feature exists for.

		Fuel arrives on day -10 and is all drawn down by day -1. A dispense is
		then keyed in late for day -8, when the tanker was full. The old ledger
		priced it against today's (empty) balance and complained there was no
		fuel; it must now be priced against day -8.
		"""
		tanker = make_tanker("TEST-FT-BD-1").name
		truck = make_resource("TEST-FT-BD-TRK1", "Truck", reading=1000).name

		supply(tanker, 1000, date=day(-10), posting_time="08:00:00")
		dispense(tanker, truck, 1000, odometer_km=1500, date=day(-1), posting_time="08:00:00")
		self.assertEqual(balance(tanker), 0)

		frappe.clear_messages()
		# the odometer that applied on day -8, which sits behind the day -1 reading
		late = dispense(tanker, truck, 200, odometer_km=1200, date=day(-8), posting_time="08:00:00")

		self.assertEqual(late.docstatus, 1)
		# priced against the 1,000 L the tanker actually held on day -8
		self.assertEqual(entry_for(late).previous_balance, 1000)
		self.assertEqual(entry_for(late).current_balance, 800)
		self.assertNotIn("exceeds the balance", messages_text())

	def test_backdated_entry_reposts_later_entries(self):
		tanker = make_tanker("TEST-FT-BD-2").name
		truck = make_resource("TEST-FT-BD-TRK2", "Truck", reading=1000).name

		supply(tanker, 500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 100, odometer_km=1100, date=day(-2), posting_time="08:00:00")
		self.assertEqual(entry_for(later).current_balance, 400)

		# a supply keyed in late, dated between the two
		supply(tanker, 300, date=day(-5), posting_time="08:00:00")

		# the day -2 dispense is re-priced on top of the inserted supply
		repriced = entry_for(later)
		self.assertEqual(repriced.previous_balance, 800)
		self.assertEqual(repriced.current_balance, 700)
		self.assertEqual(balance(tanker), 700)

	def test_balance_as_of_reads_history_not_current_state(self):
		tanker = make_tanker("TEST-FT-BD-3").name
		truck = make_resource("TEST-FT-BD-TRK3", "Truck", reading=1000).name

		supply(tanker, 600, date=day(-6), posting_time="08:00:00")
		dispense(tanker, truck, 150, odometer_km=1200, date=day(-3), posting_time="08:00:00")

		self.assertEqual(balance_on(tanker, day(-7)), 0)
		self.assertEqual(balance_on(tanker, day(-6)), 600)
		self.assertEqual(balance_on(tanker, day(-4)), 600)
		self.assertEqual(balance_on(tanker, day(-3)), 450)
		self.assertEqual(balance(tanker), 450)

	def test_ledger_stays_continuous_after_backdating(self):
		"""Every entry's previous_balance must equal the one before it."""
		tanker = make_tanker("TEST-FT-BD-4").name
		truck = make_resource("TEST-FT-BD-TRK4", "Truck", reading=1000).name

		supply(tanker, 400, date=day(-9), posting_time="08:00:00")
		dispense(tanker, truck, 50, odometer_km=1100, date=day(-7), posting_time="08:00:00")
		supply(tanker, 200, date=day(-3), posting_time="08:00:00")
		# inserted out of order, between existing entries
		adjust(tanker, mode="Quantity", quantity=-25, reason="Spillage",
			date=day(-5), posting_time="08:00:00")
		dispense(tanker, truck, 75, odometer_km=1200, date=day(-1), posting_time="08:00:00")

		entries = get_ledger_entries(tanker)
		running = 0
		for entry in entries:
			self.assertEqual(entry.previous_balance, running, "break at {0}".format(entry.name))
			running = entry.current_balance

		self.assertEqual(balance(tanker), running)
		self.assertEqual(balance(tanker), 400 - 50 - 25 + 200 - 75)

	def test_posting_time_orders_entries_within_a_day(self):
		tanker = make_tanker("TEST-FT-BD-5").name
		truck = make_resource("TEST-FT-BD-TRK5", "Truck", reading=1000).name

		# keyed in reverse order, but the morning supply must come first
		dispense_doc = dispense(tanker, truck, 80, odometer_km=1100, date=day(-2), posting_time="16:00:00")
		supply(tanker, 500, date=day(-2), posting_time="09:00:00")

		entry = entry_for(dispense_doc)
		self.assertEqual(entry.previous_balance, 500)
		self.assertEqual(entry.current_balance, 420)

	def test_entry_before_opening_balance_is_blocked(self):
		tanker = make_tanker("TEST-FT-BD-6").name

		opening = frappe.get_doc({
			"doctype": "Fuel Balance",
			"fuel_tanker": tanker,
			"balance": 300,
			"date": day(-5),
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		})
		opening.insert()
		opening.submit()

		# the opening figure already accounts for everything before it
		with self.assertRaises(frappe.ValidationError):
			supply(tanker, 100, date=day(-8), posting_time="08:00:00")

		self.assertEqual(balance(tanker), 300)

	def test_backdated_adjustment_measures_against_that_days_stock(self):
		tanker = make_tanker("TEST-FT-BD-7").name

		supply(tanker, 500, date=day(-6), posting_time="08:00:00")
		supply(tanker, 300, date=day(-2), posting_time="08:00:00")

		# a dip count taken on day -4, when the tanker held 500
		doc = adjust(tanker, mode="Measured Balance", measured=460,
			date=day(-4), posting_time="08:00:00")
		doc.reload()

		self.assertEqual(doc.system_balance, 500)
		self.assertEqual(doc.adjustment_litres, -40)
		# the later supply is reposted on top of the correction
		self.assertEqual(balance(tanker), 760)

	def test_stale_draft_posts_at_submission_not_at_drafting(self):
		"""Without Set Posting Time, a draft posts when it is submitted."""
		tanker = make_tanker("TEST-FT-BD-8").name

		supply(tanker, 100)
		stale = adjust(tanker, mode="Measured Balance", measured=90, submit=False)
		supply(tanker, 20)  # balance moves to 120 while the draft waits
		stale.submit()
		stale.reload()

		self.assertEqual(stale.system_balance, 120)
		self.assertEqual(stale.adjustment_litres, -30)
		self.assertEqual(balance(tanker), 90)

	def test_cancelling_a_mid_history_entry_reposts_the_tail(self):
		tanker = make_tanker("TEST-FT-BD-9").name
		truck = make_resource("TEST-FT-BD-TRK9", "Truck", reading=1000).name

		supply(tanker, 500, date=day(-8), posting_time="08:00:00")
		middle = supply(tanker, 250, date=day(-5), posting_time="08:00:00")
		last = dispense(tanker, truck, 100, odometer_km=1100, date=day(-2), posting_time="08:00:00")
		self.assertEqual(balance(tanker), 650)

		entry_for(middle).cancel()

		self.assertEqual(entry_for(last).previous_balance, 500)
		self.assertEqual(entry_for(last).current_balance, 400)
		self.assertEqual(balance(tanker), 400)

	def test_backdated_withdrawal_warns_when_it_overdraws_later(self):
		"""Affordable on its own date, but it sinks the ledger further on."""
		tanker = make_tanker("TEST-FT-BD-10").name
		truck = make_resource("TEST-FT-BD-TRK10", "Truck", reading=1000).name

		supply(tanker, 500, date=day(-9), posting_time="08:00:00")
		dispense(tanker, truck, 450, odometer_km=1100, date=day(-4), posting_time="08:00:00")

		frappe.clear_messages()
		# 300 L is affordable on day -6 (500 L on hand) but leaves -250 after day -4
		doc = dispense(tanker, truck, 300, odometer_km=1050, date=day(-6), posting_time="08:00:00")

		self.assertEqual(doc.docstatus, 1)
		self.assertIn("drives its balance negative later", messages_text())
		self.assertEqual(balance(tanker), -250)
