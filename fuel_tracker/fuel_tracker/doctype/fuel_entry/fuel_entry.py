import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import (
	ensure_posting_time,
	entry_delta,
	get_balance_as_of,
	repost_tanker,
	validate_not_before_opening,
)


class FuelEntry(Document):
	"""The immutable ledger line for one fuel movement.

	Balance figures on an entry are *derived*: `previous_balance` is whatever
	the tanker held immediately before this entry's posting moment, and
	`current_balance` is that plus this entry's signed movement. Because an
	entry can be posted into the middle of the history, submitting or
	cancelling one reposts every entry after it — see `fuel_ledger`.
	"""

	def validate(self):
		self.set_posting_datetime()

	def before_submit(self):
		validate_not_before_opening(self.fuel_tanker, self.posting_datetime)
		self.set_balances()

	def on_submit(self):
		# Repost from this entry's own moment: the walk re-derives this entry
		# too and then continues through everything already recorded after it,
		# which is what makes a backdated entry slot into the history cleanly.
		repost_tanker(self.fuel_tanker, self.posting_datetime)

	def on_cancel(self):
		self.cancel_linked_document()
		# The row is already docstatus 2 by the time on_cancel runs, so the
		# repost simply walks the ledger without it.
		repost_tanker(self.fuel_tanker, self.posting_datetime)
		self.update_resource_usage_on_cancel()

	def set_posting_datetime(self):
		"""Derive the ledger sort key from the posting date and time."""
		self.posting_datetime = ensure_posting_time(self)

	def set_balances(self):
		"""Price this entry against the balance at its posting moment.

		Reading the ledger rather than the live `Fuel Balance` is what makes a
		backdated entry correct: it sees the tanker as it stood on its own
		date, not as it stands today.
		"""
		if self.utilization_type == "Opening Balance":
			# The opening entry *is* the balance at that moment; current_balance
			# carries the entered figure and must not be recomputed.
			self.previous_balance = 0
			return

		self.previous_balance = get_balance_as_of(
			self.fuel_tanker, self.posting_datetime, exclude=self.name
		)
		self.current_balance = flt(self.previous_balance + entry_delta(self), 3)

	def cancel_linked_document(self):
		"""Cancel the source document this entry was created from.

		Cancellation is driven from the ledger, so cancelling an entry unwinds
		the document that produced it. A transfer produces two entries and
		cancelling either one cancels the transfer, which in turn cancels the
		sibling entry — the docstatus checks keep that cascade from looping.
		"""
		linked = {
			"Supplied": ("Fuel Supplied", self.fuel_supplied_id),
			"Dispensed": ("Fuel Used", self.fuel_utilization_id),
			"Adjustment": ("Fuel Adjustment", self.fuel_adjustment_id),
			"Transfer In": ("Fuel Transfer", self.fuel_transfer_id),
			"Transfer Out": ("Fuel Transfer", self.fuel_transfer_id),
		}.get(self.utilization_type)

		if not linked:
			return

		linked_doctype, linked_docname = linked
		if not linked_docname:
			return

		linked_doc = frappe.get_doc(linked_doctype, linked_docname)

		# No commit here: the whole cancel (this cascade, the repost and the
		# resource restore) must stay one transaction, or a failure partway
		# leaves the ledger and balance diverged.
		if linked_doc.docstatus == 1:
			linked_doc.flags.from_fuel_entry_cancel = True
			linked_doc.cancel()

	def update_resource_usage_on_cancel(self):
		"""Restore the resource's odometer/hours after this entry is cancelled.

		The reading is recomputed from the remaining submitted Fuel Used
		documents for the resource rather than blindly restored from the
		cancelled document, so cancelling a mid-history entry cannot drag
		the reading backwards past later, still-submitted readings. The
		cancelled document's previous reading is only used when no other
		submitted Fuel Used remains.
		"""
		if not (self.utilization_type == "Dispensed" and self.fuel_utilization_id):
			return

		fuel_used_doc = frappe.get_doc("Fuel Used", self.fuel_utilization_id)
		resource = frappe.get_doc("Resource", fuel_used_doc.resource)

		if resource.resource_type == "Truck":
			reading_field, resource_field = "odometer_km", "current_odometer"
			fallback = fuel_used_doc.previous_odometer_km
		elif resource.resource_type == "Equipment":
			reading_field, resource_field = "hours_copy", "current_hours"
			fallback = fuel_used_doc.previous_hours_copy
		else:
			return

		remaining_readings = frappe.get_all(
			"Fuel Used",
			filters={
				"resource": fuel_used_doc.resource,
				"docstatus": 1,
				"name": ["!=", fuel_used_doc.name],
			},
			pluck=reading_field,
		)
		remaining_readings = [flt(r) for r in remaining_readings if r is not None]

		if not remaining_readings and not flt(fallback):
			# Nothing left to restore from: the resource was dispensed to with
			# a faulty meter throughout, so there is no reading to hold.
			return

		setattr(resource, resource_field, max(remaining_readings) if remaining_readings else flt(fallback))
		# readings are locked against manual edits; fuel flows are exempt
		resource.flags.from_fuel_transaction = True
		resource.save()
