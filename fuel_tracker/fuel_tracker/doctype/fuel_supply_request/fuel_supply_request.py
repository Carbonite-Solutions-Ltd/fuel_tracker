# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, nowdate

from fuel_tracker.fuel_tracker.fuel_ledger import get_balance_as_of, make_posting_datetime


class FuelSupplyRequest(Document):
	"""The authorisation that must exist before fuel can be supplied.

	A request states how much fuel a tanker needs; the `Fuel Supplied`
	documents raised against it record how much actually arrived, which is
	often less (or arrives in several drops). The request therefore tracks its
	own fulfilment rather than assuming one request means one delivery — see
	:meth:`update_fulfilment`.

	This document touches no balances. Only the `Fuel Supplied` it spawns
	writes to the ledger.
	"""

	def validate(self):
		self.validate_quantity()
		self.set_site()
		self.set_balance_at_request()
		self.update_fulfilment(save=False)

	def before_submit(self):
		self.status = "Pending"

	def on_submit(self):
		self.update_fulfilment()

	def on_cancel(self):
		# Frappe's back-link check already refuses to cancel a request that a
		# submitted Fuel Supplied points at, so reaching here means nothing is
		# outstanding against it.
		self.db_set("status", "Cancelled")

	def validate_quantity(self):
		if flt(self.requested_litres) <= 0:
			frappe.throw(_("Requested (LTS) must be greater than zero."))

	def set_site(self):
		if not self.site and self.fuel_tanker:
			self.site = frappe.db.get_value("Fuel Tanker", self.fuel_tanker, "site")

	def set_balance_at_request(self):
		"""Record what the tanker held when the request was raised."""
		if self.docstatus == 0 and self.fuel_tanker:
			self.balance_at_request = get_balance_as_of(
				self.fuel_tanker, make_posting_datetime(self.date or nowdate())
			)

	def update_fulfilment(self, save=True):
		"""Roll up the submitted supplies raised against this request.

		Called from `Fuel Supplied` on both submit and cancel, so the status
		tracks reality in both directions: cancelling the only delivery puts a
		request back to Pending rather than leaving it falsely fulfilled.
		"""
		supplied = 0.0
		if not self.is_new():
			supplied = flt(
				frappe.db.get_value(
					"Fuel Supplied",
					{"fuel_supply_request": self.name, "docstatus": 1},
					"sum(fuel_supplied)",
				)
			)

		requested = flt(self.requested_litres)
		pending = max(requested - supplied, 0.0)
		status = self.derive_status(supplied, requested)

		if save and not self.is_new():
			# db_set rather than save(): the request is submitted by the time
			# supplies land against it, and fulfilment is derived state.
			self.db_set(
				{"supplied_litres": supplied, "pending_litres": pending, "status": status},
				update_modified=False,
			)
		else:
			self.supplied_litres = supplied
			self.pending_litres = pending
			self.status = status

	def derive_status(self, supplied, requested):
		if self.docstatus == 2:
			return "Cancelled"
		if self.docstatus == 0:
			return "Draft"
		if supplied <= 0:
			return "Pending"
		# Compared at 3 decimals so float noise on a matching delivery cannot
		# leave a request stuck one-millionth of a litre short.
		if flt(supplied, 3) >= flt(requested, 3):
			return "Fully Supplied"
		return "Partially Supplied"


@frappe.whitelist()
def make_fuel_supplied(source_name, target_doc=None):
	"""Build a Fuel Supplied from a request, defaulted to the pending litres.

	The quantity is only a default: the whole point of the request/supply
	split is that the actual litres delivered get keyed on the supply.
	"""
	def set_missing_values(source, target):
		target.fuel_supplied = flt(source.requested_litres) - flt(source.supplied_litres)
		target.date = nowdate()

	return get_mapped_doc(
		"Fuel Supply Request",
		source_name,
		{
			"Fuel Supply Request": {
				"doctype": "Fuel Supplied",
				"field_map": {
					"name": "fuel_supply_request",
					"fuel_tanker": "fuel_tanker",
					"site": "site",
					"supplier": "supplier",
					"requested_litres": "requested_litres",
				},
				"validation": {"docstatus": ["=", 1]},
			}
		},
		target_doc,
		set_missing_values,
	)
