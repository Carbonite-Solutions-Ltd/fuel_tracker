import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import PRECISION, get_balance_as_of


class FuelBalance(Document):
	def validate(self):
		# Runs on save and on submit: a typed figure left on the draft would
		# show as the tanker's balance while the ledger says otherwise.
		self.refuse_opening_behind_movements()

	def on_submit(self):
		self.seed_opening_fuel_entry()

	def refuse_opening_behind_movements(self):
		"""Do not silently discard an opening figure the ledger cannot take.

		The draft row is created by a tanker's first movement and tracks the
		ledger from then on, so submitting it untouched is fine — there is
		nothing to seed. But a figure typed into it after movements exist
		used to vanish without a word: the opening entry is only seeded on an
		empty ledger, so the tanker carried on from zero and went negative.
		Refuse instead, and point at the tool that does work on a live ledger.
		"""
		if not self.fuel_tanker or not self.has_active_ledger():
			return

		if flt(self.balance, PRECISION) == flt(get_balance_as_of(self.fuel_tanker), PRECISION):
			return

		frappe.throw(
			_("Tanker {0} already has fuel movements, so {1} L cannot be applied as its opening balance. To set the stock it held, submit a Fuel Adjustment in Measured Balance mode, dated when the tank was counted — it may be dated before the first movement.")
			.format(frappe.bold(self.fuel_tanker), flt(self.balance, PRECISION)),
			title=_("Ledger Already Started"),
		)

	def has_active_ledger(self):
		# Cancelled Fuel Entries (docstatus 2) are ignored, so a fresh balance
		# can re-seed after the previous opening entry was cancelled.
		return frappe.db.exists("Fuel Entry", {"fuel_tanker": self.fuel_tanker, "docstatus": ["!=", 2]})

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
		"""Create the opening Fuel Entry for this tanker's ledger.

		The very first time a Fuel Balance is submitted for a fuel tanker there
		is no ledger history yet, so seed a Fuel Entry that carries the opening
		balance forward. Subsequent balances are skipped because the tanker
		already has at least one Fuel Entry.

		The entry posts at 00:00:00 on its date so that it anchors the ledger:
		anything else recorded that same day sorts after it, and anything
		dated earlier is refused outright (see `validate_not_before_opening`).
		"""
		if not self.fuel_tanker:
			return

		# Only seed when this tanker has no active ledger history yet
		# (`refuse_opening_behind_movements` has already stopped a figure
		# that would otherwise be lost here).
		if self.has_active_ledger():
			return

		opening_entry = frappe.get_doc({
			"doctype": "Fuel Entry",
			"date": self.date,
			"posting_time": "00:00:00",
			"site": self.site,
			"fuel_tanker": self.fuel_tanker,
			"utilization_type": "Opening Balance",
			"previous_balance": 0,
			"current_balance": self.balance or 0,
		})
		opening_entry.flags.ignore_permissions = True
		opening_entry.flags.from_fuel_balance = True
		opening_entry.insert()
		opening_entry.submit()
