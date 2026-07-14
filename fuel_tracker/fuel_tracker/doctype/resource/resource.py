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

	@frappe.whitelist()
	def reset_reading(self, new_reading, reason):
		"""Controlled correction of a locked reading (meter replaced/reset).

		System Manager only. Does not touch the fuel ledger — no litres
		move — but leaves an audit comment on the resource recording the
		old value, new value, user and reason.
		"""
		frappe.only_for("System Manager")

		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("A reason is required to reset the reading."))

		if self.resource_type == "Truck":
			field, label = "current_odometer", _("Current Odometer")
		elif self.resource_type == "Equipment":
			field, label = "current_hours", _("Current Hours")
		else:
			frappe.throw(_("Readings apply only to Truck or Equipment resources."))

		new_reading = flt(new_reading)
		old_reading = flt(self.get(field))
		if new_reading < 0:
			frappe.throw(_("The new reading cannot be negative."))
		if new_reading == old_reading:
			frappe.throw(_("The new reading is the same as the current one."))

		self.set(field, new_reading)
		self.flags.from_reading_reset = True
		self.save()
		self.add_comment(
			"Comment",
			_("Reading reset: {0} changed from {1} to {2} by {3}. Reason: {4}")
			.format(label, old_reading, new_reading, frappe.session.user, reason),
		)
		frappe.msgprint(
			_("{0} reset from {1} to {2}.").format(label, old_reading, new_reading),
			indicator="green",
			alert=True,
		)

	def block_reading_edits(self):
		"""Lock Current Odometer / Current Hours once they carry a value.

		The initial reading is entered by hand (from zero/empty); after that
		the reading is ledger state and may only move through fuel
		transactions (Fuel Used submit and Fuel Entry cancel set
		flags.from_fuel_transaction before saving) or a Reset Reading by a
		System Manager. Correcting a wrong dispense still means cancelling
		its Fuel Entry, which recomputes the reading.
		"""
		if self.is_new() or self.flags.from_fuel_transaction or self.flags.from_reading_reset:
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
