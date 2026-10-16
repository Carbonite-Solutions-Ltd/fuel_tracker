# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""Executive Fuel Summary, and the one-line explanation behind every status."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from fuel_tracker.fuel_tracker.consumption import status_note as consumption_note
from fuel_tracker.fuel_tracker.report.average_fuel_consumption_ledger.average_fuel_consumption_ledger import (
	execute as consumption_execute,
)
from fuel_tracker.fuel_tracker.report.executive_fuel_summary.executive_fuel_summary import (
	execute as executive_execute,
)
from fuel_tracker.fuel_tracker.report.fuel_balance.fuel_balance import execute as balance_execute
from fuel_tracker.fuel_tracker.report.fuel_balance.fuel_balance import status_note as balance_note
from fuel_tracker.fuel_tracker.report.resource_fuel_summary.resource_fuel_summary import (
	execute as summary_execute,
)
from fuel_tracker.fuel_tracker.report.resource_fuel_summary.resource_fuel_summary import (
	status_note as summary_note,
)
from fuel_tracker.tests.utils import (
	dispense,
	ensure_site,
	issue_miscellaneous,
	make_resource,
	make_tanker,
	request_supply,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]


def day(offset):
	return add_days(today(), offset)


class TestExecutiveFuelSummary(FrappeTestCase):
	"""Two sites over an 11-day period (day -10 to today).

	Site A
	  TA1  1000 L before the period, +500 supplied, 100 + 10 L to the truck,
	       30 L Miscellaneous, 200 L transferred to TB1  -> closes at 1160
	  TA2  minimum level 500; 300 L supplied, 5 L to the same truck -> 295 (Low)
	Site B
	  TB1  receives the 200 L transfer, 50 L to equipment -> 150; a 400 L
	       request is still outstanding
	The truck's second fill burns 100 L over 200 km = 0.5 L/km against a
	0.2 baseline: one High Alert, on TA1.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.site_a = ensure_site("TEST-FT-EX-SITE-A")
		cls.site_b = ensure_site("TEST-FT-EX-SITE-B")
		cls.ta1 = make_tanker("TEST-FT-EX-TA1", site=cls.site_a).name
		cls.ta2 = make_tanker("TEST-FT-EX-TA2", site=cls.site_a, minimum_level=500).name
		cls.tb1 = make_tanker("TEST-FT-EX-TB1", site=cls.site_b).name
		cls.truck = make_resource("TEST-FT-EX-TRK", "Truck", reading=1000, average_consumption=0.2).name
		cls.eq = make_resource("TEST-FT-EX-EQ", "Equipment", reading=100).name

		supply(cls.ta1, 1000, date=day(-20), posting_time="08:00:00")
		supply(cls.ta1, 500, date=day(-9), posting_time="08:00:00")
		supply(cls.ta2, 300, date=day(-9), posting_time="09:00:00")
		dispense(cls.ta1, cls.truck, 100, odometer_km=1100, date=day(-8), posting_time="08:00:00")
		dispense(cls.ta1, cls.truck, 10, odometer_km=1300, date=day(-6), posting_time="08:00:00")
		dispense(cls.ta2, cls.truck, 5, odometer_km=1400, date=day(-4), posting_time="08:00:00")
		issue_miscellaneous(cls.ta1, 30, date=day(-5), posting_time="08:00:00")
		transfer(cls.ta1, cls.tb1, 200, date=day(-3), posting_time="08:00:00")
		dispense(cls.tb1, cls.eq, 50, hours_copy=110, date=day(-2), posting_time="08:00:00")
		request_supply(cls.tb1, 400, date=day(-2))

		cls.filters = {
			"from_date": day(-10),
			"to_date": today(),
			"fuel_tanker": [cls.ta1, cls.ta2, cls.tb1],
		}
		cls.columns, cls.rows, _msg, cls.chart, cls.summary = executive_execute(dict(cls.filters))
		cls.by = {r["entity"]: r for r in cls.rows}

	def test_sites_open_onto_their_tankers(self):
		layout = [(r["entity"], r["indent"], r.get("parent_entity")) for r in self.rows]
		self.assertEqual(layout, [
			(self.site_a, 0, None),
			(self.ta1, 1, self.site_a),
			(self.ta2, 1, self.site_a),
			(self.site_b, 0, None),
			(self.tb1, 1, self.site_b),
		])

	def test_tanker_rows_are_the_fuel_balance_report(self):
		_cols, balances = balance_execute(
			{"from_date": day(-10), "to_date": today(), "fuel_tanker": [self.ta1, self.ta2, self.tb1]}
		)
		for balance in balances:
			row = self.by[balance["fuel_tanker"]]
			for field in ("opening_balance", "litres_supplied", "transferred_in", "litres_dispensed",
					"litres_miscellaneous", "transferred_out", "litres_adjusted", "current_balance", "status"):
				self.assertEqual(row[field], balance[field], f"{balance['fuel_tanker']} {field}")

		ta1 = self.by[self.ta1]
		self.assertEqual(ta1["opening_balance"], 1000)
		self.assertEqual(ta1["litres_supplied"], 500)
		self.assertEqual(ta1["litres_dispensed"], 110)
		self.assertEqual(ta1["litres_miscellaneous"], 30)
		self.assertEqual(ta1["transferred_out"], 200)
		self.assertEqual(ta1["current_balance"], 1160)

	def test_site_rows_add_up_their_tankers(self):
		site = self.by[self.site_a]
		self.assertEqual(site["opening_balance"], 1000)
		self.assertEqual(site["litres_supplied"], 800)
		self.assertEqual(site["litres_dispensed"], 115)
		self.assertEqual(site["current_balance"], 1160 + 295)
		self.assertEqual(site["fills"], 3)
		# the same truck was fuelled from both tankers: one resource, not two
		self.assertEqual(self.by[self.ta1]["resources_fuelled"], 1)
		self.assertEqual(self.by[self.ta2]["resources_fuelled"], 1)
		self.assertEqual(site["resources_fuelled"], 1)

	def test_stock_cover_uses_the_periods_rate_of_use(self):
		ta1 = self.by[self.ta1]
		# 110 L dispensed + 30 L Miscellaneous over 11 days; transfers are not use
		self.assertEqual(ta1["avg_daily_use"], flt(140 / 11, 2))
		self.assertEqual(ta1["days_of_stock"], flt(1160 / (140 / 11), 2))

		quiet = make_tanker("TEST-FT-EX-QUIET", site=self.site_b).name
		supply(quiet, 100, date=day(-1), posting_time="08:00:00")
		_c, rows, _m, _ch, _s = executive_execute({**self.filters, "fuel_tanker": [quiet]})
		row = [r for r in rows if r["entity"] == quiet][0]
		self.assertIsNone(row["days_of_stock"], "nothing used: blank, not '0 days left'")

	def test_alerts_requests_and_status_roll_up(self):
		self.assertEqual(self.by[self.ta1]["consumption_alerts"], 1)
		self.assertEqual(self.by[self.ta2]["consumption_alerts"], 0)
		self.assertEqual(self.by[self.site_a]["consumption_alerts"], 1)
		self.assertEqual(self.by[self.tb1]["outstanding_requests"], 400)
		self.assertEqual(self.by[self.site_b]["outstanding_requests"], 400)

		self.assertEqual(self.by[self.ta2]["status"], "Low")
		self.assertEqual(self.by[self.site_a]["status"], "Low", "a site takes its worst tanker's status")
		self.assertIn("1 of 2 tankers", self.by[self.site_a]["status_note"])
		self.assertEqual(self.by[self.site_b]["status"], "OK")

	def test_headline_cards_and_chart(self):
		cards = {c["label"]: c["value"] for c in self.summary}
		self.assertEqual(cards["Closing Balance"], "1,605.00 L")  # 1160 + 295 + 150
		self.assertEqual(cards["Supplied"], "800.00 L")
		self.assertEqual(cards["Miscellaneous"], "30.00 L")
		self.assertEqual(cards["Outstanding Requests"], "400.00 L")
		self.assertEqual(cards["Tankers Needing Attention"], 1)
		self.assertEqual(cards["Consumption Alerts"], 1)

		self.assertEqual(self.chart["data"]["labels"], [self.site_a, self.site_b])
		closing = self.chart["data"]["datasets"][2]["values"]
		self.assertEqual(closing, [1455, 150])

	def test_numbers_show_two_decimals(self):
		for column in self.columns:
			if column["fieldtype"] == "Float":
				self.assertEqual(column.get("precision"), 2, column["fieldname"])

	def test_no_tankers_is_an_empty_report_not_an_error(self):
		_c, rows, _m, chart, summary = executive_execute({"site": ["TEST-FT-EX-NO-SUCH-SITE"]})
		self.assertEqual((rows, chart, summary), ([], None, []))

	def test_every_status_in_these_reports_is_explained(self):
		reports = [
			(balance_execute({"fuel_tanker": [self.ta1, self.ta2, self.tb1]})[1], "status"),
			(consumption_execute({"resource": self.truck})[1], "alert_status"),
			(summary_execute({"resource": [self.truck, self.eq]})[1], "status"),
			(self.rows, "status"),
		]
		for rows, field in reports:
			self.assertTrue(rows)
			for row in rows:
				self.assertTrue(row.get("status_note"), f"{row.get(field)} has no explanation")


class TestStatusExplanations(FrappeTestCase):
	def test_every_status_has_a_one_line_explanation(self):
		for status in ("OK", "Low", "Negative", "Check Ledger"):
			self.assertTrue(balance_note(status), status)
		for status in ("Good", "Above Average", "Warning", "High Alert", "No Baseline", "First Fill",
				"No Movement", "Meter Faulty", "Check Reading", "Not Metered"):
			self.assertTrue(consumption_note(status), status)
		for status in ("Set Baseline", "Check Readings", "Not Measurable", "High Alert", "Not Metered"):
			self.assertTrue(summary_note(status), status)

		for note in (balance_note("Low"), consumption_note("High Alert"), summary_note("Set Baseline")):
			self.assertNotIn("\n", note, "one line")
