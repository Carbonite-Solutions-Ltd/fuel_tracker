# Copyright (c) 2024, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class Resource(Document):
	def validate(self):
		self.block_reading_edits()

	def on_trash(self):
		"""Never delete a resource that has been part of a submitted dispense.

		Frappe's link check already blocks deletion while referencing
		documents exist; this guard also covers force-deletes and keeps the
		fuel history's foreign keys intact even for cancelled transactions.
		"""
		if frappe.db.exists("Fuel Used", {"resource": self.name, "docstatus": ["!=", 0]}):
			frappe.throw(
				_("Resource {0} has been used in submitted fuel transactions and cannot be deleted.")
				.format(frappe.bold(self.name))
			)

	def block_reading_edits(self):
		"""Lock Current Odometer / Current Hours once they carry a value.

		The initial reading is entered by hand (from zero/empty); after that
		the reading is ledger state and may only move through fuel
		transactions (Fuel Used submit and Fuel Entry cancel set
		flags.from_fuel_transaction before saving). Correcting a wrong
		reading means cancelling the faulty dispense, which recomputes it.
		"""
		if self.is_new() or self.flags.from_fuel_transaction:
			return

		old = self.get_doc_before_save()
		if not old:
			return

		for field, label in (("current_odometer", "Current Odometer"), ("current_hours", "Current Hours")):
			if flt(old.get(field)) and flt(self.get(field)) != flt(old.get(field)):
				frappe.throw(
					_("{0} is locked once set. It changes only through fuel transactions; to correct it, cancel the faulty Fuel Entry instead.")
					.format(_(label))
				)
