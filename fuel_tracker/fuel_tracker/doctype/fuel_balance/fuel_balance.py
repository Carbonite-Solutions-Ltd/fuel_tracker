import frappe
from frappe import _
from frappe.model.document import Document


class FuelBalance(Document):
	def on_submit(self):
		self.seed_opening_fuel_entry()

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
		"""
		if not self.fuel_tanker:
			return

		# Only seed when this tanker has no active ledger history yet.
		# Cancelled Fuel Entries (docstatus 2) are ignored, so a fresh balance
		# can re-seed after the previous opening entry was cancelled.
		if frappe.db.exists("Fuel Entry", {"fuel_tanker": self.fuel_tanker, "docstatus": ["!=", 2]}):
			return

		opening_entry = frappe.get_doc({
			"doctype": "Fuel Entry",
			"date": self.date,
			"site": self.site,
			"fuel_tanker": self.fuel_tanker,
			"utilization_type": "Opening Balance",
			"previous_balance": 0,
			"current_balance": self.balance or 0,
		})
		opening_entry.flags.ignore_permissions = True
		opening_entry.insert()
		opening_entry.submit()
