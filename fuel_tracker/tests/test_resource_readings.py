# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""Date-aware odometer / hour-meter readings.

Backdating fuel was only half-implemented until readings became date-aware
too: a `Fuel Used` took its previous reading from the live `Resource`, which
holds the newest reading of all, so keying in a fill that was missed last week
was rejected for "going backwards".
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.fuel_tracker.resource_ledger import get_reading_documents
from fuel_tracker.tests.utils import (
	dispense,
	entry_for,
	make_resource,
	make_tanker,
	supply,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


def reading(resource, field="current_odometer"):
	return frappe.db.get_value("Resource", resource, field)


class TestResourceReadings(FrappeTestCase):
	def setup_truck(self, suffix, opening=1000, litres=5000):
		tanker = make_tanker("TEST-FT-RR-{0}".format(suffix)).name
		truck = make_resource("TEST-FT-RR-TRK{0}".format(suffix), "Truck", reading=opening).name
		supply(tanker, litres, date=day(-30), posting_time="08:00:00")
		return tanker, truck

	def test_backdated_fill_uses_the_reading_from_its_own_date(self):
		"""The regression: a late entry was measured against today's odometer."""
		tanker, truck = self.setup_truck(1)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 120, odometer_km=2000, date=day(-2), posting_time="08:00:00")
		self.assertEqual(entry_for(later).diff_odometer, 500)

		# a fill missed on day -6, when the odometer genuinely read 1750
		late = dispense(tanker, truck, 90, odometer_km=1750, date=day(-6), posting_time="08:00:00")

		self.assertEqual(late.docstatus, 1)
		self.assertEqual(late.previous_odometer_km, 1500)
		self.assertEqual(entry_for(late).diff_odometer, 250)
		# the fill that follows it is re-measured from the inserted reading
		self.assertEqual(entry_for(later).diff_odometer, 250)
		self.assertEqual(reading(truck), 2000, "the newest reading still stands")

	def test_reading_may_not_overtake_a_later_one(self):
		tanker, truck = self.setup_truck(2)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		dispense(tanker, truck, 100, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 50, odometer_km=2500, date=day(-6), posting_time="08:00:00")

	def test_reading_may_not_fall_behind_an_earlier_one(self):
		tanker, truck = self.setup_truck(3)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")

		with self.assertRaises(frappe.ValidationError):
			dispense(tanker, truck, 50, odometer_km=1400, date=day(-6), posting_time="08:00:00")

	def test_resource_holds_the_newest_reading_not_the_last_submitted(self):
		tanker, truck = self.setup_truck(4)
		dispense(tanker, truck, 100, odometer_km=2000, date=day(-2), posting_time="08:00:00")
		self.assertEqual(reading(truck), 2000)

		# submitted later, but posted earlier — must not drag the resource back
		dispense(tanker, truck, 80, odometer_km=1600, date=day(-8), posting_time="08:00:00")
		self.assertEqual(reading(truck), 2000)

	def test_cancelling_a_mid_history_fill_reposts_the_distances(self):
		tanker, truck = self.setup_truck(5)
		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		middle = dispense(tanker, truck, 90, odometer_km=1750, date=day(-6), posting_time="08:00:00")
		last = dispense(tanker, truck, 120, odometer_km=2000, date=day(-2), posting_time="08:00:00")
		self.assertEqual(entry_for(last).diff_odometer, 250)

		entry_for(middle).cancel()

		# the gap the cancelled fill used to split is measured whole again
		self.assertEqual(entry_for(last).diff_odometer, 500)
		self.assertEqual(reading(truck), 2000)

	def test_cancelling_every_fill_restores_the_opening_reading(self):
		tanker, truck = self.setup_truck(6, opening=1000)
		first = dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		second = dispense(tanker, truck, 120, odometer_km=2000, date=day(-2), posting_time="08:00:00")

		entry_for(second).cancel()
		self.assertEqual(reading(truck), 1500)
		entry_for(first).cancel()
		self.assertEqual(reading(truck), 1000, "back to where the truck started")

	def test_equipment_hours_follow_the_same_rules(self):
		tanker = make_tanker("TEST-FT-RR-7").name
		eq = make_resource("TEST-FT-RR-EQ7", "Equipment", reading=100).name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")

		dispense(tanker, eq, 50, hours_copy=150, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, eq, 40, hours_copy=200, date=day(-2), posting_time="08:00:00")

		mid = dispense(tanker, eq, 30, hours_copy=175, date=day(-6), posting_time="08:00:00")

		self.assertEqual(entry_for(mid).diff_hours_copy, 25)
		self.assertEqual(entry_for(later).diff_hours_copy, 25)
		self.assertEqual(reading(eq, "current_hours"), 200)

	def test_faulty_meter_fills_sit_outside_the_sequence(self):
		"""They record no reading, so they neither supply nor consume one."""
		tanker = make_tanker("TEST-FT-RR-8").name
		truck = make_resource("TEST-FT-RR-TRK8", "Truck", reading=1000, has_faulty_meter=1).name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")

		dispense(tanker, truck, 60, date=day(-10), posting_time="08:00:00")
		dispense(tanker, truck, 70, date=day(-5), posting_time="08:00:00")

		self.assertEqual(get_reading_documents(truck, "Truck"), [])
		self.assertEqual(reading(truck), 1000, "an unread meter cannot move the reading")

	def test_repaired_meter_measures_across_the_outage(self):
		tanker = make_tanker("TEST-FT-RR-9").name
		truck = make_resource("TEST-FT-RR-TRK9", "Truck", reading=1000).name
		supply(tanker, 5000, date=day(-30), posting_time="08:00:00")

		dispense(tanker, truck, 100, odometer_km=1500, date=day(-20), posting_time="08:00:00")

		resource = frappe.get_doc("Resource", truck)
		resource.has_faulty_meter = 1
		resource.faulty_meter_remarks = "Meter failed"
		resource.save()
		dispense(tanker, truck, 80, date=day(-15), posting_time="08:00:00")

		resource.reload()
		resource.has_faulty_meter = 0
		resource.faulty_meter_remarks = None
		resource.save()
		repaired = dispense(tanker, truck, 90, odometer_km=2200, date=day(-5), posting_time="08:00:00")

		# distance spans the outage, measured from the last trustworthy reading
		self.assertEqual(repaired.previous_odometer_km, 1500)
		self.assertEqual(entry_for(repaired).diff_odometer, 700)
		self.assertEqual(reading(truck), 2200)
