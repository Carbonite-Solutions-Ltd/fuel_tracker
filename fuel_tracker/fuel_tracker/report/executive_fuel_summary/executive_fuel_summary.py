# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""The whole fuel position on one page: every site, and every tanker in it.

For whoever has to answer "where is our fuel, where did it go, and what needs
attention?" without opening seven reports. Sites are rows that open onto
their tankers; headline cards carry the company-wide totals.

No balance is computed here. Each tanker's opening, movements and closing come
straight from the Fuel Balance report — the ledger, read once — so the two
reports cannot disagree, and a site is simply the sum of its tankers. On top
of that it adds what a balance report cannot say: how long the stock lasts at
the period's rate of use, how much fuel is already on order, how many fills
tripped a consumption alert, and how much activity each site saw.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, fmt_money, get_first_day, getdate, nowdate

from fuel_tracker.fuel_tracker.consumption import get_fills, in_period
from fuel_tracker.fuel_tracker.report.fuel_balance import fuel_balance

#: Litres carried over from the Fuel Balance report, summed per site.
LITRES = (
	"opening_balance",
	"litres_supplied",
	"transferred_in",
	"litres_dispensed",
	"litres_miscellaneous",
	"transferred_out",
	"litres_adjusted",
	"opening_entry",
	"current_balance",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.to_date = getdate(filters.get("to_date") or nowdate())
	filters.from_date = getdate(filters.get("from_date") or get_first_day(filters.to_date))

	_columns, balances = fuel_balance.execute(
		{
			"from_date": filters.from_date,
			"to_date": filters.to_date,
			"site": filters.get("site"),
			"fuel_tanker": filters.get("fuel_tanker"),
		}
	)
	if not balances:
		return get_columns([]), [], None, None, []

	names = [row["fuel_tanker"] for row in balances]
	days = date_diff(filters.to_date, filters.from_date) + 1
	activity = get_dispense_activity(names, filters)
	alerts = get_consumption_alerts(names, filters)
	outstanding = get_outstanding_requests(names, filters.to_date)

	tankers_by_site = {}
	for balance in balances:
		tanker = frappe._dict(balance)
		tanker.site = tanker.site or _("Not Set")
		used = activity.get(tanker.fuel_tanker, frappe._dict(fills=0, resources=set()))
		tanker.update(
			{
				"entity": tanker.fuel_tanker,
				"parent_entity": tanker.site,
				"indent": 1,
				"fills": used.fills,
				"resources": used.resources,
				"resources_fuelled": len(used.resources),
				"consumption_alerts": alerts.get(tanker.fuel_tanker, 0),
				"outstanding_requests": flt(outstanding.get(tanker.fuel_tanker), 2),
			}
		)
		set_stock_cover(tanker, days)
		tankers_by_site.setdefault(tanker.site, []).append(tanker)

	data, sites, tankers = [], [], []
	for site_name in sorted(tankers_by_site):
		site_tankers = sorted(tankers_by_site[site_name], key=lambda t: t.fuel_tanker)
		site = summarise_site(site_name, site_tankers, days)
		sites.append(site)
		tankers.extend(site_tankers)
		data.append(site)
		data.extend(site_tankers)

	for row in data:
		row.pop("resources", None)  # a set, used only to count distinct resources per site

	return get_columns(data), data, None, get_chart(sites), get_summary(tankers)


def summarise_site(site_name, tankers, days):
	"""A site row: its tankers added up, and the worst of their statuses."""
	site = frappe._dict(entity=site_name, parent_entity=None, indent=0, site=site_name)
	for field in LITRES + ("fills", "consumption_alerts", "outstanding_requests"):
		site[field] = flt(sum(flt(t.get(field)) for t in tankers), 2)
	site.fills = int(site.fills)
	site.consumption_alerts = int(site.consumption_alerts)
	site.resources_fuelled = len(set().union(*(t.resources for t in tankers)))
	set_stock_cover(site, days)

	severity = [_("Check Ledger"), _("Negative"), _("Low"), _("OK")]
	site.status = min((t.status for t in tankers), key=lambda s: severity.index(s) if s in severity else 0)
	needing = [t for t in tankers if t.status != _("OK")]
	if needing:
		site.status_note = _("{0} of {1} tankers need attention. Worst is {2}: {3}").format(
			len(needing), len(tankers), site.status, fuel_balance.status_note(site.status)
		)
	else:
		site.status_note = _("Every tanker at this site is positive and above its minimum level.")
	return site


def set_stock_cover(row, days):
	"""Average daily use over the period, and how many days the stock lasts at it.

	Use is fuel dispensed to resources plus Miscellaneous issues. Transfers are
	left out: fuel moved to another tanker has not been used, only relocated.
	Left blank rather than 0 when nothing was used or nothing is left, since
	"0 days of stock" would read as an emergency that is not there.
	"""
	used = flt(row.litres_dispensed) + flt(row.litres_miscellaneous)
	daily = used / days if days > 0 else 0
	row.avg_daily_use = flt(daily, 2)
	row.days_of_stock = flt(flt(row.current_balance) / daily, 2) if daily > 0 and flt(row.current_balance) > 0 else None


def get_dispense_activity(tankers, filters):
	"""Fills dispensed to resources in the period, and which resources, per tanker."""
	rows = frappe.db.sql(
		"""
		SELECT fuel_tanker, resource, COUNT(*) AS fills
		FROM `tabFuel Entry`
		WHERE docstatus = 1 AND utilization_type = 'Dispensed'
			AND fuel_tanker IN %(tankers)s
			AND date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY fuel_tanker, resource
		""",
		{"tankers": tuple(tankers), "from_date": filters.from_date, "to_date": filters.to_date},
		as_dict=True,
	)

	activity = {}
	for row in rows:
		tanker = activity.setdefault(row.fuel_tanker, frappe._dict(fills=0, resources=set()))
		tanker.fills += row.fills
		if row.resource:
			tanker.resources.add(row.resource)
	return activity


def get_consumption_alerts(tankers, filters):
	"""Fills in the period scored Warning or High Alert, per tanker that fuelled them.

	Read from the same scoring the consumption reports use, so the count here
	is exactly the number of alert rows the Consumption Ledger shows.
	"""
	alerting = {_("High Alert"), _("Warning")}
	wanted = set(tankers)
	counts = {}
	for fill in get_fills(to_date=filters.to_date):
		if (
			fill.fuel_tanker in wanted
			and fill.status in alerting
			and in_period(fill, filters.from_date, filters.to_date)
		):
			counts[fill.fuel_tanker] = counts.get(fill.fuel_tanker, 0) + 1
	return counts


def get_outstanding_requests(tankers, to_date):
	"""Litres still to be delivered on open supply requests raised by the period's end."""
	return dict(
		frappe.db.sql(
			"""
			SELECT fuel_tanker, SUM(pending_litres)
			FROM `tabFuel Supply Request`
			WHERE docstatus = 1 AND status IN ('Pending', 'Partially Supplied')
				AND fuel_tanker IN %(tankers)s AND date <= %(to_date)s
			GROUP BY fuel_tanker
			""",
			{"tankers": tuple(tankers), "to_date": to_date},
		)
	)


def get_summary(tankers):
	"""Headline cards: the company-wide position for the period."""

	def total(field):
		return sum(flt(t.get(field)) for t in tankers)

	def litres(label, value, indicator):
		# formatted here: summary cards ignore column precision, and the generic
		# Float formatter drops trailing zeros — fmt_money keeps two decimals
		return {"value": f"{fmt_money(flt(value, 2), precision=2)} L", "label": label, "datatype": "Data", "indicator": indicator}

	attention = sum(1 for t in tankers if t.status != _("OK"))
	alerts = int(total("consumption_alerts"))
	closing = total("current_balance")

	return [
		litres(_("Closing Balance"), closing, "Blue" if closing >= 0 else "Red"),
		litres(_("Supplied"), total("litres_supplied"), "Green"),
		litres(_("Dispensed to Resources"), total("litres_dispensed"), "Orange"),
		litres(_("Miscellaneous"), total("litres_miscellaneous"), "Orange"),
		litres(_("Transferred Out"), total("transferred_out"), "Blue"),
		litres(_("Net Adjustments"), total("litres_adjusted"), "Blue"),
		litres(_("Outstanding Requests"), total("outstanding_requests"), "Orange"),
		{
			"value": attention,
			"label": _("Tankers Needing Attention"),
			"datatype": "Int",
			"indicator": "Red" if attention else "Green",
		},
		{
			"value": alerts,
			"label": _("Consumption Alerts"),
			"datatype": "Int",
			"indicator": "Red" if alerts else "Green",
		},
	]


def get_chart(sites):
	"""Per site: fuel received, fuel used and what is left."""
	return {
		"data": {
			"labels": [site.entity for site in sites],
			"datasets": [
				{
					"name": _("Received"),
					"values": [flt(s.litres_supplied + s.transferred_in, 2) for s in sites],
				},
				{
					"name": _("Used"),
					"values": [flt(s.litres_dispensed + s.litres_miscellaneous, 2) for s in sites],
				},
				{"name": _("Closing Balance"), "values": [flt(s.current_balance, 2) for s in sites]},
			],
		},
		"type": "bar",
		"colors": ["#2ecc71", "#e17055", "#0984e3"],
	}


def get_columns(data):
	def litres(label, fieldname, width=130):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Float", "precision": 2, "width": width}

	columns = [
		{"label": _("Site / Tanker"), "fieldname": "entity", "fieldtype": "Data", "width": 260},
		litres(_("Opening Balance"), "opening_balance", 140),
		litres(_("Supplied"), "litres_supplied"),
		litres(_("Transferred In"), "transferred_in"),
		litres(_("Dispensed"), "litres_dispensed"),
		litres(_("Miscellaneous"), "litres_miscellaneous"),
		litres(_("Transferred Out"), "transferred_out"),
		litres(_("Adjusted"), "litres_adjusted", 110),
	]

	# Only worth a column when a tanker was actually opened inside the period.
	if any(row.get("opening_entry") for row in data):
		columns.append(litres(_("Opening Entry"), "opening_entry"))

	columns += [
		litres(_("Closing Balance"), "current_balance", 150),
		litres(_("Avg Daily Use"), "avg_daily_use"),
		litres(_("Days of Stock"), "days_of_stock", 120),
		{"label": _("Fills"), "fieldname": "fills", "fieldtype": "Int", "width": 80},
		{"label": _("Resources Fuelled"), "fieldname": "resources_fuelled", "fieldtype": "Int", "width": 140},
		{"label": _("Consumption Alerts"), "fieldname": "consumption_alerts", "fieldtype": "Int", "width": 150},
		litres(_("Outstanding Requests"), "outstanding_requests", 170),
		{"label": _("Stock Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{"label": _("What It Means"), "fieldname": "status_note", "fieldtype": "Data", "width": 420},
	]
	return columns
