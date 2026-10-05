# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from fuel_tracker.tests.utils import (
	balance,
	dispense,
	entry_for,
	issue_miscellaneous,
	make_resource,
	make_tanker,
	messages_text,
	supply,
)

test_ignore = ["Item", "Company"]


class TestFuelUsed(FrappeTestCase):
	def test_truck_dispense_updates_ledger_and_resource(self):
		tanker = make_tanker("TEST-FT-FU-1").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FU-TRK1", "Truck", reading=1000).name

		doc = dispense(tanker, truck, 50, odometer_km=1100)

		self.assertEqual(balance(tanker), 450)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1100)
		entry = entry_for(doc)
		self.assertEqual(entry.utilization_type, "Dispensed")
		self.assertEqual(entry.litres_dispensed, 50)
		self.assertEqual(entry.diff_odometer, 100)

	def test_equipment_dispense_updates_hours(self):
		tanker = make_tanker("TEST-FT-FU-2").name
		supply(tanker, 500)
		eq = make_resource("TEST-FT-FU-EQ1", "Equipment", reading=100).name

		doc = dispense(tanker, eq, 30, hours_copy=110)

		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 110)
		self.assertEqual(entry_for(doc).diff_hours_copy, 10)

	def test_stale_draft_refreshes_previous_reading(self):
		tanker = make_tanker("TEST-FT-FU-3").name
		supply(tanker, 500)
		eq = make_resource("TEST-FT-FU-EQ2", "Equipment", reading=100).name

		stale = dispense(tanker, eq, 50, hours_copy=110, submit=False)
		dispense(tanker, eq, 30, hours_copy=105)  # moves the live reading to 105
		stale.submit()
		stale.reload()

		# the draft's previous reading must be re-read from the live resource
		self.assertEqual(stale.previous_hours_copy, 105)
		self.assertEqual(entry_for(stale).diff_hours_copy, 5)
		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 110)

	def test_reading_below_live_blocked(self):
		tanker = make_tanker("TEST-FT-FU-4").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FU-TRK2", "Truck", reading=1200).name

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 20, odometer_km=1150)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1200)

	def test_zero_and_negative_litres_blocked(self):
		tanker = make_tanker("TEST-FT-FU-5").name
		truck = make_resource("TEST-FT-FU-TRK3", "Truck", reading=100).name
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 0, odometer_km=200)
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, -10, odometer_km=200)

	def test_overdraw_warning_is_non_blocking(self):
		tanker = make_tanker("TEST-FT-FU-6").name
		supply(tanker, 10)
		truck = make_resource("TEST-FT-FU-TRK4", "Truck", reading=100).name

		frappe.clear_messages()
		doc = dispense(tanker, truck, 50, odometer_km=200)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), -40)
		self.assertIn("exceeds the balance of tanker", messages_text())

	def test_missing_previous_reading_blocked(self):
		# the resource must carry an initial reading before fuel can be
		# dispensed against it
		tanker = make_tanker("TEST-FT-FU-8").name
		supply(tanker, 100)
		truck = make_resource("TEST-FT-FU-TRK6", "Truck", reading=0).name
		eq = make_resource("TEST-FT-FU-EQ3", "Equipment", reading=0).name

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 10, odometer_km=500)
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, eq, 10, hours_copy=50)

	def test_quantity_and_current_reading_mandatory(self):
		tanker = make_tanker("TEST-FT-FU-9").name
		truck = make_resource("TEST-FT-FU-TRK7", "Truck", reading=100).name
		site = frappe.db.get_value("Fuel Tanker", tanker, "site")

		# the fuel quantity is hard-mandatory, even for drafts
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({
				"doctype": "Fuel Used", "date": today(), "fuel_tanker": tanker,
				"site": site, "resource": truck, "odometer_km": 200,
			}).insert()

		# a draft without the current reading may exist (incoming mobile
		# reports), but it cannot be submitted
		doc = frappe.get_doc({
			"doctype": "Fuel Used", "date": today(), "fuel_tanker": tanker,
			"site": site, "resource": truck, "fuel_issued_lts": 10,
		})
		doc.insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_below_minimum_level_warning(self):
		tanker = make_tanker("TEST-FT-FU-7", minimum_level=100).name
		supply(tanker, 150)
		truck = make_resource("TEST-FT-FU-TRK5", "Truck", reading=100).name

		frappe.clear_messages()
		doc = dispense(tanker, truck, 100, odometer_km=200)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 50)
		self.assertIn("minimum level", messages_text())


class TestFuelUsedFaultyMeter(FrappeTestCase):
	"""Dispensing to a vehicle or machine whose meter is broken."""

	def test_truck_with_faulty_odometer_needs_no_reading(self):
		tanker = make_tanker("TEST-FT-FM-1").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FM-TRK1", "Truck", reading=1000, has_faulty_meter=1).name

		doc = dispense(tanker, truck, 60)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 440)
		entry = entry_for(doc)
		self.assertEqual(entry.litres_dispensed, 60)
		# the flag is what marks the entry unmeasured; no distance is claimed
		self.assertTrue(entry.meter_faulty)
		self.assertEqual(entry.diff_odometer, 0)

	def test_equipment_with_faulty_hour_meter_needs_no_reading(self):
		tanker = make_tanker("TEST-FT-FM-2").name
		supply(tanker, 500)
		eq = make_resource("TEST-FT-FM-EQ1", "Equipment", reading=100, has_faulty_meter=1).name

		doc = dispense(tanker, eq, 40)

		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(entry_for(doc).meter_faulty)
		self.assertEqual(entry_for(doc).diff_hours_copy, 0)

	def test_faulty_meter_resource_needs_no_prior_reading_at_all(self):
		"""A meter that never worked has no reading to start from."""
		tanker = make_tanker("TEST-FT-FM-3").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FM-TRK2", "Truck", reading=0, has_faulty_meter=1).name

		doc = dispense(tanker, truck, 25)

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 475)

	def test_faulty_meter_does_not_overwrite_the_resource_reading(self):
		tanker = make_tanker("TEST-FT-FM-4").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FM-TRK3", "Truck", reading=5000, has_faulty_meter=1).name

		# a bogus reading from a broken meter must not become the new truth
		dispense(tanker, truck, 30, odometer_km=12)

		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 5000)

	def test_healthy_resource_still_requires_a_reading(self):
		tanker = make_tanker("TEST-FT-FM-5").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FM-TRK4", "Truck", reading=1000).name

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 20)

	def test_faulty_meter_dispense_is_excluded_from_consumption_alerts(self):
		from fuel_tracker.fuel_tracker.report.average_fuel_consumption_ledger.average_fuel_consumption_ledger import (
			execute,
		)

		tanker = make_tanker("TEST-FT-FM-6").name
		supply(tanker, 500)
		truck = make_resource(
			"TEST-FT-FM-TRK5", "Truck", reading=1000, average_consumption=0.2, has_faulty_meter=1
		).name

		dispense(tanker, truck, 50)
		dispense(tanker, truck, 60)

		_columns, data = execute({"resource": truck})
		self.assertTrue(data)
		for row in data:
			# without a reading there is no km to divide by; the row is
			# flagged rather than scored as a 0 km/L outlier
			self.assertEqual(row["alert_status"], "Meter Faulty")
			self.assertEqual(row["consumption"], 0)

	def test_repaired_meter_resumes_normal_validation(self):
		tanker = make_tanker("TEST-FT-FM-7").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-FM-TRK6", "Truck", reading=1000, has_faulty_meter=1).name

		dispense(tanker, truck, 40)

		resource = frappe.get_doc("Resource", truck)
		resource.has_faulty_meter = 0
		resource.faulty_meter_remarks = None
		resource.save()

		# back under the usual rules: a reading is required and cannot go back
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 20)
		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 20, odometer_km=900)

		doc = dispense(tanker, truck, 20, odometer_km=1200)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(entry_for(doc).diff_odometer, 200)


class TestFuelUsedMiscellaneous(FrappeTestCase):
	"""Fuel issued for site use — cleaning tools and the like — with no resource."""

	def test_miscellaneous_issue_needs_no_resource(self):
		tanker = make_tanker("TEST-FT-MI-1").name
		supply(tanker, 500)

		doc = issue_miscellaneous(tanker, 20, description="Washing down the mixer after the pour")

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(balance(tanker), 480)
		entry = entry_for(doc)
		self.assertEqual(entry.utilization_type, "Miscellaneous")
		self.assertEqual(entry.litres_dispensed, 20)
		self.assertFalse(entry.resource)

	def test_miscellaneous_requires_a_description(self):
		tanker = make_tanker("TEST-FT-MI-2").name
		supply(tanker, 500)

		with self.assertRaises(frappe.MandatoryError):
			issue_miscellaneous(tanker, 20, description=None)
		with self.assertRaises(frappe.MandatoryError):
			issue_miscellaneous(tanker, 20, description="   ")

	def test_normal_entry_still_requires_a_resource(self):
		tanker = make_tanker("TEST-FT-MI-3").name
		site = frappe.db.get_value("Fuel Tanker", tanker, "site")

		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({
				"doctype": "Fuel Used", "date": today(), "fuel_tanker": tanker,
				"site": site, "fuel_issued_lts": 10,
			}).insert()

	def test_entry_type_defaults_to_normal(self):
		tanker = make_tanker("TEST-FT-MI-4").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-MI-TRK4", "Truck", reading=1000).name

		doc = dispense(tanker, truck, 30, odometer_km=1100)

		self.assertEqual(doc.entry_type, "Normal")
		self.assertEqual(entry_for(doc).utilization_type, "Dispensed")

	def test_resource_picked_before_switching_is_dropped(self):
		"""Switching to Miscellaneous must not leave a stale resource behind."""
		tanker = make_tanker("TEST-FT-MI-5").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-MI-TRK5", "Truck", reading=1000).name

		doc = issue_miscellaneous(tanker, 15, resource=truck, odometer_km=5000)

		self.assertFalse(doc.resource)
		self.assertFalse(doc.odometer_km)
		self.assertFalse(entry_for(doc).resource)
		# the reading typed against it must not become the truck's reading
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1000)

	def test_miscellaneous_issue_leaves_the_reading_sequence_alone(self):
		tanker = make_tanker("TEST-FT-MI-6").name
		supply(tanker, 500)
		truck = make_resource("TEST-FT-MI-TRK6", "Truck", reading=1000).name

		dispense(tanker, truck, 40, odometer_km=1100)
		issue_miscellaneous(tanker, 10)
		second = dispense(tanker, truck, 30, odometer_km=1250)

		self.assertEqual(entry_for(second).diff_odometer, 150)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1250)
		self.assertEqual(balance(tanker), 420)

	def test_cancelling_the_entry_cancels_the_issue_and_restores_the_balance(self):
		tanker = make_tanker("TEST-FT-MI-7").name
		supply(tanker, 500)

		doc = issue_miscellaneous(tanker, 25)
		self.assertEqual(balance(tanker), 475)

		entry_for(doc).cancel()

		self.assertEqual(balance(tanker), 500)
		self.assertEqual(frappe.db.get_value("Fuel Used", doc.name, "docstatus"), 2)

	def test_backdated_miscellaneous_issue_reposts_later_balances(self):
		from frappe.utils import add_days

		tanker = make_tanker("TEST-FT-MI-8").name
		supply(tanker, 500, date=add_days(today(), -5), posting_time="08:00:00")
		later = supply(tanker, 100, date=add_days(today(), -1), posting_time="08:00:00")

		issue_miscellaneous(tanker, 50, date=add_days(today(), -3), posting_time="08:00:00")

		self.assertEqual(entry_for(later).previous_balance, 450)
		self.assertEqual(balance(tanker), 550)
