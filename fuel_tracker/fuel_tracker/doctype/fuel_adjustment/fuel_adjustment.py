import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import (
	ensure_posting_time,
	get_balance_as_of,
	get_or_create_fuel_balance,
	warn_if_above_threshold,
	warn_if_below_minimum,
	warn_if_ledger_goes_negative,
)


class FuelAdjustment(Document):
	"""Stock correction for a tanker (dip-count variance, spillage, theft, ...).

	On submit this creates a Fuel Entry with utilization_type="Adjustment"
	carrying the signed adjustment_litres, so the correction flows through the
	ledger like every other movement. Cancellation goes through the Fuel Entry
	(its cascade cancels this document); a submitted adjustment cannot be
	cancelled directly because the Fuel Entry links back to it.

	Note: a submitted adjustment counts as an active Fuel Entry for the tanker,
	so it forfeits later Opening Balance seeding — same as Supplied/Dispensed
	entries. A Measured Balance adjustment captures true stock anyway.
	"""

	def validate(self):
		ensure_posting_time(self)

	def before_submit(self):
		# Stamp the posting time now unless the user asked to backdate. This is
		# what makes a stale Measured Balance draft compare against the stock
		# at submission rather than at the moment it was drafted.
		ensure_posting_time(self, refresh=True)
		self.validate_reason_remarks()
		self.sync_system_balance_and_compute_adjustment()
		self.validate_nonzero_adjustment()

	def on_submit(self):
		posting_datetime = ensure_posting_time(self)
		adjustment = flt(self.adjustment_litres)

		get_or_create_fuel_balance(self.fuel_tanker, self.site, self.date)
		warn_if_ledger_goes_negative(
			self.fuel_tanker, posting_datetime, adjustment, source_label=_("This adjustment")
		)
		warn_if_above_threshold(self.fuel_tanker, posting_datetime, adjustment)
		warn_if_below_minimum(self.fuel_tanker, posting_datetime, adjustment)

		self.create_fuel_entry()

	def validate_reason_remarks(self):
		if self.reason == "Other" and not (self.remarks or "").strip():
			frappe.throw(_("Remarks are required when the reason is Other."))

	def sync_system_balance_and_compute_adjustment(self):
		"""Refresh the system balance from the ledger, then compute.

		The balance is read *as at the adjustment's posting moment*, not as it
		stands today. That is what makes a backdated dip count work: measuring
		1,000 L on the 3rd is compared against what the ledger says the tanker
		held on the 3rd, and every entry recorded after it is then reposted on
		top of the correction.

		A draft can also sit for a while before submission, so the balance
		captured while drafting may be stale; the ledger is authoritative at
		submit time. A tanker with no ledger history yet reads 0.
		"""
		if not self.site:
			self.site = frappe.db.get_value("Fuel Tanker", self.fuel_tanker, "site")

		self.system_balance = get_balance_as_of(self.fuel_tanker, ensure_posting_time(self))

		# Round to 3 decimals so float noise (e.g. measured == system apart
		# from 1e-13) cannot produce phantom adjustments or dodge the zero check.
		if self.adjustment_mode == "Measured Balance":
			self.adjustment_litres = flt(flt(self.measured_balance) - self.system_balance, 3)
		elif self.adjustment_mode == "Quantity":
			self.adjustment_litres = flt(self.quantity, 3)
		else:
			frappe.throw(_("Invalid adjustment mode: {0}").format(self.adjustment_mode))

	def validate_nonzero_adjustment(self):
		if not self.adjustment_litres:
			if self.adjustment_mode == "Measured Balance":
				frappe.throw(_("The measured balance equals the system balance; there is nothing to adjust."))
			frappe.throw(_("Adjustment Quantity (L) cannot be zero."))

	def create_fuel_entry(self):
		fuel_entry = frappe.get_doc({
			"doctype": "Fuel Entry",
			"date": self.date,
			"posting_time": self.posting_time,
			"fuel_tanker": self.fuel_tanker,
			"site": self.site,
			"utilization_type": "Adjustment",
			"litres_adjusted": self.adjustment_litres,
			"fuel_adjustment_id": self.name,
		})
		fuel_entry.flags.ignore_permissions = True
		fuel_entry.insert()
		fuel_entry.submit()
