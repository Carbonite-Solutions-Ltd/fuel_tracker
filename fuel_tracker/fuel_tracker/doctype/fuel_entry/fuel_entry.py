import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import (
	MISCELLANEOUS_TYPE,
	OPENING_TYPE,
	ensure_posting_time,
	entry_delta,
	get_balance_as_of,
	repost_tanker,
	validate_not_before_opening,
	validate_not_future_dated,
)
from fuel_tracker.fuel_tracker.resource_ledger import repost_resource_readings

#: Every movement type, and the link to the source document it must come from.
SOURCE_LINKS = {
	"Supplied": ("Fuel Supplied", "fuel_supplied_id"),
	"Dispensed": ("Fuel Used", "fuel_utilization_id"),
	MISCELLANEOUS_TYPE: ("Fuel Used", "fuel_utilization_id"),
	"Adjustment": ("Fuel Adjustment", "fuel_adjustment_id"),
	"Transfer In": ("Fuel Transfer", "fuel_transfer_id"),
	"Transfer Out": ("Fuel Transfer", "fuel_transfer_id"),
}


class FuelEntry(Document):
	"""The immutable ledger line for one fuel movement.

	Balance figures on an entry are *derived*: `previous_balance` is whatever
	the tanker held immediately before this entry's posting moment, and
	`current_balance` is that plus this entry's signed movement. Because an
	entry can be posted into the middle of the history, submitting or
	cancelling one reposts every entry after it — see `fuel_ledger`.
	"""

	def validate(self):
		self.validate_source()
		self.set_posting_datetime()

	def validate_source(self):
		"""Only the source documents may write to the ledger.

		A hand-made entry with a mistyped type moved the balance by nothing,
		and one with a valid type added or removed fuel with no document to
		account for it. Each movement must carry the link to the document that
		produced it; an opening balance must come from a Fuel Balance.
		"""
		if self.utilization_type == OPENING_TYPE:
			if self.is_new() and not self.flags.from_fuel_balance:
				frappe.throw(_("An Opening Balance entry is created by submitting the tanker's Fuel Balance."))
			return

		source = SOURCE_LINKS.get(self.utilization_type)
		if not source:
			frappe.throw(_("Unknown utilization type {0}.").format(frappe.bold(self.utilization_type or _("(blank)"))))

		source_doctype, link_field = source
		if not self.get(link_field):
			frappe.throw(
				_("A {0} entry must be created from its {1}. Record the movement there instead of in the ledger directly.")
				.format(self.utilization_type, source_doctype)
			)

	def before_submit(self):
		validate_not_future_dated(self.date)
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
		source = SOURCE_LINKS.get(self.utilization_type)
		if not source:
			return

		linked_doctype, link_field = source
		linked_docname = self.get(link_field)
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
		"""Repost the resource's reading sequence after this entry is cancelled.

		The cancelled document drops out of the sequence, so every fill after
		it is measured from a new starting point and the resource falls back to
		the newest reading that remains. Reposting handles a mid-history cancel
		as naturally as a cancel of the latest fill, and cannot drag the
		reading backwards past readings that are still submitted.
		"""
		if not (self.utilization_type == "Dispensed" and self.fuel_utilization_id):
			return

		resource, resource_type = frappe.db.get_value(
			"Fuel Used", self.fuel_utilization_id, ["resource", "resource_type"]
		)
		repost_resource_readings(resource, resource_type, self.posting_datetime)
