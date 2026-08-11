# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.tests.utils import (
	balance,
	balance_on,
	ensure_site,
	entries_for,
	make_tanker,
	messages_text,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]


class TestFuelTransfer(FrappeTestCase):
	def make_pair(self, suffix):
		"""Two tankers on two different sites."""
		site_a = ensure_site("TEST-FT-SITE-A")
		site_b = ensure_site("TEST-FT-SITE-B")
		source = make_tanker("TEST-FT-TRF-{0}-A".format(suffix), site=site_a).name
		dest = make_tanker("TEST-FT-TRF-{0}-B".format(suffix), site=site_b).name
		return source, dest

	def test_transfer_moves_fuel_between_sites(self):
		source, dest = self.make_pair(1)
		supply(source, 1000)
		supply(dest, 200)

		doc = transfer(source, dest, 400)

		self.assertEqual(balance(source), 600)
		self.assertEqual(balance(dest), 600)

		in_entry, out_entry = sorted(entries_for(doc), key=lambda e: e.utilization_type)
		self.assertEqual(in_entry.utilization_type, "Transfer In")
		self.assertEqual(in_entry.fuel_tanker, dest)
		self.assertEqual(in_entry.litres_supplied, 400)
		self.assertEqual(out_entry.utilization_type, "Transfer Out")
		self.assertEqual(out_entry.fuel_tanker, source)
		self.assertEqual(out_entry.litres_dispensed, 400)

	def test_sites_are_fetched_from_the_tankers(self):
		source, dest = self.make_pair(2)
		supply(source, 500)

		doc = transfer(source, dest, 100)
		doc.reload()

		self.assertEqual(doc.from_site, "TEST-FT-SITE-A")
		self.assertEqual(doc.to_site, "TEST-FT-SITE-B")
		self.assertNotEqual(doc.from_site, doc.to_site)

	def test_transfer_to_same_tanker_blocked(self):
		source, _dest = self.make_pair(3)
		supply(source, 500)

		with self.assertRaises(frappe.ValidationError):
			transfer(source, source, 100)

	def test_zero_and_negative_litres_blocked(self):
		source, dest = self.make_pair(4)
		supply(source, 500)

		with self.assertRaises(frappe.ValidationError):
			transfer(source, dest, 0)
		with self.assertRaises(frappe.ValidationError):
			transfer(source, dest, -50)

	def test_cancelling_either_leg_unwinds_both_sides(self):
		source, dest = self.make_pair(5)
		supply(source, 800)
		doc = transfer(source, dest, 300)
		self.assertEqual(balance(source), 500)
		self.assertEqual(balance(dest), 300)

		# cancelling one leg must cascade through the transfer to the other
		entries_for(doc)[0].cancel()

		doc.reload()
		self.assertEqual(doc.docstatus, 2)
		self.assertEqual(len(entries_for(doc, docstatus=1)), 0)
		self.assertEqual(len(entries_for(doc, docstatus=2)), 2)
		self.assertEqual(balance(source), 800)
		self.assertEqual(balance(dest), 0)

	def test_cancelling_the_transfer_cancels_both_legs(self):
		source, dest = self.make_pair(6)
		supply(source, 800)
		doc = transfer(source, dest, 300)

		doc.cancel()

		self.assertEqual(len(entries_for(doc, docstatus=1)), 0)
		self.assertEqual(balance(source), 800)
		self.assertEqual(balance(dest), 0)

	def test_overdrawing_the_source_warns_without_blocking(self):
		source, dest = self.make_pair(7)
		supply(source, 100)

		frappe.clear_messages()
		doc = transfer(source, dest, 250)

		self.assertEqual(doc.docstatus, 1)
		self.assertIn("exceeds the balance of tanker", messages_text())
		self.assertEqual(balance(source), -150)
		self.assertEqual(balance(dest), 250)

	def test_backdated_transfer_reposts_both_ledgers(self):
		source, dest = self.make_pair(8)
		day = lambda o: add_days(today(), o)

		supply(source, 1000, date=day(-10), posting_time="08:00:00")
		supply(dest, 100, date=day(-10), posting_time="08:00:00")
		# an entry on each side that the backdated transfer must be inserted before
		supply(source, 50, date=day(-1), posting_time="08:00:00")
		supply(dest, 20, date=day(-1), posting_time="08:00:00")

		transfer(source, dest, 400, date=day(-5), posting_time="08:00:00")

		self.assertEqual(balance_on(source, day(-6)), 1000)
		self.assertEqual(balance_on(source, day(-5)), 600)
		self.assertEqual(balance_on(dest, day(-5)), 500)
		self.assertEqual(balance(source), 650)
		self.assertEqual(balance(dest), 520)

	def test_transfer_litres_appear_in_the_fuel_ledger_report(self):
		from fuel_tracker.fuel_tracker.report.fuel_ledger.fuel_ledger import execute

		source, dest = self.make_pair(9)
		supply(source, 900)
		transfer(source, dest, 350)

		_columns, data = execute({"fuel_tanker": [source, dest]})
		by_type = {row["utilization_type"]: row for row in data if row.get("utilization_type")}

		self.assertEqual(by_type["Transfer Out"]["litres_dispensed"], 350)
		self.assertEqual(by_type["Transfer In"]["litres_supplied"], 350)

	def test_cancelling_a_backdated_transfer_reposts_both_ledgers(self):
		"""Reversing a transfer that sits mid-history on both sides."""
		source, dest = self.make_pair(10)
		day = lambda o: add_days(today(), o)

		supply(source, 1000, date=day(-10), posting_time="08:00:00")
		supply(dest, 100, date=day(-10), posting_time="08:00:00")
		doc = transfer(source, dest, 400, date=day(-5), posting_time="08:00:00")
		# activity on both sides *after* the transfer, which must be re-priced
		supply(source, 50, date=day(-2), posting_time="08:00:00")
		supply(dest, 20, date=day(-2), posting_time="08:00:00")
		self.assertEqual(balance(source), 650)
		self.assertEqual(balance(dest), 520)

		doc.cancel()

		# both sides unwind, and the later entries re-price on top
		self.assertEqual(len(entries_for(doc, docstatus=1)), 0)
		self.assertEqual(balance_on(source, day(-5)), 1000)
		self.assertEqual(balance_on(dest, day(-5)), 100)
		self.assertEqual(balance(source), 1050)
		self.assertEqual(balance(dest), 120)
