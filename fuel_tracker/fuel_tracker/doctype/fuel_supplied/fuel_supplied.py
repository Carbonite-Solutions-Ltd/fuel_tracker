import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import (
	ensure_posting_time,
	get_or_create_fuel_balance,
	warn_if_above_threshold,
)


class FuelSupplied(Document):
	"""Fuel arriving into a tanker, always against an approved supply request.

	Balances are not computed here: the `Fuel Entry` this creates prices
	itself against the ledger at its own posting moment, so a backdated
	supply lands in the right place in history.
	"""

	def validate(self):
		ensure_posting_time(self)

	def before_submit(self):
		# Stamp the posting time now unless the user asked to backdate, so a
		# draft left sitting cannot post behind entries recorded since.
		ensure_posting_time(self, refresh=True)
		self.validate_fuel_quantity()
		self.validate_request()

	def on_submit(self):
		# Create the balance row up front so a tanker touched for the first
		# time has somewhere for the ledger tail to be written back to.
		get_or_create_fuel_balance(self.fuel_tanker, self.site, self.date)
		warn_if_above_threshold(self.fuel_tanker, ensure_posting_time(self), flt(self.fuel_supplied))
		self.create_fuel_entry()
		self.update_request_status()

	def on_cancel(self):
		self.update_request_status()

	def validate_fuel_quantity(self):
		if flt(self.fuel_supplied) <= 0:
			frappe.throw(_("Fuel Supplied (LTS) must be greater than zero."))

	def validate_request(self):
		"""Every supply answers a request, and must match its tanker.

		The link is mandatory on the field, so this guards the pairing rather
		than the presence: a supply booked against another tanker's request
		would credit the wrong bowser.
		"""
		if not self.fuel_supply_request:
			frappe.throw(_("A Fuel Supply Request is required before fuel can be supplied."))

		request = frappe.db.get_value(
			"Fuel Supply Request",
			self.fuel_supply_request,
			["docstatus", "fuel_tanker", "status"],
			as_dict=True,
		)

		if request.docstatus != 1:
			frappe.throw(
				_("Fuel Supply Request {0} is not submitted.").format(frappe.bold(self.fuel_supply_request))
			)
		if request.status == "Cancelled":
			frappe.throw(
				_("Fuel Supply Request {0} has been cancelled.").format(frappe.bold(self.fuel_supply_request))
			)
		if request.fuel_tanker != self.fuel_tanker:
			frappe.throw(
				_("Fuel Supply Request {0} is for tanker {1}, not {2}.")
				.format(frappe.bold(self.fuel_supply_request), frappe.bold(request.fuel_tanker), frappe.bold(self.fuel_tanker))
			)

	def create_fuel_entry(self):
		fuel_entry = frappe.get_doc({
			"doctype": "Fuel Entry",
			"date": self.date,
			"posting_time": self.posting_time,
			"fuel_tanker": self.fuel_tanker,
			"site": self.site,
			"utilization_type": "Supplied",
			"litres_supplied": self.fuel_supplied,
			"fuel_supplied_id": self.name,
		})
		fuel_entry.flags.ignore_permissions = True
		fuel_entry.insert()
		fuel_entry.submit()

	def update_request_status(self):
		if self.fuel_supply_request:
			frappe.get_doc("Fuel Supply Request", self.fuel_supply_request).update_fulfilment()
