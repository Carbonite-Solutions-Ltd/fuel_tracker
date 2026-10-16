# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

"""End-to-end scenarios: every report, proven against hand-computed figures.

Each scenario builds a fortnight of realistic history on its own tankers and
resources (prefix ``TEST-FT-E2E-<n>``), mutates it the way users do — late
keying, cancelling, amending — and then checks every report against figures
worked out by hand in the comments next to them. Reports are always filtered
to the records a scenario created, because the site under test holds real data.

Tests carrying a ``# Regression (fixed):`` note pin behaviour that used to be
wrong — each was written against the broken code first and failed on it.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate, today

from fuel_tracker.api.dashboard import fuelBalance
from fuel_tracker.fuel_tracker.fuel_ledger import get_tanker_balance_on
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
from fuel_tracker.fuel_tracker.report.miscellaneous_fuel_register.miscellaneous_fuel_register import (
	execute as misc_register_execute,
)
from fuel_tracker.fuel_tracker.report.resource_fuel_summary.resource_fuel_summary import (
	execute as summary_execute,
)
from fuel_tracker.tests.utils import (
	adjust,
	balance,
	dispense,
	ensure_site,
	entries_for,
	entry_for,
	issue_miscellaneous,
	make_resource,
	make_tanker,
	messages_text,
	report_total,
	request_supply,
	supply,
	transfer,
)

test_ignore = ["Item", "Company"]


# ---------------------------------------------------------------------------
# helpers local to this module
# ---------------------------------------------------------------------------


def day(offset):
	return add_days(today(), offset)


def open_balance(tanker, amount, date):
	"""Submit the tanker's opening balance, reusing the lazily created row."""
	name = frappe.db.get_value("Fuel Balance", {"fuel_tanker": tanker}, "name")
	if name:
		doc = frappe.get_doc("Fuel Balance", name)
		doc.balance = amount
		doc.date = date
		doc.save()
	else:
		doc = frappe.get_doc({
			"doctype": "Fuel Balance",
			"fuel_tanker": tanker,
			"balance": amount,
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
			"date": date,
		})
		doc.insert()
	doc.submit()
	return doc


def raise_request(tanker, litres, date, required_by=None):
	doc = frappe.get_doc({
		"doctype": "Fuel Supply Request",
		"date": date,
		"required_by": required_by,
		"fuel_tanker": tanker,
		"requested_litres": litres,
		"reason": "Routine Replenishment",
	})
	doc.insert()
	doc.submit()
	return doc


def make_resource_at(chassis, resource_type, stationed_site, **kwargs):
	"""A resource stationed at a site (set before it is ever fuelled)."""
	name = make_resource(chassis, resource_type, **kwargs).name
	frappe.db.set_value("Resource", name, "stationed_site", stationed_site, update_modified=False)
	return name


def cancel_via_entry(doc, utilization_type=None):
	"""Cancel a source document the supported way: through its Fuel Entry."""
	entries = entries_for(doc)
	if utilization_type:
		entries = [e for e in entries if e.utilization_type == utilization_type]
	entries[0].cancel()


def amend(doc, **changes):
	"""Amend a cancelled document the way the desk does."""
	original = frappe.get_doc(doc.doctype, doc.name)
	assert original.docstatus == 2, "only a cancelled document can be amended"
	amended = frappe.copy_doc(original)
	amended.amended_from = original.name
	amended.docstatus = 0  # copy_doc keeps docstatus while frappe.flags.in_test
	amended.update(changes)
	amended.insert()
	amended.submit()
	return amended


def tanker_site(tanker):
	return frappe.db.get_value("Fuel Tanker", tanker, "site")


def bal(opening=0, supplied=0, t_in=0, dispensed=0, misc=0, t_out=0, adjusted=0, opening_entry=0, closing=0):
	"""Expected Fuel Balance report row."""
	return {
		"opening_balance": opening,
		"litres_supplied": supplied,
		"transferred_in": t_in,
		"litres_dispensed": dispensed,
		"litres_miscellaneous": misc,
		"transferred_out": t_out,
		"litres_adjusted": adjusted,
		"opening_entry": opening_entry,
		"current_balance": closing,
	}


def movements(rows):
	"""Fuel Ledger rows reduced to (type, supplied, dispensed, adjusted, previous, current)."""
	return [
		(
			r["utilization_type"],
			flt(r["litres_supplied"], 3),
			flt(r["litres_dispensed"], 3),
			flt(r["litres_adjusted"], 3),
			flt(r["previous_balance"], 3),
			flt(r["current_balance"], 3),
		)
		for r in rows
	]


def ledger_rows(**filters):
	"""Fuel Ledger report as (data rows, the total row the desk shows)."""
	cols, rows = ledger_execute(filters)
	if not rows:
		return [], None
	return rows, report_total(cols, rows)


def consumption_rows(resources, **filters):
	"""Consumption ledger rows for the given resources, keyed by Fuel Used."""
	out = {}
	for resource in resources:
		_cols, rows = consumption_execute({**filters, "resource": resource})
		for row in rows:
			out[row["reference_document"]] = row
	return out


def summary_rows(resources, **filters):
	_cols, rows = summary_execute({**filters, "resource": list(resources)})
	return {r["resource"]: r for r in rows}


def misc_register(**filters):
	cols, rows, _msg, chart = misc_register_execute(filters)
	return cols, rows, chart


def names(rows, key="name"):
	return [r[key] for r in rows]


# ---------------------------------------------------------------------------
# the site week
# ---------------------------------------------------------------------------


def build_site_week(prefix):
	"""Two sites, three tankers, four resources, a fortnight of movements.

	Sites A and B. TA1 (site A, opened at 2,000 L, minimum 500), TA2 (site A),
	TB1 (site B, minimum 2,000). TRK1 (truck, baseline 0.25 L/km), TRK2 (truck,
	no baseline), EQ1 (equipment, baseline 10 L/h, stationed at B but always
	fuelled from site A) and FTRK (truck with a faulty meter).

	    d-14 00:00  TA1 opening balance 2,000                     TA1 2000
	    d-13        REQ1 TA2 1,000 L; REQ2 TB1 3,000 L
	    d-13 09:00  TA2 supplied 1,000 (REQ1, fully)              TA2 1000
	    d-12 08:00  TB1 supplied 1,200 (REQ2)                     TB1 1200
	    d-12 10:00  TA1 -> TRK1 200 L @ 10,400 km (from 10,000)   TA1 1800
	    d-12 11:00  TA1 -> EQ1 150 L @ 110 h (from 100)           TA1 1650
	    d-11 08:00  TB1 supplied 800 (REQ2, 2,000 of 3,000)       TB1 2000
	    d-11 09:00  TB1 -> TRK2 300 L @ 5,600 km (from 5,000)     TB1 1700
	    d-10 08:00  TA1 -> FTRK 100 L (faulty meter)              TA1 1550
	    d-10 10:00  TA2 -> TRK1 120 L @ 11,200 km                 TA2 880
	    d-9  08:00  TA1 miscellaneous 40 L                        TA1 1510
	    d-9  12:00  TA1 -> EQ1 90 L @ 125 h                       TA1 1420
	    d-8  08:00  transfer TA1 -> TB1 600 L (cross-site)        TA1 820, TB1 2300
	    d-8  10:00  TB1 -> TRK2 250 L @ 6,400 km                  TB1 2050
	    d-7  08:00  TB1 miscellaneous 25 L                        TB1 2025
	    d-7  10:00  TA1 -> FTRK 80 L (faulty meter)               TA1 740
	    d-6  08:00  TA2 quantity adjustment -30 (spillage)        TA2 850
	    d-6         REQ3 TA1 500 L, required by d-2 (never supplied)
	    d-6  10:00  transfer TA2 -> TA1 100 L (same site)         TA2 750, TA1 840
	    d-5  10:00  TA1 -> TRK1 100 L @ 11,500 km                 TA1 740
	    d-4  08:00  TB1 dip count 1,990 (system 2,025 -> -35)     TB1 1990
	    d-3  10:00  TA2 -> EQ1 60 L @ 133 h                       TA2 690
	"""
	ns = frappe._dict(prefix=prefix)
	ns.site_a = ensure_site(prefix + "-SITE-A")
	ns.site_b = ensure_site(prefix + "-SITE-B")
	ns.ta1 = make_tanker(prefix + "-TA1", site=ns.site_a, minimum_level=500).name
	ns.ta2 = make_tanker(prefix + "-TA2", site=ns.site_a).name
	ns.tb1 = make_tanker(prefix + "-TB1", site=ns.site_b, minimum_level=2000).name
	ns.tankers = [ns.ta1, ns.ta2, ns.tb1]

	ns.trk1 = make_resource_at(prefix + "-TRK1", "Truck", ns.site_a, reading=10000, average_consumption=0.25)
	ns.trk2 = make_resource_at(prefix + "-TRK2", "Truck", ns.site_b, reading=5000)
	ns.eq1 = make_resource_at(prefix + "-EQ1", "Equipment", ns.site_b, reading=100, average_consumption=10)
	ns.ftrk = make_resource_at(prefix + "-FTRK", "Truck", ns.site_a, reading=20000, has_faulty_meter=1)
	ns.resources = [ns.trk1, ns.trk2, ns.eq1, ns.ftrk]

	open_balance(ns.ta1, 2000, date=day(-14))
	ns.req1 = request_supply(ns.ta2, 1000, date=day(-13))
	ns.req2 = request_supply(ns.tb1, 3000, date=day(-13))
	ns.sup_ta2 = supply(ns.ta2, 1000, date=day(-13), posting_time="09:00:00", request=ns.req1.name)
	ns.sup_tb1_a = supply(ns.tb1, 1200, date=day(-12), posting_time="08:00:00", request=ns.req2.name)
	ns.f1 = dispense(ns.ta1, ns.trk1, 200, odometer_km=10400, date=day(-12), posting_time="10:00:00")
	ns.e1 = dispense(ns.ta1, ns.eq1, 150, hours_copy=110, date=day(-12), posting_time="11:00:00")
	ns.sup_tb1_b = supply(ns.tb1, 800, date=day(-11), posting_time="08:00:00", request=ns.req2.name)
	ns.r1 = dispense(ns.tb1, ns.trk2, 300, odometer_km=5600, date=day(-11), posting_time="09:00:00")
	ns.x1 = dispense(ns.ta1, ns.ftrk, 100, date=day(-10), posting_time="08:00:00")
	ns.f2 = dispense(ns.ta2, ns.trk1, 120, odometer_km=11200, date=day(-10), posting_time="10:00:00")
	ns.misc_a = issue_miscellaneous(
		ns.ta1, 40, description="Cleaning tools after work", date=day(-9), posting_time="08:00:00"
	)
	ns.e2 = dispense(ns.ta1, ns.eq1, 90, hours_copy=125, date=day(-9), posting_time="12:00:00")
	ns.xfer_ab = transfer(ns.ta1, ns.tb1, 600, date=day(-8), posting_time="08:00:00")
	ns.r2 = dispense(ns.tb1, ns.trk2, 250, odometer_km=6400, date=day(-8), posting_time="10:00:00")
	ns.misc_b = issue_miscellaneous(
		ns.tb1, 25, description="Degreasing the batching plant", date=day(-7), posting_time="08:00:00"
	)
	ns.x2 = dispense(ns.ta1, ns.ftrk, 80, date=day(-7), posting_time="10:00:00")
	ns.adj_qty = adjust(
		ns.ta2, mode="Quantity", quantity=-30, reason="Spillage", date=day(-6), posting_time="08:00:00"
	)
	ns.req3 = raise_request(ns.ta1, 500, date=day(-6), required_by=day(-2))
	ns.xfer_aa = transfer(ns.ta2, ns.ta1, 100, date=day(-6), posting_time="10:00:00")
	ns.f3 = dispense(ns.ta1, ns.trk1, 100, odometer_km=11500, date=day(-5), posting_time="10:00:00")
	ns.adj_measured = adjust(ns.tb1, mode="Measured Balance", measured=1990, date=day(-4), posting_time="08:00:00")
	ns.e3 = dispense(ns.ta2, ns.eq1, 60, hours_copy=133, date=day(-3), posting_time="10:00:00")
	return ns


#: Fuel Ledger per tanker: (type, supplied, dispensed, adjusted, previous, current)
SITE_WEEK_LEDGER = {
	"ta1": [
		("Opening Balance", 0, 0, 0, 0, 2000),
		("Dispensed", 0, 200, 0, 2000, 1800),       # TRK1 d-12
		("Dispensed", 0, 150, 0, 1800, 1650),       # EQ1 d-12
		("Dispensed", 0, 100, 0, 1650, 1550),       # FTRK d-10
		("Miscellaneous", 0, 40, 0, 1550, 1510),    # d-9 08:00
		("Dispensed", 0, 90, 0, 1510, 1420),        # EQ1 d-9
		("Transfer Out", 0, 600, 0, 1420, 820),     # to TB1 d-8
		("Dispensed", 0, 80, 0, 820, 740),          # FTRK d-7
		("Transfer In", 100, 0, 0, 740, 840),       # from TA2 d-6
		("Dispensed", 0, 100, 0, 840, 740),         # TRK1 d-5
	],
	"ta2": [
		("Supplied", 1000, 0, 0, 0, 1000),
		("Dispensed", 0, 120, 0, 1000, 880),
		("Adjustment", 0, 0, -30, 880, 850),
		("Transfer Out", 0, 100, 0, 850, 750),
		("Dispensed", 0, 60, 0, 750, 690),
	],
	"tb1": [
		("Supplied", 1200, 0, 0, 0, 1200),
		("Supplied", 800, 0, 0, 1200, 2000),
		("Dispensed", 0, 300, 0, 2000, 1700),
		("Transfer In", 600, 0, 0, 1700, 2300),
		("Dispensed", 0, 250, 0, 2300, 2050),
		("Miscellaneous", 0, 25, 0, 2050, 2025),
		("Adjustment", 0, 0, -35, 2025, 1990),
	],
}

#: Fuel Balance report (no from_date), with the expected status.
SITE_WEEK_BALANCES = {
	# 0 + 100 in - 720 dispensed - 40 misc - 600 out + 2000 opening entry = 740
	"ta1": (bal(t_in=100, dispensed=720, misc=40, t_out=600, opening_entry=2000, closing=740), "OK"),
	# 1000 - 180 - 100 - 30 = 690
	"ta2": (bal(supplied=1000, dispensed=180, t_out=100, adjusted=-30, closing=690), "OK"),
	# 2000 + 600 - 550 - 25 - 35 = 1990, below the 2,000 minimum
	"tb1": (bal(supplied=2000, t_in=600, dispensed=550, misc=25, adjusted=-35, closing=1990), "Low"),
}

#: Consumption ledger, tank to tank: litres put in at the previous metered
#: fill over the distance recorded since it.
SITE_WEEK_SCORES = {
	"f1": dict(alert_status="First Fill", kilometers=400, previous_odometer=10000, current_odometer=10400, consumption=0),
	# 200 L / 800 km = 0.25, exactly the baseline
	"f2": dict(alert_status="Good", litres_dispensed=200, kilometers=800, previous_odometer=10400,
		current_odometer=11200, consumption=0.25, average_consumption=0.25, variance=0, fuel_supposed_to_be_used=200),
	# 120 L / 300 km = 0.4, 60% over the baseline
	"f3": dict(alert_status="High Alert", litres_dispensed=120, kilometers=300, previous_odometer=11200,
		current_odometer=11500, consumption=0.4, variance=0.15, fuel_supposed_to_be_used=75),
	"e1": dict(alert_status="First Fill", diff_hours=10, current_hours=110, kilometers=0, consumption=0),
	# 150 L / 15 h = 10, the baseline
	"e2": dict(alert_status="Good", litres_dispensed=150, diff_hours=15, current_hours=125, kilometers=0,
		previous_odometer=0, current_odometer=0, consumption=10, variance=0, fuel_supposed_to_be_used=150),
	# 90 L / 8 h = 11.25, 12.5% over
	"e3": dict(alert_status="Warning", litres_dispensed=90, diff_hours=8, current_hours=133, consumption=11.25,
		variance=1.25, fuel_supposed_to_be_used=80),
	"r1": dict(alert_status="First Fill", kilometers=600, consumption=0),
	# 300 L / 800 km = 0.375, nothing to compare against
	"r2": dict(alert_status="No Baseline", litres_dispensed=300, kilometers=800, consumption=0.375, variance=0,
		fuel_supposed_to_be_used=0),
	"x1": dict(alert_status="Meter Faulty", kilometers=0, consumption=0),
	"x2": dict(alert_status="Meter Faulty", kilometers=0, consumption=0),
}

#: Resource Fuel Summary columns unaffected by how distance is attributed.
SITE_WEEK_SUMMARY_COUNTS = {
	"trk1": dict(fills=3, litres=420, faulty_fills=0, average_consumption=0.25),
	"trk2": dict(fills=2, litres=550, faulty_fills=0),
	"eq1": dict(fills=3, litres=300, faulty_fills=0, average_consumption=10),
	"ftrk": dict(fills=2, litres=180, faulty_fills=2, distance=0, observed_consumption=0, status="Not Measurable"),
}

#: Resource Fuel Summary measured over scored fills only (first fills and
#: faulty-meter fills carry no measurable interval). (fields, variance_pct)
SITE_WEEK_SUMMARY_MEASURED = {
	# scored: f2 200 L/800 km, f3 120 L/300 km -> 320/1100 = 0.2909, +16.36%
	"trk1": (dict(distance=1100, measured_litres=320, observed_consumption=0.2909, variance=0.0409, status="Warning"), 16.36),
	# scored: e2 150 L/15 h, e3 90 L/8 h -> 240/23 = 10.4348, +4.35%
	"eq1": (dict(distance=23, measured_litres=240, observed_consumption=10.4348, variance=0.4348, status="Above Average"), 4.35),
	# scored: r2 300 L/800 km
	"trk2": (dict(distance=800, measured_litres=300, observed_consumption=0.375, status="Set Baseline"), None),
	"ftrk": (dict(distance=0, measured_litres=0, observed_consumption=0, status="Not Measurable"), None),
}


class ScenarioAssertions:
	"""Checks shared by every scenario."""

	def assert_fields(self, row, label, **expected):
		self.assertIsNotNone(row, "{0}: no row".format(label))
		for field, value in expected.items():
			actual = row.get(field)
			if isinstance(value, (int, float)) and not isinstance(value, bool):
				self.assertAlmostEqual(
					flt(actual), value, places=4,
					msg="{0}: {1} is {2}, expected {3}".format(label, field, actual, value),
				)
			else:
				self.assertEqual(actual, value, "{0}: {1} is {2!r}, expected {3!r}".format(label, field, actual, value))

	def assert_chain(self, data):
		"""Previous balance of each row is the current balance of the one before."""
		running = 0.0
		for row in data:
			if row["utilization_type"] == "Opening Balance":
				running = flt(row["current_balance"], 3)
				continue
			self.assertAlmostEqual(flt(row["previous_balance"]), running, places=3, msg="chain breaks at " + row["name"])
			running = flt(
				running + flt(row["litres_supplied"]) - flt(row["litres_dispensed"]) + flt(row["litres_adjusted"]), 3
			)
			self.assertAlmostEqual(flt(row["current_balance"]), running, places=3, msg="bad delta at " + row["name"])
		return running

	def check_ledger(self, ns, expected):
		"""Every tanker's Fuel Ledger reads exactly as computed, continuously, with a true total."""
		for key, rows in expected.items():
			data, total = ledger_rows(fuel_tanker=[ns[key]])
			self.assertEqual(movements(data), [tuple(flt(v, 3) if not isinstance(v, str) else v for v in r) for r in rows], key)
			self.assertEqual({r["fuel_tanker"] for r in data}, {ns[key]})
			self.assert_chain(data)
			self.assertAlmostEqual(flt(total["litres_supplied"]), sum(r[1] for r in rows), places=3)
			self.assertAlmostEqual(flt(total["litres_dispensed"]), sum(r[2] for r in rows), places=3)
			self.assertAlmostEqual(flt(total["litres_adjusted"]), sum(r[3] for r in rows), places=3)

	def check_balance_report(self, ns, expected, **filters):
		filters = {"to_date": today(), "fuel_tanker": ns.tankers, **filters}
		cols, rows = balance_execute(filters)
		by = {r["fuel_tanker"]: r for r in rows}
		self.assertEqual(len(rows), len(by), "a tanker must never be split across rows")
		self.assertEqual(set(by), {ns[k] for k in expected})
		for key, (values, status) in expected.items():
			row = by[ns[key]]
			self.assert_fields(row, key, **values)
			self.assertEqual(row["difference"], 0, "{0} does not reconcile".format(key))
			self.assertEqual(row["site"], tanker_site(ns[key]))
			if status:
				self.assertEqual(row["status"], status, key)
		return cols, by

	def check_agreement(self, ns, closings):
		"""Report closing == Fuel Balance doctype == ledger tail == dashboard == as-at API."""
		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [ns[k] for k in closings]})
		by = {r["fuel_tanker"]: r for r in rows}
		for key, closing in closings.items():
			tanker = ns[key]
			data, _total = ledger_rows(fuel_tanker=[tanker])
			self.assertAlmostEqual(flt(by[tanker]["current_balance"]), closing, places=3, msg=key + " report")
			self.assertAlmostEqual(balance(tanker), closing, places=3, msg=key + " Fuel Balance doctype")
			self.assertAlmostEqual(flt(data[-1]["current_balance"]), closing, places=3, msg=key + " ledger tail")
			self.assertAlmostEqual(flt(fuelBalance(tanker_site(tanker), tanker)), closing, places=3, msg=key + " dashboard")
			self.assertAlmostEqual(
				flt(get_tanker_balance_on(tanker, today(), "23:59:59")), closing, places=3, msg=key + " as-at"
			)

	def check_scores(self, ns, expected, resources=None, **filters):
		rows = consumption_rows(resources or ns.resources, **filters)
		self.assertEqual(set(rows), {ns[k].name for k in expected}, "scored fills")
		for key, fields in expected.items():
			self.assert_fields(rows[ns[key].name], key, **fields)
		return rows

	def check_summary(self, ns, expected, resources=None, **filters):
		rows = summary_rows(resources or ns.resources, **filters)
		self.assertEqual(set(rows), {ns[k] for k in expected})
		for key, fields in expected.items():
			if isinstance(fields, tuple):
				fields, pct = fields
				if pct is not None:
					self.assertAlmostEqual(flt(rows[ns[key]]["variance_pct"]), pct, delta=0.03, msg=key + " variance %")
			self.assert_fields(rows[ns[key]], key, **fields)
		return rows


# ---------------------------------------------------------------------------
# Scenario 1, 2 and 6 — the site week, read-only, with period windows and filters
# ---------------------------------------------------------------------------


class TestSiteWeek(ScenarioAssertions, FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.ns = build_site_week("TEST-FT-E2E-1")

	# -- scenario 1 ---------------------------------------------------------

	def test_balance_report_matches_doctype_ledger_and_dashboard(self):
		ns = self.ns
		cols, by = self.check_balance_report(ns, SITE_WEEK_BALANCES)
		self.check_agreement(ns, {k: v[0]["current_balance"] for k, v in SITE_WEEK_BALANCES.items()})

		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": ns.tankers})
		self.assertEqual(names(rows, "fuel_tanker"), [ns.ta1, ns.ta2, ns.tb1], "site A first, then site B")

		fieldnames = [c["fieldname"] for c in cols]
		self.assertIn("opening_entry", fieldnames, "TA1 was opened inside the period")
		self.assertNotIn("difference", fieldnames, "shown only when the ledger is damaged")

		# the doctype is the tail of the ledger, dated at its last movement
		self.assertEqual(getdate(frappe.db.get_value("Fuel Balance", ns.ta1, "date")), getdate(day(-5)))
		self.assertEqual(getdate(frappe.db.get_value("Fuel Balance", ns.tb1, "date")), getdate(day(-4)))
		self.assertEqual(frappe.db.get_value("Fuel Balance", ns.ta1, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Fuel Balance", ns.ta2, "docstatus"), 0, "lazily created draft")

	def test_ledger_report_rows_running_balance_and_totals(self):
		ns = self.ns
		self.check_ledger(ns, SITE_WEEK_LEDGER)

		data, total = ledger_rows(fuel_tanker=ns.tankers)
		self.assertEqual(len(data), 10 + 5 + 7)
		tankers = names(data, "fuel_tanker")
		self.assertEqual(tankers, sorted(tankers), "grouped by tanker, never interleaved")
		self.assertAlmostEqual(flt(total["litres_supplied"]), 3700, places=3)    # 1000+1200+800 bought, 600+100 moved in
		self.assertAlmostEqual(flt(total["litres_dispensed"]), 2215, places=3)   # 1360 TA1 + 280 TA2 + 575 TB1
		self.assertAlmostEqual(flt(total["litres_adjusted"]), -65, places=3)
		self.assertAlmostEqual(flt(total["diff_odometer"]), 2900, places=3)      # TRK1 1500 + TRK2 1400, FTRK 0
		self.assertAlmostEqual(flt(total["diff_hours_copy"]), 33, places=3)      # EQ1 10 + 15 + 8

		misc = {r["name"]: r for r in data if r["utilization_type"] == "Miscellaneous"}
		self.assertEqual(
			{r["description"] for r in misc.values()},
			{"Cleaning tools after work", "Degreasing the batching plant"},
		)
		self.assertTrue(all(not r["resource"] for r in misc.values()))
		transfer_rows = [r for r in data if r["utilization_type"].startswith("Transfer")]
		self.assertTrue(all(not r["resource"] and not r["description"] for r in transfer_rows))

	def test_balance_as_at_api_and_dashboard_on_past_dates(self):
		ns = self.ns
		self.assertEqual(get_tanker_balance_on(ns.ta1, day(-15), "23:59:59"), 0)
		self.assertEqual(get_tanker_balance_on(ns.ta1, day(-14)), 2000, "opening entry posts at 00:00:00")
		self.assertEqual(get_tanker_balance_on(ns.ta1, day(-8), "07:59:59"), 1420)
		self.assertEqual(get_tanker_balance_on(ns.ta1, day(-8), "08:00:00"), 820)
		self.assertEqual(get_tanker_balance_on(ns.tb1, day(-8), "08:00:00"), 2300)
		self.assertEqual(get_tanker_balance_on(ns.ta2, day(-13), "08:59:59"), 0)
		self.assertEqual(get_tanker_balance_on(ns.ta2, day(-13), "09:00:00"), 1000)

		self.assertEqual(fuelBalance(ns.site_a, ns.ta1, date=day(-9)), 1420)
		self.assertEqual(fuelBalance(ns.site_a, ns.ta2, date=day(-6)), 750)
		self.assertEqual(fuelBalance(ns.site_b, ns.tb1, date=day(-4)), 1990)
		self.assertEqual(fuelBalance(ns.site_b, ns.tb1, date=day(-13)), 0)

	def test_transfer_register(self):
		ns = self.ns
		_cols, rows = transfer_execute({"fuel_tanker": ns.tankers})
		self.assertEqual(names(rows), [ns.xfer_aa.name, ns.xfer_ab.name], "newest first")

		same, cross = rows
		self.assert_fields(cross, "cross", from_site=ns.site_a, from_tanker=ns.ta1, to_site=ns.site_b,
			to_tanker=ns.tb1, litres_transferred=600, route="Cross-site", status="Submitted")
		self.assertEqual(getdate(cross["date"]), getdate(day(-8)))
		self.assert_fields(same, "same", from_site=ns.site_a, from_tanker=ns.ta2, to_site=ns.site_a,
			to_tanker=ns.ta1, litres_transferred=100, route="Same site", status="Submitted")

		# each transfer is two ledger legs on the same posting moment
		out_leg, in_leg = entries_for(ns.xfer_ab)
		self.assertEqual((out_leg.utilization_type, out_leg.fuel_tanker), ("Transfer Out", ns.ta1))
		self.assertEqual((in_leg.utilization_type, in_leg.fuel_tanker), ("Transfer In", ns.tb1))
		self.assertEqual(out_leg.posting_datetime, in_leg.posting_datetime)
		self.assertEqual(out_leg.site, ns.site_a)
		self.assertEqual(in_leg.site, ns.site_b)

	def test_supply_request_status(self):
		ns = self.ns
		_cols, rows = request_execute({"fuel_tanker": ns.tankers})
		self.assertEqual(names(rows), [ns.req3.name, ns.req2.name, ns.req1.name], "newest first")
		by = {r["name"]: r for r in rows}

		self.assert_fields(by[ns.req1.name], "REQ1", requested_litres=1000, supplied_litres=1000, pending_litres=0,
			fulfilled_pct=100, deliveries=1, status="Fully Supplied", overdue="", site=ns.site_a, age=13)
		self.assert_fields(by[ns.req2.name], "REQ2", requested_litres=3000, supplied_litres=2000, pending_litres=1000,
			fulfilled_pct=66.67, deliveries=2, status="Partially Supplied", overdue="", site=ns.site_b)
		self.assert_fields(by[ns.req3.name], "REQ3", requested_litres=500, supplied_litres=0, pending_litres=500,
			fulfilled_pct=0, deliveries=0, status="Pending", overdue="Yes", age=6)

		# the request records what the tanker held on its own date, from the ledger
		self.assertEqual(frappe.db.get_value("Fuel Supply Request", ns.req3.name, "balance_at_request"), 740)
		self.assertEqual(frappe.db.get_value("Fuel Supply Request", ns.req1.name, "balance_at_request"), 0)

	def test_miscellaneous_register(self):
		ns = self.ns
		cols, rows, chart = misc_register(fuel_tanker=ns.tankers)
		self.assertEqual(names(rows), [ns.misc_b.name, ns.misc_a.name], "newest first, only site-use issues")
		self.assert_fields(rows[1], "misc_a", site=ns.site_a, fuel_tanker=ns.ta1, litres=40,
			description="Cleaning tools after work", status="Submitted", owner=frappe.session.user)
		self.assert_fields(rows[0], "misc_b", site=ns.site_b, fuel_tanker=ns.tb1, litres=25,
			description="Degreasing the batching plant", status="Submitted")
		self.assertNotIn("cancelled_litres", [c["fieldname"] for c in cols])
		self.assertEqual(chart["data"]["labels"], [ns.site_a, ns.site_b], "largest site first")
		self.assertEqual(chart["data"]["datasets"][0]["values"], [40, 25])

	def test_consumption_ledger_scores_each_fill_tank_to_tank(self):
		ns = self.ns
		rows = self.check_scores(ns, SITE_WEEK_SCORES)
		for key in ("f1", "f2", "f3", "e1", "e2", "e3", "r1", "r2", "x1", "x2"):
			row = rows[ns[key].name]
			self.assertEqual(row["fuel_tanker"], ns[key].fuel_tanker)
			self.assertEqual(row["site"], tanker_site(ns[key].fuel_tanker))
			self.assertEqual(row["utilization_type"], "Dispensed")

		# the faulty-meter truck is never scored: no reading, so no distance
		faulty = [r for r in rows.values() if r["resource"] == ns.ftrk]
		self.assertEqual({r["alert_status"] for r in faulty}, {"Meter Faulty"})
		self.assertEqual(entry_for(ns.x1).meter_faulty, 1)
		self.assertEqual(frappe.db.get_value("Resource", ns.ftrk, "current_odometer"), 20000, "never written back")

	def test_resource_summary_counts_fills_and_litres(self):
		ns = self.ns
		rows = self.check_summary(ns, SITE_WEEK_SUMMARY_COUNTS)
		# the site shown is where the resource is stationed
		self.assertEqual(rows[ns.eq1]["site"], ns.site_b)
		self.assertEqual(rows[ns.trk1]["site"], ns.site_a)
		self.assertEqual(rows[ns.trk2]["status"], "Set Baseline")

	def test_resource_summary_measures_only_scored_fills(self):
		# Regression (fixed): summary divides every litre drawn by every diff (first fills included) instead of the ledger's scored fills
		self.check_summary(self.ns, SITE_WEEK_SUMMARY_MEASURED)

	def test_miscellaneous_never_appears_in_consumption_reports(self):
		ns = self.ns
		misc_names = {ns.misc_a.name, ns.misc_b.name}
		for tanker in ns.tankers:
			_cols, rows = consumption_execute({"fuel_tanker": tanker})
			self.assertFalse(misc_names & set(names(rows, "reference_document")))
			self.assertTrue(all(r["resource"] for r in rows))

		_cols, rows = summary_execute({"resource": ns.resources})
		self.assertTrue(all(r["resource"] for r in rows))
		self.assertEqual(sum(flt(r["litres"]) for r in rows), 420 + 550 + 300 + 180, "65 L of site use excluded")

	def test_equipment_hours_and_truck_km_are_kept_apart(self):
		ns = self.ns
		rows = consumption_rows([ns.eq1, ns.trk1])
		eq_row, trk_row = rows[ns.e2.name], rows[ns.f2.name]
		self.assert_fields(eq_row, "equipment", resource_type="Equipment", diff_hours=15, current_hours=125,
			kilometers=0, previous_odometer=0, current_odometer=0)
		self.assert_fields(trk_row, "truck", resource_type="Truck", kilometers=800, diff_hours=0, current_hours=0)

		data, _total = ledger_rows(resource=[ns.eq1, ns.trk1], fuel_tanker=ns.tankers)
		by = {r["name"]: r for r in data}
		self.assert_fields(by[entry_for(ns.e2).name], "ledger equipment", resource_type="Equipment",
			previous_hours_copy=110, hours_copy=125, diff_hours_copy=15, diff_odometer=0)
		self.assert_fields(by[entry_for(ns.f2).name], "ledger truck", resource_type="Truck",
			previous_odometer_km=10400, odometer_km=11200, diff_odometer=800, diff_hours_copy=0)

		self.assertEqual(frappe.db.get_value("Resource", ns.trk1, "current_odometer"), 11500)
		self.assertEqual(frappe.db.get_value("Resource", ns.trk2, "current_odometer"), 6400)
		self.assertEqual(frappe.db.get_value("Resource", ns.eq1, "current_hours"), 133)

	# -- scenario 2: consecutive period windows ------------------------------

	def test_balance_report_windows_chain(self):
		ns = self.ns
		_cols, w1 = self.check_balance_report(ns, {
			"ta1": (bal(dispensed=540, misc=40, t_out=600, opening_entry=2000, closing=820), "OK"),
			"ta2": (bal(supplied=1000, dispensed=120, closing=880), "OK"),
			"tb1": (bal(supplied=2000, t_in=600, dispensed=550, closing=2050), "OK"),
		}, from_date=day(-14), to_date=day(-8))
		cols, w2 = self.check_balance_report(ns, {
			"ta1": (bal(opening=820, t_in=100, dispensed=180, closing=740), "OK"),
			"ta2": (bal(opening=880, dispensed=60, t_out=100, adjusted=-30, closing=690), "OK"),
			"tb1": (bal(opening=2050, misc=25, adjusted=-35, closing=1990), "Low"),
		}, from_date=day(-7), to_date=today())
		for tanker in ns.tankers:
			self.assertEqual(w1[tanker]["current_balance"], w2[tanker]["opening_balance"], tanker)
		self.assertNotIn("opening_entry", [c["fieldname"] for c in cols], "no tanker opened in window 2")

		# an interior window that starts after the opening entry
		self.check_balance_report(ns, {
			"ta1": (bal(opening=1650, t_in=100, dispensed=270, misc=40, t_out=600, closing=840), None),
			"ta2": (bal(opening=1000, dispensed=120, t_out=100, adjusted=-30, closing=750), None),
			"tb1": (bal(opening=1700, t_in=600, dispensed=250, misc=25, closing=2025), None),
		}, from_date=day(-10), to_date=day(-6))

	def test_ledger_report_windows_chain(self):
		ns = self.ns
		w1, t1 = ledger_rows(fuel_tanker=[ns.ta1], from_date=day(-14), to_date=day(-8))
		w2, t2 = ledger_rows(fuel_tanker=[ns.ta1], from_date=day(-7), to_date=today())
		self.assertEqual(movements(w1), [tuple(r) for r in SITE_WEEK_LEDGER["ta1"][:7]])
		self.assertEqual(movements(w2), [tuple(r) for r in SITE_WEEK_LEDGER["ta1"][7:]])
		self.assertEqual(w1[-1]["current_balance"], w2[0]["previous_balance"])
		self.assertAlmostEqual(flt(t1["litres_dispensed"]), 200 + 150 + 100 + 40 + 90 + 600, places=3)
		self.assertAlmostEqual(flt(t2["litres_supplied"]), 100, places=3)

		_a, all1 = ledger_rows(fuel_tanker=ns.tankers, from_date=day(-14), to_date=day(-8))
		_b, all2 = ledger_rows(fuel_tanker=ns.tankers, from_date=day(-7))
		self.assertAlmostEqual(flt(all1["litres_supplied"]), 3600, places=3)
		self.assertAlmostEqual(flt(all2["litres_supplied"]), 100, places=3)
		self.assertAlmostEqual(flt(all1["litres_dispensed"]), 1180 + 120 + 550, places=3)
		self.assertAlmostEqual(flt(all2["litres_dispensed"]), 180 + 160 + 25, places=3)
		self.assertAlmostEqual(flt(all1["litres_adjusted"]) + flt(all2["litres_adjusted"]), -65, places=3)

	def test_miscellaneous_register_windows(self):
		ns = self.ns
		_cols, rows, chart = misc_register(fuel_tanker=ns.tankers, from_date=day(-8))
		self.assertEqual(names(rows), [ns.misc_b.name])
		self.assertEqual(chart["data"]["labels"], [ns.site_b])
		_cols, rows, _chart = misc_register(fuel_tanker=ns.tankers, from_date=day(-9), to_date=day(-9))
		self.assertEqual(names(rows), [ns.misc_a.name])
		_cols, rows, chart = misc_register(fuel_tanker=ns.tankers, to_date=day(-10))
		self.assertEqual(rows, [])
		self.assertIsNone(chart)

	def test_consumption_window_scores_against_the_fill_before_it(self):
		ns = self.ns
		# f3 is the only TRK1 fill in the window; it is still scored against f2's 120 L
		rows = consumption_rows([ns.trk1], from_date=day(-6))
		self.assertEqual(set(rows), {ns.f3.name})
		self.assert_fields(rows[ns.f3.name], "f3", alert_status="High Alert", litres_dispensed=120, consumption=0.4)

		rows = consumption_rows([ns.trk1], from_date=day(-12), to_date=day(-12))
		self.assertEqual(set(rows), {ns.f1.name})
		self.assertEqual(rows[ns.f1.name]["alert_status"], "First Fill")

		rows = consumption_rows([ns.eq1], from_date=day(-9), to_date=day(-4))
		self.assertEqual(set(rows), {ns.e2.name})

	def test_resource_summary_window_uses_the_window_scored_fills(self):
		# Regression (fixed): summary divides window litres by window diffs instead of the ledger's attributed litres
		ns = self.ns
		rows = summary_rows([ns.trk1, ns.eq1], from_date=day(-6))
		self.assertEqual(set(rows), {ns.trk1, ns.eq1})
		# f3: 120 L (put in at f2) over 300 km = 0.4, +60%
		self.assert_fields(rows[ns.trk1], "trk1", fills=1, litres=100, distance=300, measured_litres=120,
			observed_consumption=0.4, status="High Alert")
		# e3: 90 L over 8 h = 11.25, +12.5%
		self.assert_fields(rows[ns.eq1], "eq1", fills=1, litres=60, distance=8, measured_litres=90,
			observed_consumption=11.25, variance=1.25, status="Warning")

	# -- scenario 6: every filter each report declares ------------------------

	def test_filters_fuel_balance(self):
		ns = self.ns

		def tankers(**filters):
			return names(balance_execute({"to_date": today(), **filters})[1], "fuel_tanker")

		self.assertEqual(tankers(site=[ns.site_a]), [ns.ta1, ns.ta2])
		self.assertEqual(tankers(site=[ns.site_b]), [ns.tb1])
		self.assertEqual(tankers(site=[ns.site_a, ns.site_b]), ns.tankers)
		self.assertEqual(tankers(site=[ns.site_a], fuel_tanker=[ns.tb1]), [])
		self.assertEqual(tankers(fuel_tanker=[ns.ta2]), [ns.ta2])
		self.assertEqual(tankers(fuel_tanker=ns.ta2), [ns.ta2], "a scalar works like a one-element list")

		# as at d-14: only the opening entry exists; tankers with a balance row still show, at 0
		self.check_balance_report(ns, {
			"ta1": (bal(opening_entry=2000, closing=2000), "OK"),
			"ta2": (bal(closing=0), "OK"),
			"tb1": (bal(closing=0), "Low"),
		}, to_date=day(-14))
		# the legacy `date` filter is honoured as the as-at date (py-only, not in the .js)
		_cols, rows = balance_execute({"date": day(-8), "fuel_tanker": ns.tankers})
		self.assertEqual({r["fuel_tanker"]: r["current_balance"] for r in rows}, {ns.ta1: 820, ns.ta2: 880, ns.tb1: 2050})
		# from_date only: everything before it is the opening
		self.check_balance_report(ns, {
			"ta1": (bal(opening=740, closing=740), "OK"),
			"ta2": (bal(opening=750, dispensed=60, closing=690), "OK"),
			"tb1": (bal(opening=1990, closing=1990), "Low"),
		}, from_date=day(-3))

	def test_fuel_balance_rejects_from_date_after_to_date(self):
		# Regression (fixed): an inverted period silently returns a nonsense row instead of raising
		with self.assertRaises(frappe.ValidationError):
			balance_execute({"from_date": day(-1), "to_date": day(-5), "fuel_tanker": self.ns.tankers})

	def test_filters_fuel_ledger(self):
		ns = self.ns
		data, total = ledger_rows(site=[ns.site_b])
		self.assertEqual(len(data), 7)
		self.assertEqual({r["fuel_tanker"] for r in data}, {ns.tb1})
		data, _total = ledger_rows(site=[ns.site_a])
		self.assertEqual(len(data), 10 + 5)

		data, _total = ledger_rows(resource=[ns.trk1])
		self.assertEqual(names(data), [entry_for(ns.f1).name, entry_for(ns.f3).name, entry_for(ns.f2).name],
			"TA1's fills, then TA2's")
		data, total = ledger_rows(resource=[ns.eq1, ns.trk2])
		self.assertEqual(len(data), 5)
		self.assertAlmostEqual(flt(total["litres_dispensed"]), 300 + 550, places=3)
		self.assertAlmostEqual(flt(total["diff_hours_copy"]), 33, places=3)
		self.assertAlmostEqual(flt(total["diff_odometer"]), 1400, places=3)

		def by_type(utilization_type, **filters):
			return ledger_rows(fuel_tanker=ns.tankers, utilization_type=utilization_type, **filters)

		data, _t = by_type("Opening Balance")
		self.assertEqual([(r["fuel_tanker"], r["current_balance"]) for r in data], [(ns.ta1, 2000)])
		data, total = by_type("Supplied")
		self.assertEqual(len(data), 3)
		self.assertAlmostEqual(flt(total["litres_supplied"]), 3000, places=3)
		data, _t = by_type("Transfer In")
		self.assertEqual([(r["fuel_tanker"], r["litres_supplied"]) for r in data], [(ns.ta1, 100), (ns.tb1, 600)])
		data, _t = by_type("Transfer Out")
		self.assertEqual([(r["fuel_tanker"], r["litres_dispensed"]) for r in data], [(ns.ta1, 600), (ns.ta2, 100)])
		data, total = by_type("Adjustment")
		self.assertEqual(len(data), 2)
		self.assertAlmostEqual(flt(total["litres_adjusted"]), -65, places=3)
		data, total = by_type("Miscellaneous")
		self.assertEqual(len(data), 2)
		self.assertAlmostEqual(flt(total["litres_dispensed"]), 65, places=3)
		data, _t = ledger_rows(fuel_tanker=[ns.ta2], utilization_type="Dispensed")
		self.assertEqual(names(data), [entry_for(ns.f2).name, entry_for(ns.e3).name])
		data, total = ledger_rows(fuel_tanker=[ns.ta1], from_date=day(-9), to_date=day(-9))
		self.assertEqual([r["utilization_type"] for r in data], ["Miscellaneous", "Dispensed"])

	def test_fuel_ledger_accepts_scalar_filters(self):
		# Regression (fixed): fuel_tanker/site/resource are interpolated as `IN %(x)s`, so a plain string is a SQL error
		ns = self.ns
		self.assertEqual(len(ledger_rows(fuel_tanker=ns.ta2)[0]), 5)
		self.assertEqual(len(ledger_rows(site=ns.site_b)[0]), 7)
		self.assertEqual(len(ledger_rows(resource=ns.trk1)[0]), 3)

	def test_filters_consumption_ledger(self):
		ns = self.ns

		def refs(**filters):
			_cols, rows = consumption_execute(filters)
			return {r["reference_document"] for r in rows}

		mine = {ns[k].name for k in SITE_WEEK_SCORES}
		self.assertEqual(refs(resource_type="Equipment") & mine, {ns.e1.name, ns.e2.name, ns.e3.name})
		self.assertEqual(refs(resource_type="Truck", fuel_tanker=ns.ta1),
			{ns.f1.name, ns.x1.name, ns.x2.name, ns.f3.name})
		self.assertEqual(refs(site=ns.site_b), {ns.r1.name, ns.r2.name})
		self.assertEqual(refs(fuel_tanker=ns.ta2), {ns.f2.name, ns.e3.name})
		self.assertEqual(refs(resource=ns.ftrk), {ns.x1.name, ns.x2.name})
		self.assertEqual(refs(from_date=day(-5), to_date=day(-3), resource_type="Equipment", fuel_tanker=ns.ta2),
			{ns.e3.name})
		self.assertEqual(refs(resource_type="Others", fuel_tanker=ns.ta1), set())

	def test_filters_resource_summary(self):
		ns = self.ns
		self.assertEqual(set(summary_rows(ns.resources)), set(ns.resources))
		self.assertEqual(set(summary_rows(ns.resources, resource_type="Truck")), {ns.trk1, ns.trk2, ns.ftrk})
		self.assertEqual(set(summary_rows(ns.resources, resource_type="Equipment")), {ns.eq1})
		self.assertEqual(set(summary_rows(ns.resources, only_without_baseline=1)), {ns.trk2, ns.ftrk})
		self.assertEqual(set(summary_rows(ns.resources, from_date=day(-6))), {ns.trk1, ns.eq1})
		self.assertEqual(set(summary_rows(ns.resources, to_date=day(-11))), {ns.trk1, ns.eq1, ns.trk2})
		_cols, rows = summary_execute({"resource": ns.resources})
		self.assertEqual(names(rows, "resource"), [ns.trk2, ns.trk1, ns.eq1, ns.ftrk], "most litres first")

	def test_resource_summary_site_filter_uses_the_stationed_site(self):
		# Regression (fixed): the site filter matches the tanker's site on each entry, while the Site column shows stationed_site
		ns = self.ns
		# EQ1 is stationed at B but fuelled only from site A's tankers
		self.assertEqual(set(summary_rows(ns.resources, site=[ns.site_b])), {ns.trk2, ns.eq1})
		self.assertEqual(set(summary_rows(ns.resources, site=[ns.site_a])), {ns.trk1, ns.ftrk})

	def test_filters_transfer_register(self):
		ns = self.ns

		def transfers(**filters):
			return names(transfer_execute(filters)[1])

		both = [ns.xfer_aa.name, ns.xfer_ab.name]
		self.assertEqual(transfers(fuel_tanker=[ns.ta1]), both, "TA1 sends one and receives the other")
		self.assertEqual(transfers(fuel_tanker=[ns.ta2]), [ns.xfer_aa.name])
		self.assertEqual(transfers(fuel_tanker=[ns.tb1]), [ns.xfer_ab.name])
		self.assertEqual(transfers(site=[ns.site_b]), [ns.xfer_ab.name])
		self.assertEqual(transfers(site=[ns.site_a]), both)
		self.assertEqual(transfers(site=[ns.site_a], from_date=day(-7)), [ns.xfer_aa.name])
		self.assertEqual(transfers(site=[ns.site_a], to_date=day(-7)), [ns.xfer_ab.name])
		self.assertEqual(transfers(fuel_tanker=ns.tb1), [ns.xfer_ab.name], "scalar works")
		self.assertEqual(transfers(fuel_tanker=ns.tankers, include_cancelled=1), both, "nothing cancelled here")

	def test_filters_supply_request_status(self):
		ns = self.ns

		def requests(**filters):
			return names(request_execute(filters)[1])

		req1, req2, req3 = ns.req1.name, ns.req2.name, ns.req3.name
		self.assertEqual(requests(fuel_tanker=ns.tankers, only_outstanding=1), [req3, req2])
		self.assertEqual(requests(fuel_tanker=ns.tankers, only_outstanding=0), [req3, req2, req1])
		self.assertEqual(requests(fuel_tanker=ns.tankers, status=["Fully Supplied"]), [req1])
		self.assertEqual(requests(fuel_tanker=ns.tankers, status=["Pending", "Partially Supplied"]), [req3, req2])
		self.assertEqual(requests(fuel_tanker=ns.tankers, status="Pending"), [req3])
		self.assertEqual(requests(site=[ns.site_b]), [req2])
		self.assertEqual(requests(site=[ns.site_a], from_date=day(-7)), [req3])
		self.assertEqual(requests(fuel_tanker=ns.tankers, to_date=day(-7)), [req2, req1])

	def test_filters_miscellaneous_register(self):
		ns = self.ns
		_c, rows, _chart = misc_register(site=[ns.site_a])
		self.assertEqual(names(rows), [ns.misc_a.name])
		_c, rows, _chart = misc_register(site=[ns.site_b])
		self.assertEqual(names(rows), [ns.misc_b.name])
		_c, rows, chart = misc_register(fuel_tanker=[ns.ta2])
		self.assertEqual(rows, [])
		self.assertIsNone(chart)
		cols, rows, _chart = misc_register(fuel_tanker=ns.tankers, include_cancelled=1)
		self.assertEqual(names(rows), [ns.misc_b.name, ns.misc_a.name])
		self.assertIn("cancelled_litres", [c["fieldname"] for c in cols])


# ---------------------------------------------------------------------------
# Scenario 3 — late keying into the middle of the history
# ---------------------------------------------------------------------------


class TestBackdatingScenario(ScenarioAssertions, FrappeTestCase):
	"""The site week, then three documents keyed in late.

	    TA2 supplied 400 at d-11 12:00 (REQ4)        between its d-13 supply and the d-10 TRK1 fill
	    TA1 -> TRK1 50 L @ 10,800 km at d-11 08:00   between TRK1's 10,400 (d-12) and 11,200 (d-10)
	    TA1 miscellaneous 30 L at d-9 10:00          between the d-9 08:00 issue and the d-9 12:00 fill
	"""

	LEDGER = {
		"ta1": [
			("Opening Balance", 0, 0, 0, 0, 2000),
			("Dispensed", 0, 200, 0, 2000, 1800),
			("Dispensed", 0, 150, 0, 1800, 1650),
			("Dispensed", 0, 50, 0, 1650, 1600),        # late TRK1 fill
			("Dispensed", 0, 100, 0, 1600, 1500),
			("Miscellaneous", 0, 40, 0, 1500, 1460),
			("Miscellaneous", 0, 30, 0, 1460, 1430),    # late site issue
			("Dispensed", 0, 90, 0, 1430, 1340),
			("Transfer Out", 0, 600, 0, 1340, 740),
			("Dispensed", 0, 80, 0, 740, 660),
			("Transfer In", 100, 0, 0, 660, 760),
			("Dispensed", 0, 100, 0, 760, 660),
		],
		"ta2": [
			("Supplied", 1000, 0, 0, 0, 1000),
			("Supplied", 400, 0, 0, 1000, 1400),        # late supply
			("Dispensed", 0, 120, 0, 1400, 1280),
			("Adjustment", 0, 0, -30, 1280, 1250),
			("Transfer Out", 0, 100, 0, 1250, 1150),
			("Dispensed", 0, 60, 0, 1150, 1090),
		],
		"tb1": SITE_WEEK_LEDGER["tb1"],
	}
	BALANCES = {
		"ta1": (bal(t_in=100, dispensed=770, misc=70, t_out=600, opening_entry=2000, closing=660), "OK"),
		"ta2": (bal(supplied=1400, dispensed=180, t_out=100, adjusted=-30, closing=1090), "OK"),
		"tb1": SITE_WEEK_BALANCES["tb1"],
	}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ns = cls.ns = build_site_week("TEST-FT-E2E-3")
		cls.modified_before = {
			e.name: e.modified for e in frappe.get_all(
				"Fuel Entry", filters={"fuel_tanker": ["in", ns.tankers], "docstatus": 1}, fields=["name", "modified"]
			)
		}
		ns.req4 = request_supply(ns.ta2, 400, date=day(-11))
		ns.bd_supply = supply(ns.ta2, 400, date=day(-11), posting_time="12:00:00", request=ns.req4.name)
		ns.bd_fill = dispense(ns.ta1, ns.trk1, 50, odometer_km=10800, date=day(-11), posting_time="08:00:00")
		ns.bd_misc = issue_miscellaneous(
			ns.ta1, 30, description="Washing down the mixer", date=day(-9), posting_time="10:00:00"
		)

	def test_every_later_entry_is_repriced(self):
		self.check_ledger(self.ns, self.LEDGER)

	def test_reports_reconcile_after_backdating(self):
		ns = self.ns
		self.check_balance_report(ns, self.BALANCES)
		self.check_agreement(ns, {"ta1": 660, "ta2": 1090, "tb1": 1990})
		self.assertEqual(get_tanker_balance_on(ns.ta1, day(-11), "08:00:00"), 1600)
		self.assertEqual(get_tanker_balance_on(ns.ta2, day(-11), "23:59:59"), 1400)

	def test_reposted_rows_keep_their_modified_stamp(self):
		"""Derived balances are rewritten without bumping `modified`."""
		ns = self.ns
		repriced = entry_for(ns.f3)
		self.assertEqual(repriced.previous_balance, 760)
		self.assertEqual(repriced.modified, self.modified_before[repriced.name])

	def test_readings_and_distances_are_reposted(self):
		ns = self.ns
		self.assertEqual(frappe.db.get_value("Fuel Used", ns.bd_fill.name, "previous_odometer_km"), 10400)
		self.assertEqual(entry_for(ns.bd_fill).diff_odometer, 400)
		# the fill after the late one is now measured from it
		self.assertEqual(frappe.db.get_value("Fuel Used", ns.f2.name, "previous_odometer_km"), 10800)
		self.assertEqual(entry_for(ns.f2).diff_odometer, 400)
		self.assertEqual(entry_for(ns.f3).diff_odometer, 300)
		self.assertEqual(frappe.db.get_value("Resource", ns.trk1, "current_odometer"), 11500, "not dragged back")

	def test_consumption_is_rescored(self):
		ns = self.ns
		self.check_scores(ns, {
			"f1": dict(alert_status="First Fill", kilometers=400),
			# 200 L (f1) over 400 km = 0.5, double the baseline
			"bd_fill": dict(alert_status="High Alert", litres_dispensed=200, kilometers=400, consumption=0.5),
			# now 50 L (the late fill) over 400 km = 0.125
			"f2": dict(alert_status="Good", litres_dispensed=50, kilometers=400, consumption=0.125),
			"f3": dict(alert_status="High Alert", litres_dispensed=120, kilometers=300, consumption=0.4),
		}, resources=[ns.trk1])
		rows = summary_rows([ns.trk1])
		self.assert_fields(rows[ns.trk1], "trk1", fills=4, litres=470)

	def test_summary_is_remeasured(self):
		# Regression (fixed): summary divides every litre drawn by every diff (first fills included) instead of the ledger's scored fills
		ns = self.ns
		# scored: 200/400 + 50/400 + 120/300 -> 370 L over 1100 km = 0.3364, +34.5%
		self.check_summary(ns, {
			"trk1": (dict(fills=4, litres=470, distance=1100, measured_litres=370, observed_consumption=0.3364,
				status="High Alert"), 34.55),
		}, resources=[ns.trk1])

	def test_registers_and_requests_after_backdating(self):
		ns = self.ns
		_cols, rows, chart = misc_register(fuel_tanker=ns.tankers)
		self.assertEqual(names(rows), [ns.misc_b.name, ns.bd_misc.name, ns.misc_a.name], "posting order, newest first")
		self.assertEqual(chart["data"]["labels"], [ns.site_a, ns.site_b])
		self.assertEqual(chart["data"]["datasets"][0]["values"], [70, 25])

		_cols, rows = request_execute({"fuel_tanker": [ns.ta2]})
		by = {r["name"]: r for r in rows}
		self.assert_fields(by[ns.req4.name], "REQ4", supplied_litres=400, pending_litres=0, status="Fully Supplied",
			deliveries=1)

	def test_windows_still_chain(self):
		ns = self.ns
		_c, w1 = self.check_balance_report(ns, {
			"ta1": (bal(dispensed=590, misc=70, t_out=600, opening_entry=2000, closing=740), None),
			"ta2": (bal(supplied=1400, dispensed=120, closing=1280), None),
			"tb1": (bal(supplied=2000, t_in=600, dispensed=550, closing=2050), None),
		}, from_date=day(-14), to_date=day(-8))
		_c, w2 = self.check_balance_report(ns, {
			"ta1": (bal(opening=740, t_in=100, dispensed=180, closing=660), None),
			"ta2": (bal(opening=1280, dispensed=60, t_out=100, adjusted=-30, closing=1090), None),
			"tb1": (bal(opening=2050, misc=25, adjusted=-35, closing=1990), None),
		}, from_date=day(-7))
		for tanker in ns.tankers:
			self.assertEqual(w1[tanker]["current_balance"], w2[tanker]["opening_balance"])


# ---------------------------------------------------------------------------
# Scenario 4 — cancelling from the middle of the history
# ---------------------------------------------------------------------------


class TestCancellationScenario(ScenarioAssertions, FrappeTestCase):
	"""The site week, then five cancellations, each through its Fuel Entry.

	    TB1 dip count (-35)            TB1 back to 2,025 from d-4
	    TB1 800 L supply (d-11, REQ2)  TB1 -800 from d-11; REQ2 rolls back to 1,200 of 3,000
	    TA2 -> TRK1 120 L (d-10)       TA2 +120; TRK1's d-5 fill now measured from 10,400
	    TA1 miscellaneous 40 L (d-9)   TA1 +40
	    TA1 -> TB1 transfer, via its Transfer In leg   TA1 +600, TB1 -600, both legs gone
	"""

	LEDGER = {
		"ta1": [
			("Opening Balance", 0, 0, 0, 0, 2000),
			("Dispensed", 0, 200, 0, 2000, 1800),
			("Dispensed", 0, 150, 0, 1800, 1650),
			("Dispensed", 0, 100, 0, 1650, 1550),
			("Dispensed", 0, 90, 0, 1550, 1460),
			("Dispensed", 0, 80, 0, 1460, 1380),
			("Transfer In", 100, 0, 0, 1380, 1480),
			("Dispensed", 0, 100, 0, 1480, 1380),
		],
		"ta2": [
			("Supplied", 1000, 0, 0, 0, 1000),
			("Adjustment", 0, 0, -30, 1000, 970),
			("Transfer Out", 0, 100, 0, 970, 870),
			("Dispensed", 0, 60, 0, 870, 810),
		],
		"tb1": [
			("Supplied", 1200, 0, 0, 0, 1200),
			("Dispensed", 0, 300, 0, 1200, 900),
			("Dispensed", 0, 250, 0, 900, 650),
			("Miscellaneous", 0, 25, 0, 650, 625),
		],
	}
	BALANCES = {
		"ta1": (bal(t_in=100, dispensed=720, opening_entry=2000, closing=1380), "OK"),
		"ta2": (bal(supplied=1000, dispensed=60, t_out=100, adjusted=-30, closing=810), "OK"),
		"tb1": (bal(supplied=1200, dispensed=550, misc=25, closing=625), "Low"),
	}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ns = cls.ns = build_site_week("TEST-FT-E2E-4")
		cls.cancelled_entries = set()
		for doc in (ns.adj_measured, ns.sup_tb1_b, ns.f2, ns.misc_a, ns.xfer_ab):
			cls.cancelled_entries.update(e.name for e in entries_for(doc))
		cancel_via_entry(ns.adj_measured)
		cancel_via_entry(ns.sup_tb1_b)
		cancel_via_entry(ns.f2)
		cancel_via_entry(ns.misc_a)
		cancel_via_entry(ns.xfer_ab, "Transfer In")

	def test_sources_and_both_transfer_legs_are_cancelled(self):
		ns = self.ns
		for doc in (ns.adj_measured, ns.sup_tb1_b, ns.f2, ns.misc_a, ns.xfer_ab):
			self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "docstatus"), 2, doc.name)
		self.assertEqual(len(entries_for(ns.xfer_ab)), 0)
		self.assertEqual(len(entries_for(ns.xfer_ab, docstatus=2)), 2)

	def test_ledger_after_cancellations(self):
		self.check_ledger(self.ns, self.LEDGER)
		data, _total = ledger_rows(fuel_tanker=self.ns.tankers)
		self.assertFalse(self.cancelled_entries & set(names(data)), "cancelled entries never appear")

	def test_reports_reconcile_after_cancellations(self):
		ns = self.ns
		self.check_balance_report(ns, self.BALANCES)
		self.check_agreement(ns, {"ta1": 1380, "ta2": 810, "tb1": 625})

	def test_readings_roll_back(self):
		ns = self.ns
		self.assertEqual(frappe.db.get_value("Fuel Used", ns.f3.name, "previous_odometer_km"), 10400)
		self.assertEqual(entry_for(ns.f3).diff_odometer, 1100)
		self.assertEqual(frappe.db.get_value("Resource", ns.trk1, "current_odometer"), 11500)
		# TRK1: f1 first fill, f3 now 200 L (f1) over 1,100 km = 0.1818
		self.check_scores(ns, {
			"f1": dict(alert_status="First Fill"),
			"f3": dict(alert_status="Good", litres_dispensed=200, kilometers=1100, consumption=0.1818,
				variance=-0.0682, fuel_supposed_to_be_used=275),
		}, resources=[ns.trk1])
		self.assert_fields(summary_rows([ns.trk1])[ns.trk1], "trk1", fills=2, litres=300)

	def test_summary_after_cancellations(self):
		# Regression (fixed): summary divides every litre drawn by every diff (first fills included) instead of the ledger's scored fills
		ns = self.ns
		self.check_summary(ns, {
			"trk1": (dict(fills=2, litres=300, distance=1100, measured_litres=200, observed_consumption=0.1818,
				status="Good"), -27.27),
		}, resources=[ns.trk1])

	def test_supply_request_rolls_back(self):
		ns = self.ns
		_cols, rows = request_execute({"fuel_tanker": ns.tankers})
		by = {r["name"]: r for r in rows}
		self.assert_fields(by[ns.req2.name], "REQ2", supplied_litres=1200, pending_litres=1800, fulfilled_pct=40,
			deliveries=1, status="Partially Supplied")
		self.assert_fields(by[ns.req1.name], "REQ1", status="Fully Supplied", deliveries=1)
		_cols, rows = request_execute({"fuel_tanker": ns.tankers, "only_outstanding": 1})
		self.assertEqual(names(rows), [ns.req3.name, ns.req2.name])

	def test_registers_after_cancellations(self):
		ns = self.ns
		_cols, rows = transfer_execute({"fuel_tanker": ns.tankers})
		self.assertEqual(names(rows), [ns.xfer_aa.name], "a cancelled transfer is gone by default")

		_cols, rows, chart = misc_register(fuel_tanker=ns.tankers)
		self.assertEqual(names(rows), [ns.misc_b.name])
		cols, rows, chart = misc_register(fuel_tanker=ns.tankers, include_cancelled=1)
		self.assertEqual(names(rows), [ns.misc_b.name, ns.misc_a.name])
		self.assert_fields(rows[1], "cancelled issue", status="Cancelled", litres=0, cancelled_litres=40)
		self.assertIn("cancelled_litres", [c["fieldname"] for c in cols])
		self.assertEqual(chart["data"]["labels"], [ns.site_b], "a cancelled issue moved no fuel")
		self.assertEqual(chart["data"]["datasets"][0]["values"], [25])

	def test_cancelling_the_only_supply_reopens_the_request(self):
		tanker = make_tanker("TEST-FT-E2E-4B").name
		request = request_supply(tanker, 500, date=day(-5))
		delivery = supply(tanker, 500, date=day(-4), posting_time="08:00:00", request=request.name)
		self.assertEqual(frappe.db.get_value("Fuel Supply Request", request.name, "status"), "Fully Supplied")

		cancel_via_entry(delivery)

		_cols, rows = request_execute({"fuel_tanker": [tanker], "only_outstanding": 1})
		self.assertEqual(names(rows), [request.name])
		self.assert_fields(rows[0], "request", supplied_litres=0, pending_litres=500, fulfilled_pct=0, deliveries=0,
			status="Pending")
		self.assertEqual(balance(tanker), 0)


# ---------------------------------------------------------------------------
# Scenario 5 — amending cancelled documents
# ---------------------------------------------------------------------------


class TestAmendScenario(ScenarioAssertions, FrappeTestCase):
	"""The site week, then two corrections by cancel-and-amend.

	    TA2 -> TRK1 at d-10: 120 L was wrong, it was 135 L (same reading, same moment)
	    TA1 miscellaneous at d-9: 40 L was wrong, it was 45 L, with a corrected description
	"""

	LEDGER = {
		"ta1": [
			("Opening Balance", 0, 0, 0, 0, 2000),
			("Dispensed", 0, 200, 0, 2000, 1800),
			("Dispensed", 0, 150, 0, 1800, 1650),
			("Dispensed", 0, 100, 0, 1650, 1550),
			("Miscellaneous", 0, 45, 0, 1550, 1505),
			("Dispensed", 0, 90, 0, 1505, 1415),
			("Transfer Out", 0, 600, 0, 1415, 815),
			("Dispensed", 0, 80, 0, 815, 735),
			("Transfer In", 100, 0, 0, 735, 835),
			("Dispensed", 0, 100, 0, 835, 735),
		],
		"ta2": [
			("Supplied", 1000, 0, 0, 0, 1000),
			("Dispensed", 0, 135, 0, 1000, 865),
			("Adjustment", 0, 0, -30, 865, 835),
			("Transfer Out", 0, 100, 0, 835, 735),
			("Dispensed", 0, 60, 0, 735, 675),
		],
		"tb1": SITE_WEEK_LEDGER["tb1"],
	}
	BALANCES = {
		"ta1": (bal(t_in=100, dispensed=720, misc=45, t_out=600, opening_entry=2000, closing=735), "OK"),
		"ta2": (bal(supplied=1000, dispensed=195, t_out=100, adjusted=-30, closing=675), "OK"),
		"tb1": SITE_WEEK_BALANCES["tb1"],
	}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ns = cls.ns = build_site_week("TEST-FT-E2E-5")
		cancel_via_entry(ns.f2)
		ns.f2_amended = amend(ns.f2, fuel_issued_lts=135)
		cancel_via_entry(ns.misc_a)
		ns.misc_a_amended = amend(
			ns.misc_a, fuel_issued_lts=45, description="Cleaning tools after work (corrected)"
		)

	def test_amended_documents_replace_the_originals(self):
		ns = self.ns
		for original, amended in ((ns.f2, ns.f2_amended), (ns.misc_a, ns.misc_a_amended)):
			self.assertEqual(amended.name, original.name + "-1")
			self.assertEqual(amended.amended_from, original.name)
			self.assertEqual(amended.docstatus, 1)
			self.assertEqual(frappe.db.get_value("Fuel Used", original.name, "docstatus"), 2)
			self.assertIsNone(entry_for(original))
			self.assertEqual(entry_for(amended).posting_datetime, entry_for(original, docstatus=2).posting_datetime)
		self.assertEqual(entry_for(ns.misc_a_amended).utilization_type, "Miscellaneous")

	def test_ledger_and_balances_after_amend(self):
		ns = self.ns
		self.check_ledger(ns, self.LEDGER)
		self.check_balance_report(ns, self.BALANCES)
		self.check_agreement(ns, {"ta1": 735, "ta2": 675, "tb1": 1990})
		data, _total = ledger_rows(fuel_tanker=[ns.ta1], utilization_type="Miscellaneous")
		self.assertEqual([(r["litres_dispensed"], r["description"]) for r in data],
			[(45, "Cleaning tools after work (corrected)")])

	def test_readings_and_scores_after_amend(self):
		ns = self.ns
		self.assertEqual(frappe.db.get_value("Fuel Used", ns.f2_amended.name, "previous_odometer_km"), 10400)
		self.assertEqual(entry_for(ns.f2_amended).diff_odometer, 800)
		self.assertEqual(frappe.db.get_value("Fuel Used", ns.f3.name, "previous_odometer_km"), 11200)
		self.assertEqual(frappe.db.get_value("Resource", ns.trk1, "current_odometer"), 11500)
		self.check_scores(ns, {
			"f1": dict(alert_status="First Fill"),
			"f2_amended": dict(alert_status="Good", litres_dispensed=200, kilometers=800, consumption=0.25),
			# the corrected 135 L over 300 km = 0.45
			"f3": dict(alert_status="High Alert", litres_dispensed=135, kilometers=300, consumption=0.45,
				variance=0.2, fuel_supposed_to_be_used=75),
		}, resources=[ns.trk1])
		self.assert_fields(summary_rows([ns.trk1])[ns.trk1], "trk1", fills=3, litres=435)

	def test_summary_after_amend(self):
		# Regression (fixed): summary divides every litre drawn by every diff (first fills included) instead of the ledger's scored fills
		ns = self.ns
		# scored: 200 L/800 km + 135 L/300 km -> 335/1100 = 0.3045, +21.8%
		self.check_summary(ns, {
			"trk1": (dict(fills=3, litres=435, distance=1100, measured_litres=335, observed_consumption=0.3045,
				status="High Alert"), 21.8),
		}, resources=[ns.trk1])

	def test_miscellaneous_register_after_amend(self):
		ns = self.ns
		_cols, rows, chart = misc_register(fuel_tanker=ns.tankers)
		self.assertEqual(names(rows), [ns.misc_b.name, ns.misc_a_amended.name])
		self.assert_fields(rows[1], "amended", litres=45, description="Cleaning tools after work (corrected)",
			status="Submitted")
		self.assertEqual(chart["data"]["datasets"][0]["values"], [45, 25])

		_cols, rows, chart = misc_register(fuel_tanker=ns.tankers, include_cancelled=1)
		self.assertEqual(names(rows), [ns.misc_b.name, ns.misc_a_amended.name, ns.misc_a.name])
		self.assert_fields(rows[2], "original", status="Cancelled", litres=0, cancelled_litres=40)
		self.assertEqual(chart["data"]["datasets"][0]["values"], [45, 25])


# ---------------------------------------------------------------------------
# Transfer register with cancelled and draft transfers
# ---------------------------------------------------------------------------


class TestTransferRegisterCancelled(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		site_a = ensure_site("TEST-FT-E2E-9-SITE-A")
		site_b = ensure_site("TEST-FT-E2E-9-SITE-B")
		cls.source = make_tanker("TEST-FT-E2E-9A", site=site_a).name
		cls.dest = make_tanker("TEST-FT-E2E-9B", site=site_b).name
		supply(cls.source, 1000, date=day(-6), posting_time="08:00:00")
		cls.kept = transfer(cls.source, cls.dest, 300, date=day(-4), posting_time="08:00:00")
		cls.dropped = transfer(cls.source, cls.dest, 200, date=day(-3), posting_time="08:00:00")
		cls.draft = transfer(cls.source, cls.dest, 50, date=day(-2), posting_time="08:00:00", submit=False)
		cancel_via_entry(cls.dropped, "Transfer Out")

	def test_default_lists_only_submitted_transfers(self):
		_cols, rows = transfer_execute({"fuel_tanker": [self.source]})
		self.assertEqual([r["name"] for r in rows], [self.kept.name])
		self.assertEqual(balance(self.source), 700)
		self.assertEqual(balance(self.dest), 300)
		self.assertEqual(len(entries_for(self.dropped, docstatus=2)), 2, "both legs cancelled")

	def test_include_cancelled_adds_cancelled_transfers_not_drafts(self):
		# Regression (fixed): include_cancelled filters `docstatus < 2`, so it hides cancelled transfers and lists drafts as "Submitted"
		_cols, rows = transfer_execute({"fuel_tanker": [self.source], "include_cancelled": 1})
		by = {r["name"]: r for r in rows}
		self.assertNotIn(self.draft.name, by, "a draft never moved fuel")
		self.assertEqual(set(by), {self.kept.name, self.dropped.name})
		self.assertEqual(by[self.dropped.name]["status"], "Cancelled")


# ---------------------------------------------------------------------------
# Measured Balance is a stock count, not a delta
# ---------------------------------------------------------------------------


class TestMeasuredBalanceIsAStockCount(FrappeTestCase):
	def test_backdated_supply_before_a_dip_count_keeps_the_counted_stock(self):
		# Regression (fixed): a Measured Balance adjustment reposts as a fixed delta, so a movement keyed in before the dip shifts the counted stock
		tanker = make_tanker("TEST-FT-E2E-8A").name
		supply(tanker, 1000, date=day(-10), posting_time="08:00:00")
		dip = adjust(tanker, mode="Measured Balance", measured=900, date=day(-5), posting_time="08:00:00")
		self.assertEqual(entry_for(dip).litres_adjusted, -100)

		# a 200 L delivery on d-8 is keyed in late: it was in the tank when it was dipped
		supply(tanker, 200, date=day(-8), posting_time="08:00:00")

		self.assertEqual(entry_for(dip).current_balance, 900, "the dip counted 900 L")
		self.assertEqual(balance(tanker), 900)

	def test_cancelling_a_movement_before_a_dip_count_keeps_the_counted_stock(self):
		# Regression (fixed): a Measured Balance adjustment reposts as a fixed delta, so cancelling a movement before the dip shifts the counted stock
		tanker = make_tanker("TEST-FT-E2E-8B").name
		truck = make_resource("TEST-FT-E2E-8B-TRK", "Truck", reading=1000).name
		supply(tanker, 1000, date=day(-10), posting_time="08:00:00")
		mistake = dispense(tanker, truck, 100, odometer_km=1100, date=day(-8), posting_time="08:00:00")
		dip = adjust(tanker, mode="Measured Balance", measured=850, date=day(-5), posting_time="08:00:00")
		self.assertEqual(entry_for(dip).litres_adjusted, -50)

		cancel_via_entry(mistake)

		self.assertEqual(entry_for(dip).current_balance, 850, "the dip counted 850 L")
		self.assertEqual(balance(tanker), 850)


# ---------------------------------------------------------------------------
# Scenario 7 — edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(ScenarioAssertions, FrappeTestCase):
	def test_overdraw_is_warned_not_blocked_and_reconciles(self):
		tanker = make_tanker("TEST-FT-E2E-7A").name
		truck = make_resource("TEST-FT-E2E-7A-TRK", "Truck", reading=1000).name
		supply(tanker, 100, date=day(-5), posting_time="08:00:00")

		frappe.clear_messages()
		doc = dispense(tanker, truck, 150, odometer_km=1100, date=day(-3), posting_time="08:00:00")

		self.assertEqual(doc.docstatus, 1)
		self.assertIn("exceeds the balance", messages_text())
		self.assertEqual((entry_for(doc).previous_balance, entry_for(doc).current_balance), (100, -50))
		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "overdrawn", litres_supplied=100, litres_dispensed=150, current_balance=-50,
			difference=0)
		self.assertNotEqual(rows[0]["status"], "Check Ledger")
		self.assertEqual(balance(tanker), -50)
		self.assertEqual(ledger_rows(fuel_tanker=[tanker])[0][-1]["current_balance"], -50)
		self.assertEqual(fuelBalance(tanker_site(tanker), tanker), -50)

	def test_backdated_withdrawal_that_overdraws_later_is_warned(self):
		tanker = make_tanker("TEST-FT-E2E-7B").name
		truck = make_resource("TEST-FT-E2E-7B-TRK", "Truck", reading=1000).name
		supply(tanker, 500, date=day(-10), posting_time="08:00:00")
		later = dispense(tanker, truck, 450, odometer_km=1500, date=day(-2), posting_time="08:00:00")

		frappe.clear_messages()
		# affordable on d-6 (500 L), but leaves the d-2 fill 50 L short
		early = dispense(tanker, truck, 100, odometer_km=1200, date=day(-6), posting_time="08:00:00")

		self.assertIn("drives its balance negative later", messages_text())
		self.assertEqual(entry_for(early).current_balance, 400)
		self.assertEqual((entry_for(later).previous_balance, entry_for(later).current_balance), (400, -50))
		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "overdrawn later", current_balance=-50, difference=0)

	def test_negative_balance_is_flagged_on_the_balance_report(self):
		# Regression (fixed): get_status reports a negative closing balance as "OK" (or "Low") instead of "Negative"
		tanker = make_tanker("TEST-FT-E2E-7C", minimum_level=500).name
		truck = make_resource("TEST-FT-E2E-7C-TRK", "Truck", reading=1000).name
		supply(tanker, 100, date=day(-5), posting_time="08:00:00")
		dispense(tanker, truck, 150, odometer_km=1100, date=day(-3), posting_time="08:00:00")

		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		self.assertEqual(rows[0]["status"], "Negative", "checked before Low")

	def test_same_timestamp_entries_follow_creation_order(self):
		tanker = make_tanker("TEST-FT-E2E-7D").name
		truck = make_resource("TEST-FT-E2E-7D-TRK", "Truck", reading=1000).name
		at = dict(date=day(-4), posting_time="08:00:00")

		s1 = supply(tanker, 500, **at)
		d1 = dispense(tanker, truck, 100, odometer_km=1100, **at)
		m1 = issue_miscellaneous(tanker, 50, **at)
		s3 = supply(tanker, 200, **at)
		s2 = supply(tanker, 300, date=day(-4), posting_time="07:00:00")  # earlier moment, recorded last

		data, total = ledger_rows(fuel_tanker=[tanker])
		self.assertEqual(names(data), [entry_for(d).name for d in (s2, s1, d1, m1, s3)])
		self.assertEqual(movements(data), [
			("Supplied", 300, 0, 0, 0, 300),
			("Supplied", 500, 0, 0, 300, 800),
			("Dispensed", 0, 100, 0, 800, 700),
			("Miscellaneous", 0, 50, 0, 700, 650),
			("Supplied", 200, 0, 0, 650, 850),
		])
		self.assertEqual(get_tanker_balance_on(tanker, day(-4), "07:30:00"), 300)
		self.assertEqual(get_tanker_balance_on(tanker, day(-4), "08:00:00"), 850, "every 08:00 entry included")
		self.assertEqual(balance(tanker), 850)
		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "same moment", litres_supplied=1000, litres_dispensed=100,
			litres_miscellaneous=50, current_balance=850, difference=0)

		# creation, not intent, breaks the tie: a dispense recorded first sorts first
		other = make_tanker("TEST-FT-E2E-7E").name
		first = dispense(other, truck, 150, odometer_km=1200, date=day(-3), posting_time="09:00:00")
		second = supply(other, 500, date=day(-3), posting_time="09:00:00")
		self.assertEqual((entry_for(first).previous_balance, entry_for(first).current_balance), (0, -150))
		self.assertEqual((entry_for(second).previous_balance, entry_for(second).current_balance), (-150, 350))

	def test_fill_order_at_one_moment_follows_fuel_used_creation(self):
		# Regression (fixed): the consumption ledger breaks same-moment ties on Fuel Entry creation, the reading ledger on Fuel Used creation
		tanker = make_tanker("TEST-FT-E2E-7F").name
		truck = make_resource("TEST-FT-E2E-7F-TRK", "Truck", reading=1000).name
		supply(tanker, 1000, date=day(-6), posting_time="08:00:00")

		first = dispense(tanker, truck, 50, odometer_km=1100, date=day(-4), posting_time="08:00:00", submit=False)
		second = dispense(tanker, truck, 30, odometer_km=1200, date=day(-4), posting_time="08:00:00")
		first.submit()  # the draft created first is submitted last

		# the reading sequence is first (1,100) then second (1,200)
		self.assertEqual(entry_for(first).diff_odometer, 100)
		self.assertEqual(entry_for(second).diff_odometer, 100)

		rows = consumption_rows([truck])
		self.assertEqual(rows[first.name]["alert_status"], "First Fill")
		self.assert_fields(rows[second.name], "second", alert_status="No Baseline", litres_dispensed=50,
			kilometers=100, consumption=0.5)

	def test_tanker_with_only_an_opening_balance(self):
		tanker = make_tanker("TEST-FT-E2E-7G").name
		open_balance(tanker, 750, date=day(-3))

		cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "opened", **bal(opening_entry=750, closing=750), difference=0)
		self.assertIn("opening_entry", [c["fieldname"] for c in cols])

		cols, rows = balance_execute({"from_date": day(-2), "to_date": today(), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "after opening", **bal(opening=750, closing=750), difference=0)
		self.assertNotIn("opening_entry", [c["fieldname"] for c in cols])

		_cols, rows = balance_execute({"from_date": day(-3), "to_date": day(-3), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "opening day", **bal(opening_entry=750, closing=750), difference=0)

		_cols, rows = balance_execute({"to_date": day(-4), "fuel_tanker": [tanker]})
		self.assert_fields(rows[0], "before opening", **bal(closing=0), difference=0)

		data, total = ledger_rows(fuel_tanker=[tanker])
		self.assertEqual(movements(data), [("Opening Balance", 0, 0, 0, 0, 750)])
		self.assertEqual(flt(total["litres_supplied"]), 0)
		self.assertEqual(balance(tanker), 750)
		self.assertEqual(frappe.db.get_value("Fuel Balance", tanker, "docstatus"), 1)
		self.assertEqual(fuelBalance(tanker_site(tanker), tanker), 750)
		self.assertEqual(fuelBalance(tanker_site(tanker), tanker, date=day(-4)), 0)
		self.assertEqual(get_tanker_balance_on(tanker, day(-3)), 750, "the 00:00 opening counts on its own day")

		frappe.db.savepoint("e2e_before_opening")
		with self.assertRaises(frappe.ValidationError):
			supply(tanker, 100, date=day(-5), posting_time="08:00:00")
		frappe.db.rollback(save_point="e2e_before_opening")
		self.assertEqual(balance(tanker), 750)

	def test_readings_must_sit_between_their_neighbours(self):
		tanker = make_tanker("TEST-FT-E2E-7I").name
		supply(tanker, 2000, date=day(-10), posting_time="08:00:00")
		eq = make_resource("TEST-FT-E2E-7I-EQ", "Equipment", reading=100).name
		truck = make_resource("TEST-FT-E2E-7I-TRK", "Truck", reading=1000).name
		dispense(tanker, eq, 20, hours_copy=110, date=day(-5), posting_time="08:00:00")
		dispense(tanker, truck, 20, odometer_km=1100, date=day(-6), posting_time="08:00:00")
		dispense(tanker, truck, 20, odometer_km=1300, date=day(-2), posting_time="08:00:00")

		for label, kwargs in (
			("hours going backwards", dict(resource=eq, hours_copy=105, date=day(-3))),
			("km overtaking the later fill", dict(resource=truck, odometer_km=1400, date=day(-4))),
			("km behind the earlier fill", dict(resource=truck, odometer_km=1050, date=day(-4))),
		):
			frappe.db.savepoint("e2e_reading")
			resource = kwargs.pop("resource")
			with self.assertRaises(frappe.ValidationError, msg=label):
				dispense(tanker, resource, 10, posting_time="08:00:00", **kwargs)
			frappe.db.rollback(save_point="e2e_reading")

		# a reading that fits between them is accepted
		fits = dispense(tanker, truck, 10, odometer_km=1200, date=day(-4), posting_time="08:00:00")
		self.assertEqual(entry_for(fits).diff_odometer, 100)
		self.assertEqual(frappe.db.get_value("Resource", truck, "current_odometer"), 1300)
		self.assertEqual(frappe.db.get_value("Resource", eq, "current_hours"), 110)

	def test_first_fill_inside_the_report_window(self):
		ns = self._first_fill_fixture("TEST-FT-E2E-7H")
		# the old truck's first in-window fill is scored against its d-9 fill, outside the window
		rows = consumption_rows([ns.old, ns.new], from_date=day(-5))
		self.assertEqual(set(rows), {ns.old_second.name, ns.new_first.name})
		self.assert_fields(rows[ns.old_second.name], "old", alert_status="Good", litres_dispensed=100,
			kilometers=500, consumption=0.2)
		self.assertEqual(rows[ns.new_first.name]["alert_status"], "First Fill")
		rows = consumption_rows([ns.old], from_date=day(-10))
		self.assertEqual(rows[ns.old_first.name]["alert_status"], "First Fill")

		rows = summary_rows([ns.old, ns.new], from_date=day(-5))
		self.assert_fields(rows[ns.old], "old", fills=1, litres=60)
		self.assert_fields(rows[ns.new], "new", fills=1, litres=80)

	def test_summary_first_fill_in_window_contributes_no_distance(self):
		# Regression (fixed): summary counts a first fill's distance (measured from the opening reading) as consumption distance
		ns = self._first_fill_fixture("TEST-FT-E2E-7HS")
		rows = summary_rows([ns.old, ns.new], from_date=day(-5))
		self.assert_fields(rows[ns.new], "new", distance=0, measured_litres=0, observed_consumption=0,
			status="Not Measurable")
		self.assert_fields(rows[ns.old], "old", distance=500, measured_litres=100, observed_consumption=0.2,
			status="Good")

	def _first_fill_fixture(self, prefix):
		ns = frappe._dict()
		ns.tanker = make_tanker(prefix).name
		supply(ns.tanker, 5000, date=day(-20), posting_time="08:00:00")
		ns.old = make_resource(prefix + "-OLD", "Truck", reading=3000, average_consumption=0.2).name
		ns.new = make_resource(prefix + "-NEW", "Truck", reading=7000).name
		ns.old_first = dispense(ns.tanker, ns.old, 100, odometer_km=3500, date=day(-9), posting_time="08:00:00")
		ns.old_second = dispense(ns.tanker, ns.old, 60, odometer_km=4000, date=day(-4), posting_time="08:00:00")
		ns.new_first = dispense(ns.tanker, ns.new, 80, odometer_km=7500, date=day(-3), posting_time="08:00:00")
		return ns

	def test_consumption_compares_against_the_live_baseline(self):
		# Regression (fixed): the consumption ledger scores against Fuel Entry.average_consumption, a copy frozen at fill time
		tanker = make_tanker("TEST-FT-E2E-7L").name
		supply(tanker, 1000, date=day(-10), posting_time="08:00:00")
		truck = make_resource("TEST-FT-E2E-7L-TRK", "Truck", reading=1000, average_consumption=0.25).name
		dispense(tanker, truck, 100, odometer_km=1100, date=day(-8), posting_time="08:00:00")
		second = dispense(tanker, truck, 50, odometer_km=1400, date=day(-4), posting_time="08:00:00")

		# the baseline is corrected after the fills were recorded
		frappe.db.set_value("Resource", truck, "average_consumption", 0.5)

		rows = consumption_rows([truck])
		# 100 L / 300 km = 0.3333, under the corrected 0.5
		self.assert_fields(rows[second.name], "second", consumption=0.3333, average_consumption=0.5,
			variance=-0.1667, alert_status="Good")
		self.assertEqual(summary_rows([truck])[truck]["average_consumption"], 0.5, "the summary already reads it live")

	def test_summary_example_equipment(self):
		# Regression (fixed): summary divides every litre drawn by every diff (first fills included) instead of the ledger's scored fills
		tanker = make_tanker("TEST-FT-E2E-7M").name
		supply(tanker, 1000, date=day(-10), posting_time="08:00:00")
		eq = make_resource("TEST-FT-E2E-7M-EQ", "Equipment", reading=100).name
		dispense(tanker, eq, 100, hours_copy=110, date=day(-8), posting_time="08:00:00")
		dispense(tanker, eq, 50, hours_copy=120, date=day(-4), posting_time="08:00:00")

		self.assert_fields(summary_rows([eq])[eq], "equipment", fills=2, litres=150, distance=10,
			measured_litres=100, observed_consumption=10)

	def test_summary_is_one_row_per_resource(self):
		# Regression (fixed): the summary groups by (resource, resource_type), so entries carrying a stale type split a resource
		tanker = make_tanker("TEST-FT-E2E-7N").name
		supply(tanker, 1000, date=day(-10), posting_time="08:00:00")
		eq = make_resource("TEST-FT-E2E-7N-EQ", "Equipment", reading=100).name
		first = dispense(tanker, eq, 100, hours_copy=110, date=day(-8), posting_time="08:00:00")
		dispense(tanker, eq, 50, hours_copy=120, date=day(-4), posting_time="08:00:00")
		# legacy data: the resource was re-typed after its first fill was recorded
		frappe.db.set_value("Fuel Entry", entry_for(first).name, "resource_type", "Others", update_modified=False)

		_cols, rows = summary_execute({"resource": [eq]})
		self.assertEqual(len(rows), 1)
		self.assert_fields(rows[0], "equipment", fills=2, litres=150)


class TestUnmeteredResource(ScenarioAssertions, FrappeTestCase):
	"""A resource of type Others carries no meter at all."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tanker = make_tanker("TEST-FT-E2E-7J").name
		supply(cls.tanker, 1000, date=day(-10), posting_time="08:00:00")
		cls.pump = make_resource("TEST-FT-E2E-7J-PUMP", "Others").name
		cls.fills = [
			dispense(cls.tanker, cls.pump, 40, date=day(-6), posting_time="08:00:00"),
			dispense(cls.tanker, cls.pump, 30, date=day(-3), posting_time="08:00:00"),
		]

	def test_fills_need_no_reading_and_summary_is_not_metered(self):
		self.assertEqual(balance(self.tanker), 930)
		for fill in self.fills:
			self.assertEqual((entry_for(fill).diff_odometer, entry_for(fill).diff_hours_copy), (0, 0))
		# same status the consumption ledger gives these fills: unmetered, not idle
		self.assert_fields(summary_rows([self.pump])[self.pump], "pump", fills=2, litres=70, distance=0,
			observed_consumption=0, status="Not Metered")

	def test_consumption_ledger_reports_not_metered(self):
		# Regression (fixed): an Others resource falls through to "First Fill"/"No Movement", which reads as a measurement
		rows = consumption_rows([self.pump])
		self.assertEqual({r["alert_status"] for r in rows.values()}, {"Not Metered"})


class TestMeterRepairedMidPeriod(ScenarioAssertions, FrappeTestCase):
	"""A truck metered, then flagged faulty for one fill, then repaired.

	    d-9  A 100 L @ 1,100 km (from 1,000)    metered
	    d-7  B  60 L                            meter faulty
	    d-5  C  40 L @ 1,300 km                 metered again: 200 km since A
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tanker = make_tanker("TEST-FT-E2E-7K").name
		supply(cls.tanker, 1000, date=day(-10), posting_time="08:00:00")
		cls.truck = make_resource("TEST-FT-E2E-7K-TRK", "Truck", reading=1000, average_consumption=1).name
		cls.a = dispense(cls.tanker, cls.truck, 100, odometer_km=1100, date=day(-9), posting_time="08:00:00")
		frappe.db.set_value("Resource", cls.truck, {"has_faulty_meter": 1, "faulty_meter_remarks": "Cable cut"})
		cls.b = dispense(cls.tanker, cls.truck, 60, date=day(-7), posting_time="08:00:00")
		frappe.db.set_value("Resource", cls.truck, {"has_faulty_meter": 0, "faulty_meter_remarks": None})
		cls.c = dispense(cls.tanker, cls.truck, 40, odometer_km=1300, date=day(-5), posting_time="08:00:00")

	def test_reading_sequence_skips_the_unmetered_fill(self):
		self.assertEqual(entry_for(self.b).meter_faulty, 1)
		self.assertEqual(entry_for(self.c).diff_odometer, 200)
		self.assertEqual(frappe.db.get_value("Fuel Used", self.c.name, "previous_odometer_km"), 1100)
		self.assertEqual(frappe.db.get_value("Resource", self.truck, "current_odometer"), 1300)
		self.assertEqual(balance(self.tanker), 800)

	def test_consumption_attributes_every_litre_since_the_last_metered_fill(self):
		# Regression (fixed): only the immediately previous fill's litres are scored, so the faulty fill's 60 L stand in for A + B
		rows = consumption_rows([self.truck])
		self.assertEqual(rows[self.a.name]["alert_status"], "First Fill")
		self.assertEqual(rows[self.b.name]["alert_status"], "Meter Faulty")
		# A's 100 L + B's 60 L over 200 km = 0.8, under the 1.0 baseline
		self.assert_fields(rows[self.c.name], "C", litres_dispensed=160, kilometers=200, consumption=0.8,
			alert_status="Good")

	def test_summary_measures_only_the_scored_interval(self):
		# Regression (fixed): summary divides all 200 L (faulty fill included) by every diff, contradicting its own docstring
		row = summary_rows([self.truck])[self.truck]
		self.assert_fields(row, "truck", fills=3, litres=200, faulty_fills=1, distance=200, measured_litres=160,
			observed_consumption=0.8, status="Good")


class TestLedgerSiteIsTheTankers(FrappeTestCase):
	"""A dispense whose site was keyed by hand to another site than its tanker's."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.site_a = ensure_site("TEST-FT-E2E-7P-SITE-A")
		cls.site_b = ensure_site("TEST-FT-E2E-7P-SITE-B")
		cls.tanker = make_tanker("TEST-FT-E2E-7P", site=cls.site_a).name
		truck = make_resource("TEST-FT-E2E-7P-TRK", "Truck", reading=1000).name
		supply(cls.tanker, 500, date=day(-5), posting_time="08:00:00")
		fill = dispense(cls.tanker, truck, 100, odometer_km=1100, date=day(-3), posting_time="08:00:00")
		frappe.db.set_value("Fuel Entry", entry_for(fill).name, "site", cls.site_b, update_modified=False)

	def test_balance_report_keeps_the_tanker_whole(self):
		_cols, rows = balance_execute({"to_date": today(), "fuel_tanker": [self.tanker]})
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["site"], rows[0]["current_balance"], rows[0]["difference"]), (self.site_a, 400, 0))

	def test_ledger_site_filter_matches_the_tankers_site(self):
		# Regression (fixed): the Fuel Ledger site filter matches the site keyed on each entry, so a tanker's history splits across sites
		self.assertEqual(ledger_rows(fuel_tanker=[self.tanker], site=[self.site_b])[0], [])
		self.assertEqual(len(ledger_rows(fuel_tanker=[self.tanker], site=[self.site_a])[0]), 2)
