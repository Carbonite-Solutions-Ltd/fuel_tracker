# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""Report figures, and the specific ways they used to be wrong."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from fuel_tracker.fuel_tracker.report.average_fuel_consumption_ledger.average_fuel_consumption_ledger import (
	execute as consumption_execute,
)
from fuel_tracker.fuel_tracker.report.fuel_balance.fuel_balance import execute as balance_execute
from fuel_tracker.fuel_tracker.report.fuel_ledger.fuel_ledger import execute as ledger_execute
from fuel_tracker.fuel_tracker.report.fuel_supply_request_status.fuel_supply_request_status import (
	execute as request_execute,
)
from fuel_tracker.fuel_tracker.report.fuel_transfer_register.fuel_transfer_register import (
	execute as transfer_execute,
)
from fuel_tracker.fuel_tracker.report.resource_fuel_summary.resource_fuel_summary import (
	execute as summary_execute,
)
from fuel_tracker.tests.utils import (
	adjust,
	balance,
	dispense,
	ensure_site,
	entry_for,
	make_resource,
	make_tanker,
	request_supply,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


def open_balance(tanker, amount, date=None):
	"""Submit the tanker's opening balance, reusing the lazily created row."""
	name = frappe.db.get_value("Fuel Balance", {"fuel_tanker": tanker}, "name")
	if name:
		doc = frappe.get_doc("Fuel Balance", name)
		doc.balance = amount
		doc.date = date or today()
		doc.save()
	else:
		doc = frappe.get_doc({
			"doctype": "Fuel Balance",
			"fuel_tanker": tanker,
			"balance": amount,
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
			"date": date or today(),
		})
		doc.insert()
	doc.submit()
	return doc


def row_for(rows, tanker):
	matches = [r for r in rows if r["fuel_tanker"] == tanker]
	return matches[0] if matches else None


class TestFuelBalanceReport(FrappeTestCase):
	def test_closing_matches_the_doctype_and_row_reconciles(self):
		tanker = make_tanker("TEST-FT-RA-1", minimum_level=1000).name
		open_balance(tanker, 200, date=day(-10))
		supply(tanker, 120, date=day(-8), posting_time="08:00:00")
		truck = make_resource("TEST-FT-RA-TRK1", "Truck", reading=100).name
		dispense(tanker, truck, 30, odometer_km=200, date=day(-6), posting_time="08:00:00")
		adjust(tanker, mode="Quantity", quantity=-40, date=day(-4), posting_time="08:00:00")

		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		row = row_for(rows, tanker)

		self.assertEqual(row["litres_supplied"], 120)
		self.assertEqual(row["litres_dispensed"], 30)
		self.assertEqual(row["litres_adjusted"], -40)
		self.assertEqual(row["opening_entry"], 200)
		self.assertEqual(row["current_balance"], 250)
		self.assertEqual(row["current_balance"], balance(tanker))
		self.assertEqual(row["difference"], 0)
		self.assertEqual(row["status"], "Low")  # 250 < minimum_level 1000

	def test_tanker_is_not_split_when_entries_carry_different_sites(self):
		"""The bug that made a tanker show up as two part-rows."""
		site_a = ensure_site("TEST-FT-RA-SITE-A")
		site_b = ensure_site("TEST-FT-RA-SITE-B")
		tanker = make_tanker("TEST-FT-RA-2", site=site_a).name
		truck = make_resource("TEST-FT-RA-TRK2", "Truck", reading=100).name

		supply(tanker, 900, date=day(-8), posting_time="08:00:00")
		# the site on Fuel Used is keyed by hand and need not match the tanker's
		doc = dispense(tanker, truck, 100, odometer_km=300, date=day(-5), posting_time="08:00:00")
		frappe.db.set_value("Fuel Entry", entry_for(doc).name, "site", site_b, update_modified=False)

		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})

		self.assertEqual(len(rows), 1, "the tanker must produce exactly one row")
		self.assertEqual(rows[0]["site"], site_a, "the site shown is the tanker's own")
		self.assertEqual(rows[0]["current_balance"], balance(tanker))
		self.assertEqual(rows[0]["current_balance"], 800)

	def test_movements_before_an_opening_balance_are_not_counted_twice(self):
		"""An opening balance supersedes whatever came before it.

		Nothing can be dated before an opening balance through normal use any
		more, so this reproduces the shape of the legacy data that exposed the
		bug: an entry dragged behind the opening entry after the fact.
		"""
		from fuel_tracker.fuel_tracker.fuel_ledger import repost_tanker

		tanker = make_tanker("TEST-FT-RA-3").name
		open_balance(tanker, 1000, date=day(-10))
		supply(tanker, 250, date=day(-5), posting_time="08:00:00")
		stray = supply(tanker, 500, date=day(-2), posting_time="08:00:00")

		# push it behind the opening entry, the way the old data ended up
		frappe.db.set_value(
			"Fuel Entry", entry_for(stray).name,
			{"date": day(-20), "posting_datetime": "{0} 08:00:00".format(day(-20))},
			update_modified=False,
		)
		repost_tanker(tanker)

		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		row = row_for(rows, tanker)

		# 1000 declared + 250 after it — the stray 500 sits before the opening
		# balance, which already accounts for it, so it must not be added on top
		self.assertEqual(row["current_balance"], 1250)
		self.assertEqual(row["current_balance"], balance(tanker))
		self.assertEqual(row["difference"], 0)

	def test_period_window_reconciles(self):
		tanker = make_tanker("TEST-FT-RA-4").name
		truck = make_resource("TEST-FT-RA-TRK4", "Truck", reading=100).name

		supply(tanker, 1000, date=day(-20), posting_time="08:00:00")
		supply(tanker, 300, date=day(-5), posting_time="08:00:00")
		dispense(tanker, truck, 200, odometer_km=400, date=day(-3), posting_time="08:00:00")

		_cols, rows = balance_execute(
			{"from_date": day(-10), "to_date": today(), "fuel_tanker": [tanker]}
		)
		row = row_for(rows, tanker)

		self.assertEqual(row["opening_balance"], 1000)   # everything before the window
		self.assertEqual(row["litres_supplied"], 300)    # inside the window only
		self.assertEqual(row["litres_dispensed"], 200)
		self.assertEqual(row["current_balance"], 1100)
		self.assertEqual(row["difference"], 0)

	def test_transfers_are_shown_in_their_own_columns(self):
		site_a = ensure_site("TEST-FT-RA-SITE-A")
		site_b = ensure_site("TEST-FT-RA-SITE-B")
		source = make_tanker("TEST-FT-RA-5A", site=site_a).name
		dest = make_tanker("TEST-FT-RA-5B", site=site_b).name

		supply(source, 900, date=day(-6), posting_time="08:00:00")
		transfer(source, dest, 400, date=day(-3), posting_time="08:00:00")

		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [source, dest]})
		out_row, in_row = row_for(rows, source), row_for(rows, dest)

		self.assertEqual(out_row["transferred_out"], 400)
		self.assertEqual(out_row["litres_dispensed"], 0, "a transfer is not a dispense")
		self.assertEqual(out_row["current_balance"], 500)
		self.assertEqual(in_row["transferred_in"], 400)
		self.assertEqual(in_row["litres_supplied"], 0, "a transfer is not a purchase")
		self.assertEqual(in_row["current_balance"], 400)
		self.assertEqual(out_row["difference"], 0)
		self.assertEqual(in_row["difference"], 0)


class TestFuelLedgerReport(FrappeTestCase):
	def test_running_balance_is_continuous_in_report_order(self):
		tanker = make_tanker("TEST-FT-RA-6").name
		truck = make_resource("TEST-FT-RA-TRK6", "Truck", reading=100).name

		supply(tanker, 500, date=day(-9), posting_time="08:00:00")
		dispense(tanker, truck, 50, odometer_km=200, date=day(-7), posting_time="08:00:00")
		# inserted out of order — the report must still read continuously
		supply(tanker, 200, date=day(-8), posting_time="08:00:00")

		_cols, rows = ledger_execute({"fuel_tanker": [tanker]})
		data = rows[:-1]

		running = None
		for row in data:
			if running is not None:
				self.assertEqual(row["previous_balance"], running)
			running = row["current_balance"]

		self.assertEqual(running, balance(tanker))
		self.assertEqual(rows[-1]["litres_supplied"], 700)
		self.assertEqual(rows[-1]["litres_dispensed"], 50)

	def test_rows_are_grouped_by_tanker(self):
		"""Balances are per tanker, so interleaving them would read as nonsense."""
		first = make_tanker("TEST-FT-RA-7A").name
		second = make_tanker("TEST-FT-RA-7B").name
		supply(first, 100, date=day(-5), posting_time="08:00:00")
		supply(second, 200, date=day(-4), posting_time="08:00:00")
		supply(first, 300, date=day(-3), posting_time="08:00:00")

		_cols, rows = ledger_execute({"fuel_tanker": [first, second]})
		tankers = [r["fuel_tanker"] for r in rows[:-1]]

		self.assertEqual(tankers, sorted(tankers), "rows must not interleave tankers")


class TestConsumptionReport(FrappeTestCase):
	def test_consumption_is_measured_tank_to_tank(self):
		tanker = make_tanker("TEST-FT-RA-8").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		eq = make_resource("TEST-FT-RA-EQ8", "Equipment", reading=100, average_consumption=10).name

		dispense(tanker, eq, 100, hours_copy=110, date=day(-10), posting_time="08:00:00")
		dispense(tanker, eq, 20, hours_copy=120, date=day(-5), posting_time="08:00:00")

		_cols, rows = consumption_execute({"resource": eq})
		second = [r for r in rows if r["litres_dispensed"] == 100][0]

		# 100 L put in at the first fill, 10 h covered before the second
		self.assertEqual(second["diff_hours"], 10)
		self.assertEqual(second["consumption"], 10)
		self.assertEqual(second["alert_status"], "Good")

	def test_statuses_name_the_reason_instead_of_showing_a_bogus_zero(self):
		tanker = make_tanker("TEST-FT-RA-9").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")

		first = make_resource("TEST-FT-RA-EQ9A", "Equipment", reading=100).name
		dispense(tanker, first, 50, hours_copy=110, date=day(-10), posting_time="08:00:00")

		# metered, but the machine did not run between fills
		still = make_resource("TEST-FT-RA-EQ9B", "Equipment", reading=100).name
		dispense(tanker, still, 40, hours_copy=110, date=day(-10), posting_time="08:00:00")
		dispense(tanker, still, 10, hours_copy=110, date=day(-5), posting_time="08:00:00")

		# no reading at all
		faulty = make_resource("TEST-FT-RA-EQ9C", "Equipment", reading=100, has_faulty_meter=1).name
		dispense(tanker, faulty, 30, date=day(-10), posting_time="08:00:00")
		dispense(tanker, faulty, 25, date=day(-5), posting_time="08:00:00")

		_cols, rows = consumption_execute({})
		status = {(r["resource"], r["litres_dispensed"]): r["alert_status"] for r in rows}

		self.assertEqual(status[(first, 0)], "First Fill")
		self.assertEqual(status[(still, 40)], "No Movement")
		self.assertEqual(status[(faulty, 30)], "Meter Faulty")
		self.assertNotIn("", {r["alert_status"] for r in rows}, "no row may be left unexplained")

	def test_backwards_reading_is_flagged_not_scored(self):
		"""Legacy data can hold readings that go down; that is bad data, not 0 km/L."""
		tanker = make_tanker("TEST-FT-RA-10").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		truck = make_resource("TEST-FT-RA-TRK10", "Truck", reading=1000, average_consumption=0.2).name

		dispense(tanker, truck, 100, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		second = dispense(tanker, truck, 50, odometer_km=2000, date=day(-5), posting_time="08:00:00")
		# force the sort of reversed reading only bad historical data produces
		frappe.db.set_value(
			"Fuel Entry", entry_for(second).name, "diff_odometer", -300, update_modified=False
		)

		_cols, rows = consumption_execute({"resource": truck})
		flagged = [r for r in rows if r["kilometers"] == -300]

		self.assertEqual(len(flagged), 1)
		self.assertEqual(flagged[0]["alert_status"], "Check Reading")
		self.assertEqual(flagged[0]["consumption"], 0)

	def test_small_truck_consumption_is_not_rounded_away(self):
		tanker = make_tanker("TEST-FT-RA-11").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		truck = make_resource("TEST-FT-RA-TRK11", "Truck", reading=1000).name

		dispense(tanker, truck, 50, odometer_km=1500, date=day(-10), posting_time="08:00:00")
		dispense(tanker, truck, 10, odometer_km=2000, date=day(-5), posting_time="08:00:00")

		_cols, rows = consumption_execute({"resource": truck})
		scored = [r for r in rows if r["litres_dispensed"] == 50][0]

		# 50 L over 500 km = 0.1 L/km — two decimals would still hold this, but
		# the report keeps four so thriftier vehicles do not read as zero
		self.assertEqual(scored["consumption"], 0.1)
		self.assertEqual(scored["alert_status"], "No Baseline")


class TestNewReports(FrappeTestCase):
	def test_transfer_register_lists_both_ends(self):
		site_a = ensure_site("TEST-FT-RA-SITE-A")
		site_b = ensure_site("TEST-FT-RA-SITE-B")
		source = make_tanker("TEST-FT-RA-12A", site=site_a).name
		dest = make_tanker("TEST-FT-RA-12B", site=site_b).name
		supply(source, 900, date=day(-6), posting_time="08:00:00")
		transfer(source, dest, 350, date=day(-3), posting_time="08:00:00")

		_cols, rows = transfer_execute({"fuel_tanker": [source]})

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["from_tanker"], source)
		self.assertEqual(rows[0]["to_tanker"], dest)
		self.assertEqual(rows[0]["litres_transferred"], 350)
		self.assertEqual(rows[0]["route"], "Cross-site")
		self.assertEqual(rows[0]["status"], "Submitted")

	def test_transfer_register_finds_a_tanker_on_either_side(self):
		site_a = ensure_site("TEST-FT-RA-SITE-A")
		site_b = ensure_site("TEST-FT-RA-SITE-B")
		source = make_tanker("TEST-FT-RA-13A", site=site_a).name
		dest = make_tanker("TEST-FT-RA-13B", site=site_b).name
		supply(source, 500, date=day(-6), posting_time="08:00:00")
		transfer(source, dest, 100, date=day(-3), posting_time="08:00:00")

		# filtering on the receiving tanker must still find the movement
		_cols, rows = transfer_execute({"fuel_tanker": [dest]})
		self.assertEqual(len(rows), 1)

	def test_request_status_tracks_outstanding_litres(self):
		tanker = make_tanker("TEST-FT-RA-14").name
		request = request_supply(tanker, 1000, date=day(-5))
		supply(tanker, 400, request=request.name, date=day(-3), posting_time="08:00:00")

		_cols, rows = request_execute({"fuel_tanker": [tanker], "only_outstanding": 1})

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["requested_litres"], 1000)
		self.assertEqual(rows[0]["supplied_litres"], 400)
		self.assertEqual(rows[0]["pending_litres"], 600)
		self.assertEqual(rows[0]["fulfilled_pct"], 40)
		self.assertEqual(rows[0]["deliveries"], 1)
		self.assertEqual(rows[0]["status"], "Partially Supplied")

	def test_request_status_hides_fulfilled_when_outstanding_only(self):
		tanker = make_tanker("TEST-FT-RA-15").name
		request = request_supply(tanker, 500, date=day(-5))
		supply(tanker, 500, request=request.name, date=day(-3), posting_time="08:00:00")

		_cols, outstanding = request_execute({"fuel_tanker": [tanker], "only_outstanding": 1})
		_cols, everything = request_execute({"fuel_tanker": [tanker], "only_outstanding": 0})

		self.assertEqual(len(outstanding), 0)
		self.assertEqual(len(everything), 1)
		self.assertEqual(everything[0]["status"], "Fully Supplied")
		self.assertEqual(everything[0]["fulfilled_pct"], 100)

	def test_resource_summary_derives_the_observed_consumption(self):
		tanker = make_tanker("TEST-FT-RA-16").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		eq = make_resource("TEST-FT-RA-EQ16", "Equipment", reading=100).name

		dispense(tanker, eq, 100, hours_copy=110, date=day(-10), posting_time="08:00:00")
		dispense(tanker, eq, 50, hours_copy=120, date=day(-5), posting_time="08:00:00")

		_cols, rows = summary_execute({"resource": [eq]})
		row = [r for r in rows if r["resource"] == eq][0]

		self.assertEqual(row["fills"], 2)
		self.assertEqual(row["litres"], 150)
		self.assertEqual(row["distance"], 20)          # 10 h + 10 h
		self.assertEqual(row["observed_consumption"], 7.5)  # 150 L / 20 h
		self.assertEqual(row["status"], "Set Baseline")

	def test_resource_summary_scores_against_a_baseline(self):
		tanker = make_tanker("TEST-FT-RA-17").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		eq = make_resource("TEST-FT-RA-EQ17", "Equipment", reading=100, average_consumption=5).name

		dispense(tanker, eq, 100, hours_copy=110, date=day(-10), posting_time="08:00:00")
		dispense(tanker, eq, 50, hours_copy=120, date=day(-5), posting_time="08:00:00")

		_cols, rows = summary_execute({"resource": [eq]})
		row = [r for r in rows if r["resource"] == eq][0]

		self.assertEqual(row["observed_consumption"], 7.5)
		self.assertEqual(row["variance"], 2.5)
		self.assertEqual(row["variance_pct"], 50)
		self.assertEqual(row["status"], "High Alert")

	def test_resource_summary_counts_unmetered_fills_separately(self):
		tanker = make_tanker("TEST-FT-RA-18").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		eq = make_resource("TEST-FT-RA-EQ18", "Equipment", reading=100, has_faulty_meter=1).name

		dispense(tanker, eq, 80, date=day(-10), posting_time="08:00:00")
		dispense(tanker, eq, 60, date=day(-5), posting_time="08:00:00")

		_cols, rows = summary_execute({"resource": [eq]})
		row = [r for r in rows if r["resource"] == eq][0]

		self.assertEqual(row["litres"], 140, "the fuel was still drawn")
		self.assertEqual(row["faulty_fills"], 2)
		self.assertEqual(row["distance"], 0)
		self.assertEqual(row["status"], "Not Measurable")

	def test_resource_summary_can_shortlist_resources_without_a_baseline(self):
		tanker = make_tanker("TEST-FT-RA-19").name
		supply(tanker, 5000, date=day(-20), posting_time="08:00:00")
		with_baseline = make_resource("TEST-FT-RA-EQ19A", "Equipment", reading=100, average_consumption=5).name
		without = make_resource("TEST-FT-RA-EQ19B", "Equipment", reading=100).name

		for resource in (with_baseline, without):
			dispense(tanker, resource, 100, hours_copy=110, date=day(-10), posting_time="08:00:00")
			dispense(tanker, resource, 50, hours_copy=120, date=day(-5), posting_time="08:00:00")

		_cols, rows = summary_execute({"only_without_baseline": 1})
		listed = {r["resource"] for r in rows}

		self.assertIn(without, listed)
		self.assertNotIn(with_baseline, listed)
