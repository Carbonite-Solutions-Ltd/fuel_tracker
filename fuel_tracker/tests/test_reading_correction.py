# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""Correcting a mistyped reading on a submitted `Fuel Used`.

Before this, the only fix was cancelling the fill's `Fuel Entry` — which also
unwinds the tanker's fuel — and a reading typed too high blocked every
correct fill after it as "going backwards".
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.fuel_tracker.resource_ledger import get_anchor_reading
from fuel_tracker.tests.utils import (
	balance,
	dispense,
	entry_for,
	issue_miscellaneous,
	make_resource,
	make_tanker,
	supply,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


def reading(resource, field="current_odometer"):
	return frappe.db.get_value("Resource", resource, field)


def make_user(email, role):
	"""A desk user holding a single Fuel Tracker role.

	The roles are created on each site rather than shipped by the app, so the
	test creates the role when the site lacks it, and gives it read on Fuel
	Used — what a form-called method needs — as live sites already have.
	"""
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
	if not frappe.db.exists("Custom DocPerm", {"parent": "Fuel Used", "role": role}):
		from frappe.permissions import add_permission

		add_permission("Fuel Used", role, 0)

	if not frappe.db.exists("User", email):
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": role,
			"send_welcome_email": 0,
		}).insert()
		user.add_roles(role)
	return email


class TestReadingCorrection(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def setup_truck(self, suffix, opening=1000):
		tanker = make_tanker("TEST-FT-RC-{0}".format(suffix)).name
		truck = make_resource("TEST-FT-RC-TRK{0}".format(suffix), "Truck", reading=opening).name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")
		return tanker, truck

	def test_a_reading_typed_too_high_is_corrected_and_unblocks_later_fills(self):
		tanker, truck = self.setup_truck(1)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		# 1750 keyed as 17500
		typo = dispense(tanker, truck, 90, odometer_km=17500, date=day(-6), posting_time="08:00:00")

		# the genuine next reading is refused because of the typo
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		litres_before = balance(tanker)
		typo.correct_reading(1750, "extra zero keyed")

		typo.reload()
		self.assertEqual(typo.docstatus, 1, "corrected in place, not cancelled")
		self.assertEqual(typo.odometer_km, 1750)
		self.assertEqual(entry_for(typo).diff_odometer, 250)
		self.assertEqual(reading(truck), 1750)
		self.assertEqual(balance(tanker), litres_before, "no fuel moves")

		later = dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")
		self.assertEqual(entry_for(later).diff_odometer, 250)

	def test_correcting_a_mid_history_fill_re_measures_the_next_one(self):
		tanker, truck = self.setup_truck(2)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		middle = dispense(tanker, truck, 90, odometer_km=1600, date=day(-6), posting_time="08:00:00")
		later = dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		middle.correct_reading(1800, "read 1600 off the wrong truck")

		later.reload()
		self.assertEqual(entry_for(middle).diff_odometer, 300)
		self.assertEqual(later.previous_odometer_km, 1800)
		self.assertEqual(entry_for(later).diff_odometer, 200)
		self.assertEqual(reading(truck), 2000, "the newest reading still stands")

	def test_correcting_the_latest_fill_moves_the_resource_reading(self):
		tanker, truck = self.setup_truck(3)
		doc = dispense(tanker, truck, 100, odometer_km=1900, date=day(-2), posting_time="08:00:00")

		doc.correct_reading(1090, "digits transposed")

		self.assertEqual(entry_for(doc).diff_odometer, 90)
		self.assertEqual(reading(truck), 1090)

	def test_correction_must_still_fit_between_its_neighbours(self):
		tanker, truck = self.setup_truck(4)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		middle = dispense(tanker, truck, 90, odometer_km=1700, date=day(-6), posting_time="08:00:00")
		dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		with self.assertRaises(frappe.ValidationError):
			middle.correct_reading(2500, "overtakes the later fill")
		with self.assertRaises(frappe.ValidationError):
			middle.correct_reading(1400, "falls behind the earlier fill")

		self.assertEqual(frappe.db.get_value("Fuel Used", middle.name, "odometer_km"), 1700)
		self.assertEqual(entry_for(middle).diff_odometer, 200)

	def test_reason_and_a_real_change_are_required(self):
		tanker, truck = self.setup_truck(5)
		doc = dispense(tanker, truck, 100, odometer_km=1500, date=day(-2), posting_time="08:00:00")

		for value, reason in ((1600, ""), (1600, "   "), (1500, "same"), (0, "zero"), (-5, "negative")):
			with self.assertRaises(frappe.ValidationError):
				doc.correct_reading(value, reason)
		self.assertEqual(frappe.db.get_value("Fuel Used", doc.name, "odometer_km"), 1500)

	def test_only_submitted_metered_fills_can_be_corrected(self):
		tanker, truck = self.setup_truck(6)
		draft = dispense(tanker, truck, 100, odometer_km=1500, submit=False)
		with self.assertRaises(frappe.ValidationError):
			draft.correct_reading(1600, "still a draft")

		misc = issue_miscellaneous(tanker, 10)
		with self.assertRaises(frappe.ValidationError):
			misc.correct_reading(1600, "no resource")

		faulty = make_resource("TEST-FT-RC-FAULTY", "Truck", reading=1000, has_faulty_meter=1).name
		unmetered = dispense(tanker, faulty, 50)
		with self.assertRaises(frappe.ValidationError):
			unmetered.correct_reading(1600, "no reading recorded")

	def test_equipment_hours_are_corrected_the_same_way(self):
		tanker = make_tanker("TEST-FT-RC-7").name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")
		eq = make_resource("TEST-FT-RC-EQ7", "Equipment", reading=100).name
		first = dispense(tanker, eq, 50, hours_copy=1200, date=day(-6), posting_time="08:00:00")
		later = dispense(tanker, eq, 40, hours_copy=1300, date=day(-2), posting_time="08:00:00")

		first.correct_reading(120, "extra zero keyed")

		later.reload()
		self.assertEqual(entry_for(first).diff_hours_copy, 20)
		self.assertEqual(later.previous_hours_copy, 120)
		self.assertEqual(entry_for(later).diff_hours_copy, 1180)
		self.assertEqual(reading(eq, "current_hours"), 1300)

	def test_correction_is_logged_on_the_fill_and_the_resource(self):
		tanker, truck = self.setup_truck(8)
		doc = dispense(tanker, truck, 100, odometer_km=1500, date=day(-2), posting_time="08:00:00")

		doc.correct_reading(1450, "pump attendant misread the dial")

		for doctype, name in (("Fuel Used", doc.name), ("Resource", truck)):
			comments = frappe.get_all(
				"Comment",
				filters={"reference_doctype": doctype, "reference_name": name, "comment_type": "Comment"},
				pluck="content",
			)
			note = next((c for c in comments if "pump attendant misread the dial" in c), "")
			self.assertIn("1500", note)
			self.assertIn("1450", note)
			self.assertIn("Administrator", note)

	def test_fuel_tracker_manager_may_correct(self):
		tanker, truck = self.setup_truck(9)
		doc = dispense(tanker, truck, 100, odometer_km=1500, date=day(-2), posting_time="08:00:00")
		manager = make_user("test-ft-rc-manager@example.com", "Fuel Tracker Manager")

		frappe.set_user(manager)
		frappe.get_doc("Fuel Used", doc.name).correct_reading(1400, "misread")
		frappe.set_user("Administrator")

		self.assertEqual(reading(truck), 1400)

	def test_attendant_may_not_correct(self):
		tanker, truck = self.setup_truck(10)
		doc = dispense(tanker, truck, 100, odometer_km=1500, date=day(-2), posting_time="08:00:00")
		attendant = make_user("test-ft-rc-attendant@example.com", "Fuel Tracker Attendant")

		frappe.set_user(attendant)
		with self.assertRaises(frappe.PermissionError):
			doc.correct_reading(1400, "not allowed")
		frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Fuel Used", doc.name, "odometer_km"), 1500)
		self.assertEqual(reading(truck), 1500)


class TestOpeningReadingCorrection(FrappeTestCase):
	"""The previous reading on a resource's first fill is its opening reading.

	On any other fill the previous reading is the fill before it, and is fixed
	by correcting that fill. The first fill had nothing to correct it from.
	"""

	def setUp(self):
		frappe.set_user("Administrator")

	def setup_truck(self, suffix, opening=1000):
		tanker = make_tanker("TEST-FT-RCO-{0}".format(suffix)).name
		truck = make_resource("TEST-FT-RCO-TRK{0}".format(suffix), "Truck", reading=opening).name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")
		return tanker, truck

	def test_first_fill_opening_reading_is_corrected(self):
		tanker, truck = self.setup_truck(1)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")
		litres_before = balance(tanker)

		first.correct_reading(1500, "opening keyed from the wrong truck", previous_reading=1200)

		first.reload()
		self.assertEqual(first.previous_odometer_km, 1200)
		self.assertEqual(first.odometer_km, 1500)
		self.assertEqual(entry_for(first).diff_odometer, 300)
		self.assertEqual(entry_for(later).diff_odometer, 500, "later fills are untouched")
		self.assertEqual(get_anchor_reading(truck, "Truck"), 1200, "the ledger now starts there")
		self.assertEqual(reading(truck), 2000)
		self.assertEqual(balance(tanker), litres_before, "no fuel moves")

	def test_opening_and_reading_corrected_together(self):
		tanker, truck = self.setup_truck(2)
		only = dispense(tanker, truck, 100, odometer_km=33535, date=day(-2), posting_time="08:00:00")

		only.correct_reading(33532, "both misread", previous_reading=33400)

		only.reload()
		self.assertEqual(only.previous_odometer_km, 33400)
		self.assertEqual(entry_for(only).diff_odometer, 132)
		self.assertEqual(reading(truck), 33532)

	def test_previous_reading_of_a_later_fill_points_to_the_fill_before(self):
		tanker, truck = self.setup_truck(3)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		with self.assertRaises(frappe.ValidationError) as caught:
			later.correct_reading(2000, "wrong place", previous_reading=1400)
		self.assertIn(first.name, str(caught.exception))
		self.assertEqual(frappe.db.get_value("Fuel Used", later.name, "previous_odometer_km"), 1500)

		# unchanged previous reading is fine; only a change is refused
		later.correct_reading(1900, "typo", previous_reading=1500)
		self.assertEqual(entry_for(later).diff_odometer, 400)

	def test_opening_must_be_positive_and_not_above_the_reading(self):
		tanker, truck = self.setup_truck(4)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		for opening, new_reading in ((1600, None), (0, None), (-5, None), (900, 2100)):
			with self.assertRaises(frappe.ValidationError):
				first.correct_reading(new_reading, "bad opening", previous_reading=opening)

		first.reload()
		self.assertEqual(first.previous_odometer_km, 1000)
		self.assertEqual(first.odometer_km, 1500)
		self.assertEqual(get_anchor_reading(truck, "Truck"), 1000)

	def test_opening_held_by_a_cancelled_earlier_fill_is_corrected(self):
		"""Cancelled fills still anchor the sequence (see get_anchor_reading)."""
		tanker, truck = self.setup_truck(5)
		cancelled = dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		entry_for(cancelled).cancel()
		first = dispense(tanker, truck, 80, odometer_km=1700, date=day(-6), posting_time="08:00:00")
		self.assertEqual(first.previous_odometer_km, 1000)

		first.correct_reading(None, "opening was 1100", previous_reading=1100)

		self.assertEqual(entry_for(first).diff_odometer, 600)
		self.assertEqual(get_anchor_reading(truck, "Truck"), 1100)

		# cancelling everything restores the corrected opening, not the old one
		entry_for(first).cancel()
		self.assertEqual(reading(truck), 1100)

	def test_equipment_opening_hours(self):
		tanker = make_tanker("TEST-FT-RCO-6").name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")
		eq = make_resource("TEST-FT-RCO-EQ6", "Equipment", reading=100).name
		first = dispense(tanker, eq, 50, hours_copy=150, date=day(-6), posting_time="08:00:00")

		first.correct_reading(None, "hour meter misread", previous_reading=140)

		self.assertEqual(entry_for(first).diff_hours_copy, 10)
		self.assertEqual(reading(eq, "current_hours"), 150)

	def test_onload_tells_the_form_which_fill_holds_the_previous_reading(self):
		tanker, truck = self.setup_truck(7)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		for doc, expected in ((first, None), (later, first.name)):
			loaded = frappe.get_doc("Fuel Used", doc.name)
			loaded.run_method("onload")
			self.assertEqual(loaded.get_onload().get("previous_fill"), expected)

	def test_opening_correction_is_logged(self):
		tanker, truck = self.setup_truck(8)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-2), posting_time="08:00:00")

		first.correct_reading(None, "opening misread at handover", previous_reading=1050)

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Fuel Used", "reference_name": first.name, "comment_type": "Comment"},
			pluck="content",
		)
		note = next((c for c in comments if "opening misread at handover" in c), "")
		self.assertIn("opening", note)
		self.assertIn("1000", note)
		self.assertIn("1050", note)

	def test_attendant_may_not_correct_the_opening(self):
		tanker, truck = self.setup_truck(9)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-2), posting_time="08:00:00")
		attendant = make_user("test-ft-rc-attendant@example.com", "Fuel Tracker Attendant")

		frappe.set_user(attendant)
		try:
			with self.assertRaises(frappe.PermissionError):
				first.correct_reading(None, "not allowed", previous_reading=1100)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Fuel Used", first.name, "previous_odometer_km"), 1000)


class TestClashingFillIsNamed(FrappeTestCase):
	"""A rejected reading names the fill it clashes with.

	Usually that fill holds the mistake — a reading keyed too high blocks
	every correct one after it — and it is the one to correct.
	"""

	def setUp(self):
		frappe.set_user("Administrator")

	def setup_truck(self, suffix, opening=1000):
		tanker = make_tanker("TEST-FT-RCN-{0}".format(suffix)).name
		truck = make_resource("TEST-FT-RCN-TRK{0}".format(suffix), "Truck", reading=opening).name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")
		return tanker, truck

	def test_backwards_reading_names_the_fill_before(self):
		tanker, truck = self.setup_truck(1)
		typo = dispense(tanker, truck, 90, odometer_km=17500, date=day(-6), posting_time="08:00:00")

		with self.assertRaises(frappe.ValidationError) as caught:
			dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00")
		self.assertIn(typo.name, str(caught.exception))
		self.assertIn("Correct Reading", str(caught.exception))

	def test_overtaking_reading_names_the_fill_after(self):
		tanker, truck = self.setup_truck(2)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 100, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		with self.assertRaises(frappe.ValidationError) as caught:
			dispense(tanker, truck, 50, odometer_km=2500, date=day(-6), posting_time="08:00:00")
		self.assertIn(later.name, str(caught.exception))

	def test_reading_below_the_opening_names_no_fill(self):
		tanker, truck = self.setup_truck(3, opening=1200)

		with self.assertRaises(frappe.ValidationError) as caught:
			dispense(tanker, truck, 20, odometer_km=1150)
		self.assertIn("opening reading", str(caught.exception))
		self.assertNotIn("Correct Reading", str(caught.exception))

	def test_draft_blocked_by_a_typo_submits_once_the_typo_is_corrected(self):
		"""The workflow: keep the new fill as a draft, fix the old one, submit."""
		tanker, truck = self.setup_truck(4)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		typo = dispense(tanker, truck, 90, odometer_km=17500, date=day(-6), posting_time="08:00:00")

		draft = dispense(tanker, truck, 80, odometer_km=2000, date=day(-2), posting_time="08:00:00", submit=False)
		with self.assertRaises(frappe.ValidationError):
			draft.submit()
		draft = frappe.get_doc("Fuel Used", draft.name)
		self.assertEqual(draft.docstatus, 0, "the draft and its reading survive")
		self.assertEqual(draft.odometer_km, 2000)

		typo.correct_reading(1750, "extra zero keyed")
		draft.submit()

		draft.reload()
		self.assertEqual(draft.previous_odometer_km, 1750)
		self.assertEqual(entry_for(draft).diff_odometer, 250)
		self.assertEqual(reading(truck), 2000)
