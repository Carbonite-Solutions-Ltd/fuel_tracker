# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import (
	ensure_posting_time,
	get_balance_as_of,
	get_or_create_fuel_balance,
	validate_not_future_dated,
	warn_if_above_threshold,
	warn_if_below_minimum,
	warn_if_ledger_goes_negative,
)


class FuelTransfer(Document):
	"""Fuel moved from one tanker to another, typically across sites.

	Balances live on tankers, not sites, so a site-to-site movement is a
	tanker-to-tanker movement whose two tankers happen to sit on different
	sites. One transfer therefore produces *two* ledger entries: a
	`Transfer Out` that debits the source tanker and a `Transfer In` that
	credits the destination. Both carry the same posting moment and both link
	back here, which keeps the two sides inseparable — cancelling either entry
	cancels this transfer, which cancels the other entry.
	"""

	def validate(self):
		validate_not_future_dated(self.date)
		ensure_posting_time(self)
		self.validate_route()
		self.validate_quantity()
		self.set_balances()

	def before_submit(self):
		# Stamp the posting time now unless the user asked to backdate, so a
		# draft left sitting cannot post behind entries recorded since.
		ensure_posting_time(self, refresh=True)

	def on_submit(self):
		posting_datetime = ensure_posting_time(self)
		litres = flt(self.litres_transferred)

		get_or_create_fuel_balance(self.from_tanker, self.from_site, self.date)
		get_or_create_fuel_balance(self.to_tanker, self.to_site, self.date)

		warn_if_ledger_goes_negative(
			self.from_tanker,
			posting_datetime,
			-litres,
			source_label=_("Transferring out {0} L").format(litres),
		)
		warn_if_below_minimum(self.from_tanker, posting_datetime, -litres)
		warn_if_above_threshold(self.to_tanker, posting_datetime, litres)

		self.create_fuel_entries()

	def on_cancel(self):
		self.cancel_fuel_entries()

	def validate_route(self):
		if not (self.from_tanker and self.to_tanker):
			return

		if self.from_tanker == self.to_tanker:
			frappe.throw(
				_("A transfer must move fuel between two different tankers. Use a Fuel Adjustment to correct a single tanker's stock.")
			)

		# The link fetches populate these in the desk form; fill them in for
		# documents built by the API or a script too.
		if not self.from_site:
			self.from_site = frappe.db.get_value("Fuel Tanker", self.from_tanker, "site")
		if not self.to_site:
			self.to_site = frappe.db.get_value("Fuel Tanker", self.to_tanker, "site")

	def validate_quantity(self):
		if flt(self.litres_transferred) <= 0:
			frappe.throw(_("Litres Transferred must be greater than zero."))

	def set_balances(self):
		"""Show both tankers as they stand at this transfer's posting moment.

		Informational only — the ledger entries price themselves — but it lets
		someone keying a backdated transfer see the balances that actually
		applied on that date rather than today's figures.
		"""
		posting_datetime = ensure_posting_time(self)
		self.from_balance = get_balance_as_of(self.from_tanker, posting_datetime)
		self.to_balance = get_balance_as_of(self.to_tanker, posting_datetime)

	def create_fuel_entries(self):
		"""Write the two legs of the transfer to the ledger.

		Litres are recorded in the same columns the rest of the ledger uses
		(`litres_dispensed` out, `litres_supplied` in) so existing reports and
		totals pick transfers up without special-casing them.
		"""
		legs = (
			{
				"fuel_tanker": self.from_tanker,
				"site": self.from_site,
				"utilization_type": "Transfer Out",
				"litres_dispensed": self.litres_transferred,
			},
			{
				"fuel_tanker": self.to_tanker,
				"site": self.to_site,
				"utilization_type": "Transfer In",
				"litres_supplied": self.litres_transferred,
			},
		)

		for leg in legs:
			entry = frappe.get_doc({
				"doctype": "Fuel Entry",
				"date": self.date,
				"posting_time": self.posting_time,
				"fuel_transfer_id": self.name,
				**leg,
			})
			entry.flags.ignore_permissions = True
			entry.insert()
			entry.submit()

	def cancel_fuel_entries(self):
		"""Cancel both legs so a transfer can never be half-unwound.

		Reached either directly or via the cascade from one leg's own
		cancellation; the already-cancelled leg is simply skipped, which stops
		the two documents bouncing the cancel back and forth.
		"""
		entries = frappe.get_all(
			"Fuel Entry",
			filters={"fuel_transfer_id": self.name, "docstatus": 1},
			pluck="name",
		)

		for name in entries:
			entry = frappe.get_doc("Fuel Entry", name)
			# No commit here: both legs and both reposts must land in one
			# transaction, or one site's balance moves without the other's.
			entry.cancel()
