# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from fuel_tracker.fuel_tracker.doctype.fuel_supply_request.fuel_supply_request import make_fuel_supplied
from fuel_tracker.tests.utils import balance, entry_for, make_tanker, request_supply, supply

test_ignore = ["Item", "Company"]


class TestFuelSupplyRequest(FrappeTestCase):
	def test_supply_without_a_request_is_blocked(self):
		tanker = make_tanker("TEST-FT-REQ-1").name

		doc = frappe.get_doc({
			"doctype": "Fuel Supplied",
			"date": frappe.utils.today(),
			"fuel_tanker": tanker,
			"site": frappe.db.get_value("Fuel Tanker", tanker, "site"),
			"fuel_supplied": 500,
		})
		with self.assertRaises(frappe.MandatoryError):
			doc.insert()

		self.assertEqual(balance(tanker), 0)

	def test_request_starts_pending_and_becomes_fully_supplied(self):
		tanker = make_tanker("TEST-FT-REQ-2").name
		request = request_supply(tanker, 500)
		request.reload()
		self.assertEqual(request.status, "Pending")
		self.assertEqual(request.pending_litres, 500)

		supply(tanker, 500, request=request.name)
		request.reload()

		self.assertEqual(request.status, "Fully Supplied")
		self.assertEqual(request.supplied_litres, 500)
		self.assertEqual(request.pending_litres, 0)
		self.assertEqual(balance(tanker), 500)

	def test_partial_delivery_tracks_the_outstanding_litres(self):
		tanker = make_tanker("TEST-FT-REQ-3").name
		request = request_supply(tanker, 1000)

		supply(tanker, 400, request=request.name)
		request.reload()
		self.assertEqual(request.status, "Partially Supplied")
		self.assertEqual(request.supplied_litres, 400)
		self.assertEqual(request.pending_litres, 600)

		# a second drop against the same request closes it out
		supply(tanker, 600, request=request.name)
		request.reload()
		self.assertEqual(request.status, "Fully Supplied")
		self.assertEqual(request.pending_litres, 0)
		self.assertEqual(balance(tanker), 1000)

	def test_actual_litres_may_differ_from_the_request(self):
		"""The request is an ask; the supply records what actually arrived."""
		tanker = make_tanker("TEST-FT-REQ-4").name
		request = request_supply(tanker, 1000)

		doc = supply(tanker, 940, request=request.name)
		request.reload()

		self.assertEqual(doc.fuel_supplied, 940)
		self.assertEqual(request.supplied_litres, 940)
		self.assertEqual(request.status, "Partially Supplied")
		self.assertEqual(balance(tanker), 940)

	def test_cancelling_the_supply_reopens_the_request(self):
		tanker = make_tanker("TEST-FT-REQ-5").name
		request = request_supply(tanker, 500)
		doc = supply(tanker, 500, request=request.name)
		request.reload()
		self.assertEqual(request.status, "Fully Supplied")

		entry_for(doc).cancel()
		request.reload()

		self.assertEqual(request.status, "Pending")
		self.assertEqual(request.supplied_litres, 0)
		self.assertEqual(request.pending_litres, 500)
		self.assertEqual(balance(tanker), 0)

	def test_request_for_another_tanker_is_rejected(self):
		tanker_a = make_tanker("TEST-FT-REQ-6A").name
		tanker_b = make_tanker("TEST-FT-REQ-6B").name
		request = request_supply(tanker_a, 500)

		with self.assertRaises(frappe.ValidationError):
			supply(tanker_b, 500, request=request.name)

		self.assertEqual(balance(tanker_b), 0)

	def test_draft_request_cannot_be_supplied_against(self):
		tanker = make_tanker("TEST-FT-REQ-7").name
		request = request_supply(tanker, 500, submit=False)

		with self.assertRaises(frappe.ValidationError):
			supply(tanker, 500, request=request.name)

	def test_zero_and_negative_requests_blocked(self):
		tanker = make_tanker("TEST-FT-REQ-8").name

		with self.assertRaises(frappe.ValidationError):
			request_supply(tanker, 0)
		with self.assertRaises(frappe.ValidationError):
			request_supply(tanker, -100)

	def test_mapper_prefills_the_supply_from_the_request(self):
		tanker = make_tanker("TEST-FT-REQ-9").name
		request = request_supply(tanker, 800)
		supply(tanker, 300, request=request.name)
		request.reload()

		target = make_fuel_supplied(request.name)

		self.assertEqual(target.fuel_supply_request, request.name)
		self.assertEqual(target.fuel_tanker, tanker)
		# defaults to what is still outstanding, editable before submit
		self.assertEqual(target.fuel_supplied, 500)

	def test_request_with_a_submitted_supply_cannot_be_cancelled(self):
		tanker = make_tanker("TEST-FT-REQ-10").name
		request = request_supply(tanker, 500)
		supply(tanker, 500, request=request.name)

		with self.assertRaises(frappe.LinkExistsError):
			request.reload()
			request.cancel()
