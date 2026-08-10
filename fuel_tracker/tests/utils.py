"""Shared helpers for fuel_tracker tests.

All helpers are idempotent where sensible and use TEST-FT-* names so test
data is recognisable. FrappeTestCase rolls the DB back at class teardown,
so nothing here needs explicit cleanup — but names must not collide with
records a class created earlier in the same run, so give each test its own
tanker/resource names.
"""

import frappe
from frappe.utils import flt, today


def ensure_company():
	"""Return an existing Company, creating a minimal one only if none exists.

	In CI, erpnext's before_tests hook completes the setup wizard and creates
	a company with a full chart of accounts; on dev sites real companies
	exist. The fallback covers bare sites.
	"""
	companies = frappe.get_all("Company", limit=1, pluck="name")
	if companies:
		return companies[0]

	company = frappe.get_doc({
		"doctype": "Company",
		"company_name": "TEST-FT Company",
		"abbr": "TFC",
		"default_currency": "USD",
		"country": "United States",
	})
	company.insert()
	return company.name


def ensure_site(name="TEST-FT-SITE"):
	if not frappe.db.exists("Site", name):
		frappe.get_doc({"doctype": "Site", "site_name": name}).insert()
	return name


def make_tanker(name, site=None, threshold=0, minimum_level=0):
	"""Create a Fuel Tanker via the new-tanker flow (auto-creates the Item)."""
	ensure_company()  # tanker item auto-create needs a company for the asset category
	site = site or ensure_site()
	if frappe.db.exists("Fuel Tanker", name):
		return frappe.get_doc("Fuel Tanker", name)

	doc = frappe.get_doc({
		"doctype": "Fuel Tanker",
		"is_new_tanker": 1,
		"new_tanker_name": name,
		"site": site,
		"tanker_threshold": threshold,
		"minimum_level": minimum_level,
	})
	doc.insert()
	return doc


def make_resource(chassis, resource_type, reading=0, average_consumption=0, has_faulty_meter=0):
	if frappe.db.exists("Resource", chassis):
		return frappe.get_doc("Resource", chassis)

	fields = {
		"doctype": "Resource",
		"chassis_number": chassis,
		"resource_type": resource_type,
		"average_consumption": average_consumption,
		"has_faulty_meter": has_faulty_meter,
		"faulty_meter_remarks": "Meter broken" if has_faulty_meter else None,
	}
	if resource_type == "Truck":
		fields["current_odometer"] = reading
	else:
		fields["current_hours"] = reading

	doc = frappe.get_doc(fields)
	doc.insert()
	return doc


def request_supply(tanker, litres, date=None, submit=True):
	"""Raise the Fuel Supply Request that every supply has to answer."""
	doc = frappe.get_doc({
		"doctype": "Fuel Supply Request",
		"date": date or today(),
		"fuel_tanker": tanker,
		"requested_litres": litres,
		"reason": "Routine Replenishment",
	})
	doc.insert()
	if submit:
		doc.submit()
	return doc


def supply(tanker, litres, date=None, posting_time=None, request=None, submit=True):
	"""Supply fuel into a tanker, raising a matching request unless one is given."""
	if request is None:
		request = request_supply(tanker, litres, date=date).name

	doc = frappe.get_doc({
		"doctype": "Fuel Supplied",
		"date": date or today(),
		"posting_time": posting_time,
		"set_posting_time": 1 if posting_time else 0,
		"fuel_tanker": tanker,
		"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		"fuel_supplied": litres,
		"fuel_supply_request": request,
	})
	doc.insert()
	if submit:
		doc.submit()
	return doc


def dispense(tanker, resource, litres, odometer_km=None, hours_copy=None,
		date=None, posting_time=None, submit=True):
	payload = {
		"doctype": "Fuel Used",
		"date": date or today(),
		"posting_time": posting_time,
		"set_posting_time": 1 if posting_time else 0,
		"fuel_tanker": tanker,
		"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		"resource": resource,
		"fuel_issued_lts": litres,
	}
	if odometer_km is not None:
		payload["odometer_km"] = odometer_km
	if hours_copy is not None:
		payload["hours_copy"] = hours_copy

	doc = frappe.get_doc(payload)
	doc.insert()
	if submit:
		doc.submit()
	return doc


def adjust(tanker, mode="Quantity", measured=None, quantity=None,
		reason="Physical Count Variance", remarks=None,
		date=None, posting_time=None, submit=True):
	doc = frappe.get_doc({
		"doctype": "Fuel Adjustment",
		"date": date or today(),
		"posting_time": posting_time,
		"set_posting_time": 1 if posting_time else 0,
		"fuel_tanker": tanker,
		"adjustment_mode": mode,
		"measured_balance": measured,
		"quantity": quantity,
		"reason": reason,
		"remarks": remarks,
	})
	doc.insert()
	if submit:
		doc.submit()
	return doc


def transfer(from_tanker, to_tanker, litres, date=None, posting_time=None, submit=True):
	doc = frappe.get_doc({
		"doctype": "Fuel Transfer",
		"date": date or today(),
		"posting_time": posting_time,
		"set_posting_time": 1 if posting_time else 0,
		"from_tanker": from_tanker,
		"to_tanker": to_tanker,
		"litres_transferred": litres,
	})
	doc.insert()
	if submit:
		doc.submit()
	return doc


def balance(tanker):
	"""The tanker's live balance — the tail of its ledger."""
	return flt(frappe.db.get_value("Fuel Balance", tanker, "balance"))


def balance_on(tanker, date, posting_time="23:59:59"):
	"""The tanker's balance as at a past date, read from the ledger."""
	from fuel_tracker.fuel_tracker.fuel_ledger import get_balance_as_of, make_posting_datetime

	return get_balance_as_of(tanker, make_posting_datetime(date, posting_time))


LINK_FIELDS = {
	"Fuel Supplied": "fuel_supplied_id",
	"Fuel Used": "fuel_utilization_id",
	"Fuel Adjustment": "fuel_adjustment_id",
	"Fuel Transfer": "fuel_transfer_id",
}


def entries_for(doc, docstatus=1):
	"""Fuel Entries created by a source document, in ledger order.

	A Fuel Transfer produces two (one per tanker); everything else produces one.
	"""
	names = frappe.get_all(
		"Fuel Entry",
		filters={LINK_FIELDS[doc.doctype]: doc.name, "docstatus": docstatus},
		order_by="posting_datetime asc, creation asc",
		pluck="name",
	)
	return [frappe.get_doc("Fuel Entry", n) for n in names]


def entry_for(doc, docstatus=1):
	"""Return the Fuel Entry created by a source document (or None)."""
	entries = entries_for(doc, docstatus)
	return entries[0] if entries else None


def messages_text():
	return " | ".join(str(m) for m in (frappe.local.message_log or []))
