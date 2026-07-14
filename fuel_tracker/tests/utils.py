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


def make_resource(chassis, resource_type, reading=0, average_consumption=0):
	if frappe.db.exists("Resource", chassis):
		return frappe.get_doc("Resource", chassis)

	fields = {
		"doctype": "Resource",
		"chassis_number": chassis,
		"resource_type": resource_type,
		"average_consumption": average_consumption,
	}
	if resource_type == "Truck":
		fields["current_odometer"] = reading
	else:
		fields["current_hours"] = reading

	doc = frappe.get_doc(fields)
	doc.insert()
	return doc


def supply(tanker, litres, submit=True):
	doc = frappe.get_doc({
		"doctype": "Fuel Supplied",
		"date": today(),
		"fuel_tanker": tanker,
		"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
		"fuel_supplied": litres,
	})
	doc.insert()
	if submit:
		doc.submit()
	return doc


def dispense(tanker, resource, litres, odometer_km=None, hours_copy=None, submit=True):
	payload = {
		"doctype": "Fuel Used",
		"date": today(),
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
		reason="Physical Count Variance", remarks=None, submit=True):
	doc = frappe.get_doc({
		"doctype": "Fuel Adjustment",
		"date": today(),
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


def balance(tanker):
	return flt(frappe.db.get_value("Fuel Balance", tanker, "balance"))


def entry_for(doc, docstatus=1):
	"""Return the Fuel Entry created by a source document (or None)."""
	link_field = {
		"Fuel Supplied": "fuel_supplied_id",
		"Fuel Used": "fuel_utilization_id",
		"Fuel Adjustment": "fuel_adjustment_id",
	}[doc.doctype]
	names = frappe.get_all("Fuel Entry", filters={link_field: doc.name, "docstatus": docstatus}, pluck="name")
	return frappe.get_doc("Fuel Entry", names[0]) if names else None


def messages_text():
	return " | ".join(str(m) for m in (frappe.local.message_log or []))
