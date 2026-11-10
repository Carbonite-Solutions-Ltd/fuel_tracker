# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.tests.utils import (
	adjust,
	balance,
	before_openings_were_required,
	entry_for,
	issue_miscellaneous,
	make_tanker,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


def make_balance(tanker, opening=0, date=None):
	doc = frappe.get_doc({
		"doctype": "Fuel Balance",
		"fuel_tanker": tanker,
		"balance": opening,
		"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		"date": date or today(),
	})
	doc.insert()
	return doc


def opening_entries(tanker, docstatus=1):
	return frappe.get_all(
		"Fuel Entry",
		filters={"fuel_tanker": tanker, "utilization_type": "Opening Balance", "docstatus": docstatus},
		fields=["name", "current_balance", "posting_datetime"],
	)


class TestFuelBalance(FrappeTestCase):
	def test_submit_seeds_opening_entry(self):
		tanker = make_tanker("TEST-FT-FB-1", opened=False).name
		doc = make_balance(tanker, opening=250)
		doc.submit()

		seeded = opening_entries(tanker)
		self.assertEqual(len(seeded), 1)
		self.assertEqual(seeded[0].current_balance, 250)
		self.assertEqual(balance(tanker), 250)

	def test_reseed_after_opening_entry_cancelled(self):
		tanker = make_tanker("TEST-FT-FB-3", opened=False).name
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
		tanker = make_tanker("TEST-FT-FB-4", opened=False).name
		doc = make_balance(tanker, opening=100)
		doc.submit()  # seeds an opening entry -> ledger is active

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Fuel Balance", tanker).cancel()

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Fuel Balance", tanker)


class TestOpeningComesFirst(FrappeTestCase):
	"""No fuel moves on a tanker until its opening balance is submitted."""

	def test_every_movement_waits_for_the_opening(self):
		tanker = make_tanker("TEST-FT-FB-6", opened=False).name
		opened = make_tanker("TEST-FT-FB-6B").name
		supply(opened, 500)

		with self.assertRaisesRegex(frappe.ValidationError, "has no opening balance yet"):
			supply(tanker, 100)
		with self.assertRaisesRegex(frappe.ValidationError, "has no opening balance yet"):
			issue_miscellaneous(tanker, 10)
		with self.assertRaisesRegex(frappe.ValidationError, "has no opening balance yet"):
			adjust(tanker, mode="Measured Balance", measured=300)
		with self.assertRaisesRegex(frappe.ValidationError, "has no opening balance yet"):
			transfer(opened, tanker, 50)

		# the first movement no longer creates a blank draft balance behind the scenes
		self.assertFalse(frappe.db.exists("Fuel Balance", {"fuel_tanker": tanker}))
		self.assertEqual(balance(opened), 500)

	def test_a_draft_can_be_saved_before_the_opening(self):
		"""Incoming mobile reports are fuel already handed out: keep them."""
		tanker = make_tanker("TEST-FT-FB-7", opened=False).name
		draft = issue_miscellaneous(tanker, 10, submit=False)
		self.assertEqual(draft.docstatus, 0)

		with self.assertRaisesRegex(frappe.ValidationError, "has no opening balance yet"):
			draft.submit()

		make_balance(tanker, opening=400, date=day(-1)).submit()
		frappe.get_doc("Fuel Used", draft.name).submit()
		self.assertEqual(balance(tanker), 390)

	def test_a_draft_opening_does_not_count(self):
		tanker = make_tanker("TEST-FT-FB-8", opened=False).name
		make_balance(tanker, opening=900)  # saved, never submitted

		with self.assertRaisesRegex(frappe.ValidationError, "has no opening balance yet"):
			supply(tanker, 100)


class TestOpeningATankerThatAlreadyHasMovements(FrappeTestCase):
	"""Live sites hold tankers that took movements before openings were required."""

	def legacy_tanker(self, name):
		tanker = make_tanker(name, opened=False).name
		with before_openings_were_required():
			draft = make_balance(tanker, opening=0, date=day(-6))  # what the first movement used to create
			supply(tanker, 1000, date=day(-5), posting_time="08:00:00")
			issue_miscellaneous(tanker, 200, date=day(-3), posting_time="08:00:00")
		return tanker, draft

	def test_opening_dated_before_the_first_movement_is_seeded_and_reprices(self):
		tanker, draft = self.legacy_tanker("TEST-FT-FB-9")
		later = frappe.get_all("Fuel Entry", {"fuel_tanker": tanker, "docstatus": 1}, pluck="name")

		draft.reload()
		draft.update({"date": day(-5), "balance": 3000}).submit()

		seeded = opening_entries(tanker)
		self.assertEqual(len(seeded), 1)
		self.assertEqual(str(seeded[0].posting_datetime), f"{day(-5)} 00:00:00")
		# everything already recorded continues from the opening
		self.assertEqual(balance(tanker), 3000 + 1000 - 200)
		closings = sorted(frappe.db.get_value("Fuel Entry", name, "current_balance") for name in later)
		self.assertEqual(closings, [3800, 4000])

	def test_opening_dated_after_a_movement_is_refused_with_the_latest_date_allowed(self):
		tanker, draft = self.legacy_tanker("TEST-FT-FB-10")

		draft.reload()
		draft.update({"date": day(-4), "balance": 3000})
		latest = frappe.format(day(-5), {"fieldtype": "Date"})
		with self.assertRaisesRegex(frappe.ValidationError, f"Set the Date to .*{latest}"):
			draft.save()
		with self.assertRaisesRegex(frappe.ValidationError, "must be dated before them"):
			frappe.get_doc("Fuel Balance", tanker).update({"date": day(-4), "balance": 3000}).submit()
		self.assertEqual(len(opening_entries(tanker)), 0)

	def test_a_movement_at_midnight_needs_the_day_before(self):
		tanker = make_tanker("TEST-FT-FB-11", opened=False).name
		with before_openings_were_required():
			supply(tanker, 500, date=day(-5), posting_time="00:00:00")

		doc = frappe.get_doc({
			"doctype": "Fuel Balance", "fuel_tanker": tanker, "balance": 100, "date": day(-5),
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		})
		with self.assertRaisesRegex(frappe.ValidationError, frappe.format(day(-6), {"fieldtype": "Date"})):
			doc.insert()

		doc.date = day(-6)
		doc.insert()
		doc.submit()
		self.assertEqual(balance(tanker), 600)

	def test_an_untouched_legacy_draft_can_still_be_saved(self):
		tanker, draft = self.legacy_tanker("TEST-FT-FB-12")
		# the old code kept the draft pointed at the ledger tail and last date
		draft.db_set({"date": day(-3), "balance": 800})

		draft.reload()
		draft.save()  # nothing entered: nothing to check

		draft.balance = 2000
		with self.assertRaisesRegex(frappe.ValidationError, "must be dated before them"):
			draft.save()

	def test_the_ledger_does_not_overwrite_an_opening_being_typed(self):
		tanker, draft = self.legacy_tanker("TEST-FT-FB-13")
		draft.reload()
		draft.update({"date": day(-6), "balance": 2500}).save()

		with before_openings_were_required():
			issue_miscellaneous(tanker, 50, date=day(-2), posting_time="08:00:00")

		self.assertEqual(frappe.db.get_value("Fuel Balance", tanker, "balance"), 2500)
		frappe.get_doc("Fuel Balance", tanker).submit()
		self.assertEqual(balance(tanker), 2500 + 1000 - 200 - 50)
