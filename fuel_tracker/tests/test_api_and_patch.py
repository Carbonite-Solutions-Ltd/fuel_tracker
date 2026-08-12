# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""The surfaces the doctype tests don't reach: whitelisted endpoints, the
backfill patch, and amending a cancelled document."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from fuel_tracker.api.dashboard import fuelBalance
from fuel_tracker.api.fuel_used import get_filtered_items
from fuel_tracker.fuel_tracker.fuel_ledger import (
	entry_delta,
	get_ledger_entries,
	get_tanker_balance_on,
)
from fuel_tracker.patches.v1_0.backfill_posting_datetime import execute as run_backfill_patch
from fuel_tracker.tests.utils import (
	balance,
	dispense,
	entry_for,
	make_resource,
	make_tanker,
	request_supply,
	supply,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


def assert_ledger_continuous(case, tanker):
	running = None
	for entry in get_ledger_entries(tanker):
		if entry.utilization_type == "Opening Balance":
			running = entry.current_balance
			continue
		running = 0 if running is None else running
		case.assertEqual(entry.previous_balance, running, "chain breaks at {0}".format(entry.name))
		running = round(running + entry_delta(entry), 3)
		case.assertEqual(entry.current_balance, running)
	if running is not None:
		case.assertEqual(balance(tanker), running)


class TestWhitelistedEndpoints(FrappeTestCase):
	def test_get_tanker_balance_on_returns_the_balance_for_that_date(self):
		"""Backs the "balance on this date" hint on the desk forms."""
		tanker = make_tanker("TEST-FT-API-1").name
		supply(tanker, 700, date=day(-6), posting_time="08:00:00")
		supply(tanker, 200, date=day(-2), posting_time="08:00:00")

		self.assertEqual(get_tanker_balance_on(tanker, day(-7)), 0)
		self.assertEqual(get_tanker_balance_on(tanker, day(-6), "09:00:00"), 700)
		self.assertEqual(get_tanker_balance_on(tanker, day(-3), "23:59:59"), 700)
		self.assertEqual(get_tanker_balance_on(tanker, day(-1), "23:59:59"), 900)

	def test_dashboard_balance_reports_a_quiet_day(self):
		"""The old endpoint returned nothing unless the tanker moved that day."""
		tanker = make_tanker("TEST-FT-API-2")
		site = tanker.site
		tanker = tanker.name
		supply(tanker, 450, date=day(-9), posting_time="08:00:00")

		# no movement since day -9, but the tanker still holds 450 L today
		self.assertEqual(fuelBalance(site, tanker), 450)
		self.assertEqual(fuelBalance(site, tanker, date=day(-9)), 450)
		self.assertEqual(fuelBalance(site, tanker, date=day(-10)), 0)

	def test_dashboard_balance_is_not_ordered_by_modified(self):
		"""Reposts deliberately leave `modified` alone, so it cannot order the ledger."""
		tanker = make_tanker("TEST-FT-API-3").name
		truck = make_resource("TEST-FT-API-TRK1", "Truck", reading=1000).name
		site = frappe.db.get_value("Fuel Tanker", tanker, "site")

		supply(tanker, 800, date=day(-8), posting_time="08:00:00")
		dispense(tanker, truck, 100, odometer_km=1100, date=day(-4), posting_time="08:00:00")
		# a backdated insert reposts the later entry without touching `modified`
		supply(tanker, 300, date=day(-6), posting_time="08:00:00")

		self.assertEqual(fuelBalance(site, tanker), 1000)

	def test_resource_list_exposes_the_faulty_meter_flag(self):
		"""The mobile client needs this to know whether to demand a reading."""
		make_resource("TEST-FT-API-TRK2", "Truck", reading=500, has_faulty_meter=1)

		result = get_filtered_items()
		rows = {r["name"]: r for r in result["data"]}

		self.assertEqual(result["status"], "success")
		self.assertIn("has_faulty_meter", rows["TEST-FT-API-TRK2"])
		self.assertEqual(rows["TEST-FT-API-TRK2"]["has_faulty_meter"], 1)


class TestBackfillPatch(FrappeTestCase):
	def test_patch_is_idempotent(self):
		"""Re-running the backfill must not shift any balance."""
		tanker = make_tanker("TEST-FT-PATCH-1").name
		truck = make_resource("TEST-FT-PATCH-TRK1", "Truck", reading=1000).name

		supply(tanker, 900, date=day(-7), posting_time="08:00:00")
		dispense(tanker, truck, 120, odometer_km=1150, date=day(-4), posting_time="08:00:00")
		supply(tanker, 60, date=day(-2), posting_time="08:00:00")

		before = balance(tanker)
		snapshot = {e.name: (e.previous_balance, e.current_balance) for e in get_ledger_entries(tanker)}

		run_backfill_patch()
		run_backfill_patch()

		self.assertEqual(balance(tanker), before)
		after = {e.name: (e.previous_balance, e.current_balance) for e in get_ledger_entries(tanker)}
		self.assertEqual(snapshot, after)
		assert_ledger_continuous(self, tanker)

	def test_patch_repairs_a_drifted_ledger(self):
		"""The repost is what makes historical balances trustworthy."""
		tanker = make_tanker("TEST-FT-PATCH-2").name
		supply(tanker, 500, date=day(-5), posting_time="08:00:00")
		supply(tanker, 250, date=day(-3), posting_time="08:00:00")
		self.assertEqual(balance(tanker), 750)

		# simulate the drift the old append-only arithmetic could leave behind
		last = get_ledger_entries(tanker)[-1]
		frappe.db.set_value(
			"Fuel Entry", last.name,
			{"previous_balance": 0, "current_balance": 42},
			update_modified=False,
		)

		run_backfill_patch()

		assert_ledger_continuous(self, tanker)
		self.assertEqual(balance(tanker), 750)


class TestAmendFlow(FrappeTestCase):
	def test_amending_a_cancelled_supply_reposts_correctly(self):
		tanker = make_tanker("TEST-FT-AMD-1").name
		request = request_supply(tanker, 500)
		doc = supply(tanker, 500, request=request.name)
		self.assertEqual(balance(tanker), 500)

		entry_for(doc).cancel()
		self.assertEqual(balance(tanker), 0)

		doc.reload()
		amended = frappe.copy_doc(doc)
		amended.amended_from = doc.name
		amended.docstatus = 0
		amended.fuel_supplied = 480  # the delivery was short
		amended.insert()
		amended.submit()

		self.assertEqual(balance(tanker), 480)
		request.reload()
		self.assertEqual(request.supplied_litres, 480)
		self.assertEqual(request.status, "Partially Supplied")
		assert_ledger_continuous(self, tanker)

	def test_amended_supply_still_needs_a_valid_request(self):
		tanker_a = make_tanker("TEST-FT-AMD-2A").name
		tanker_b = make_tanker("TEST-FT-AMD-2B").name
		request = request_supply(tanker_a, 300)
		doc = supply(tanker_a, 300, request=request.name)
		entry_for(doc).cancel()

		doc.reload()
		amended = frappe.copy_doc(doc)
		amended.amended_from = doc.name
		amended.docstatus = 0
		amended.fuel_tanker = tanker_b  # now points at the wrong tanker's request
		amended.insert()

		with self.assertRaises(frappe.ValidationError):
			amended.submit()
