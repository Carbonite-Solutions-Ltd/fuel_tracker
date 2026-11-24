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
