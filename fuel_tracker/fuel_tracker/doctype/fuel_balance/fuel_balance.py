import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_datetime, getdate

from fuel_tracker.fuel_tracker.fuel_ledger import (
	OPENING_TYPE,
	get_first_movement_datetime,
	get_opening_datetime,
	make_posting_datetime,
)


class FuelBalance(Document):
	"""A tanker's opening balance — and, once submitted, its live balance.

	Submitting it seeds an Opening Balance entry at 00:00 on its date, and no
	fuel can move on the tanker until it is submitted (`validate_tanker_opened`).
	After that `sync_fuel_balance` keeps it pointed at the tail of the ledger.
	"""

	def validate(self):
		self.validate_opening_date()

	def on_submit(self):
		self.seed_opening_fuel_entry()

	def validate_opening_date(self):
		"""An opening must come before every movement already on the tanker.

		Normally the ledger is empty here, since nothing can be recorded on a
		tanker before its opening. Tankers that took movements before that rule
		existed can still be opened, as long as the opening is dated before
		their first movement: it is seeded there and every later entry
		re-prices from it. An opening dated after a movement would leave that
		movement priced against nothing, so it is refused.
		"""
		if not self.fuel_tanker:
			return

		first = get_first_movement_datetime(self.fuel_tanker)
		if not first:
			return

		opening = get_opening_datetime(self.fuel_tanker)
		if opening:
			frappe.throw(
				_("Tanker {0} already has an opening balance on {1}. Correct its stock with a Fuel Adjustment in Measured Balance mode instead.")
				.format(frappe.bold(self.fuel_tanker), frappe.format(getdate(opening), {"fieldtype": "Date"})),
				title=_("Already Opened"),
			)

		first = get_datetime(first)
		if make_posting_datetime(self.date, "00:00:00") < first:
			return

		# a draft created by a movement before the rule existed can still be
		# saved untouched; only a figure or date being entered is checked
		if self.docstatus == 0 and not (self.has_value_changed("balance") or self.has_value_changed("date")):
			return

		# the opening sits at 00:00 on its date, so it must fall on the day of
		# the first movement at the latest — or the day before, if that
		# movement was itself posted at midnight
		latest = first.date() if first > get_datetime(first.date()) else add_days(first.date(), -1)
		frappe.throw(
			_("Tanker {0} already has fuel movements from {1}, so its opening balance must be dated before them. Set the Date to {2} or earlier.")
			.format(
				frappe.bold(self.fuel_tanker),
				frappe.format(first, {"fieldtype": "Datetime"}),
				frappe.bold(frappe.format(getdate(latest), {"fieldtype": "Date"})),
			),
			title=_("Opening Must Come First"),
		)

	def on_cancel(self):
		self.block_if_active_ledger("cancelled")

	def on_trash(self):
		self.block_if_active_ledger("deleted")

	def block_if_active_ledger(self, action):
		"""Protect a balance whose tanker already has a submitted Fuel Entry.

		Once the ledger holds a submitted entry for this tanker, the balance is
		the anchor of that ledger and must not be cancelled or deleted. The
		Fuel Entry has to be cancelled first to release the balance.
		"""
		if not self.fuel_tanker:
			return

		if frappe.db.exists("Fuel Entry", {"fuel_tanker": self.fuel_tanker, "docstatus": 1}):
			frappe.throw(
				_("This Fuel Balance cannot be {0} because tanker {1} has a submitted Fuel Entry. Cancel the Fuel Entry first.")
				.format(action, frappe.bold(self.fuel_tanker))
			)

	def seed_opening_fuel_entry(self):
		"""Create the Opening Balance entry that anchors this tanker's ledger.

		It posts at 00:00:00 on its date, so anything else recorded that day
		sorts after it, and anything dated earlier is refused outright (see
		`validate_not_before_opening`). On a tanker that already has movements
		— dated after it, as `validate_opening_date` ensures — submitting the
		entry reposts them, so every later balance continues from the opening.
		A cancelled opening entry does not count, so a fresh balance can
		re-seed after one was cancelled.
		"""
		if not self.fuel_tanker or get_opening_datetime(self.fuel_tanker):
			return

		opening_entry = frappe.get_doc({
			"doctype": "Fuel Entry",
			"date": self.date,
			"posting_time": "00:00:00",
			"site": self.site,
			"fuel_tanker": self.fuel_tanker,
			"utilization_type": OPENING_TYPE,
			"previous_balance": 0,
			"current_balance": self.balance or 0,
		})
		opening_entry.flags.ignore_permissions = True
		opening_entry.flags.from_fuel_balance = True
		opening_entry.insert()
		opening_entry.submit()
