import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from fuel_tracker.fuel_tracker.fuel_ledger import (
	ensure_posting_time,
	get_or_create_fuel_balance,
	warn_if_below_minimum,
	warn_if_ledger_goes_negative,
)
from fuel_tracker.fuel_tracker.resource_ledger import (
	get_previous_reading,
	get_reading_fields,
	repost_resource_readings,
	validate_reading_fits_sequence,
)


class FuelUsed(Document):
	"""Fuel dispensed from a tanker to a resource.

	Balances are not computed here: the `Fuel Entry` this creates prices
	itself against the ledger at its own posting moment, so a backdated
	dispense is measured against the fuel the tanker actually held that day.
	"""

	def validate(self):
		self.posting_datetime = ensure_posting_time(self)
		self.sync_meter_status()

	def before_submit(self):
		# Stamp the posting time now unless the user asked to backdate, so a
		# draft left sitting cannot post behind entries recorded since.
		self.posting_datetime = ensure_posting_time(self, refresh=True)
		if self.review_status == "Incoming Report":
			self.review_status = "Reviewed"
		self.validate_fuel_quantity()
		self.sync_and_validate_resource_reading()

	def on_submit(self):
		posting_datetime = ensure_posting_time(self)

		get_or_create_fuel_balance(self.fuel_tanker, self.site, self.date)
		warn_if_ledger_goes_negative(
			self.fuel_tanker,
			posting_datetime,
			-flt(self.fuel_issued_lts),
			source_label=_("Dispensing {0} L").format(flt(self.fuel_issued_lts)),
		)
		warn_if_below_minimum(self.fuel_tanker, posting_datetime, -flt(self.fuel_issued_lts))

		self.create_fuel_entry()
		# Reposting rather than simply writing this reading back: a document
		# slotted into the middle of the history changes the distance recorded
		# against the fill that follows it, and must not drag the resource's
		# current reading backwards.
		repost_resource_readings(self.resource, self.resource_type, self.posting_datetime)

	def validate_fuel_quantity(self):
		if flt(self.fuel_issued_lts) <= 0:
			frappe.throw(_("Fuel Issued (LTS) must be greater than zero."))

	def sync_meter_status(self):
		"""Copy the resource's faulty-meter flag onto this document.

		Held on the document rather than read live so the desk form can drop
		the mandatory reading as soon as a resource is picked, and so the
		record shows why a reading is missing even if the resource is repaired
		and unflagged later.
		"""
		if not self.resource:
			return

		resource = frappe.db.get_value(
			"Resource", self.resource, ["resource_type", "has_faulty_meter"], as_dict=True
		)
		if not resource:
			return

		self.resource_type = resource.resource_type
		self.meter_faulty = resource.has_faulty_meter

	def sync_and_validate_resource_reading(self):
		"""Set the previous reading from the reading sequence, then validate.

		The previous reading is the one recorded immediately *before* this
		document's posting moment — not the newest reading on the `Resource`.
		That is what lets a fill be keyed in late: a document dated last week
		is measured from last week's reading, and the check that a reading may
		not go backwards is made against both neighbours, so it only has to
		sit between the fills either side of it.

		A resource flagged with a faulty meter is exempt from all of it: no
		reading is required, none is validated, and the entry is tagged so
		consumption reports skip it rather than reporting a bogus 0 km/L.
		"""
		resource = frappe.get_doc("Resource", self.resource)
		self.resource_type = resource.resource_type
		self.meter_faulty = resource.has_faulty_meter

		if self.meter_faulty:
			return

		fields = get_reading_fields(self.resource_type)
		if not fields:
			return

		reading_field, previous_field, _diff_field, current_field = fields

		# mandatory_depends_on only guards the desk form; enforce at
		# submit for API/script-created documents too
		if not flt(self.get(reading_field)):
			frappe.throw(
				_("Current Odometer (KM) is required to dispense fuel to a truck.")
				if self.resource_type == "Truck"
				else _("Current Hours is required to dispense fuel to equipment.")
			)

		previous = get_previous_reading(
			self.resource, self.resource_type, self.posting_datetime, exclude=self.name
		)
		if not flt(previous) and not flt(resource.get(current_field)):
			frappe.throw(
				_("Resource {0} has no opening reading. Set it on the Resource record before dispensing fuel, or flag its meter as faulty.")
				.format(frappe.bold(self.resource))
				+ self.open_resource_button()
			)

		self.set(previous_field, flt(previous))
		validate_reading_fits_sequence(self, self.resource_type)

	def open_resource_button(self):
		return '<br><br><a class="btn btn-primary btn-sm" href="{0}">{1}</a>'.format(
			frappe.utils.get_url_to_form("Resource", self.resource), _("Open Resource")
		)

	def create_fuel_entry(self):
		fuel_entry_data = {
			"doctype": "Fuel Entry",
			"date": self.date,
			"posting_time": self.posting_time,
			"fuel_tanker": self.fuel_tanker,
			"site": self.site,
			"utilization_type": "Dispensed",
			"litres_dispensed": self.fuel_issued_lts,
			"fuel_utilization_id": self.name,
			"resource": self.resource,
			"meter_faulty": self.meter_faulty,
		}

		# A faulty meter yields no usable distance/hours, so no diff is written
		# — a reading typed against a broken meter would otherwise land in the
		# ledger as a wild (often negative) distance. Float columns are not
		# nullable, so the diff reads 0; `meter_faulty` is what tells the
		# consumption report the difference between "travelled nothing" and
		# "was never measured".
		if not self.meter_faulty:
			if self.resource_type == "Truck":
				fuel_entry_data["diff_odometer"] = flt(self.odometer_km) - flt(self.previous_odometer_km)
			elif self.resource_type == "Equipment":
				fuel_entry_data["diff_hours_copy"] = flt(self.hours_copy) - flt(self.previous_hours_copy)

		fuel_entry = frappe.get_doc(fuel_entry_data)
		fuel_entry.flags.ignore_permissions = True  # If necessary to bypass permission checks
		fuel_entry.insert()
		fuel_entry.submit()

	def update_resource_usage(self):
		"""Write the new reading back to the resource.

		Skipped for a faulty meter: no reading was captured, so there is
		nothing trustworthy to carry forward.
		"""
		if self.meter_faulty:
			return

		resource = frappe.get_doc("Resource", self.resource)

		if self.resource_type == "Truck":
			resource.current_odometer = self.odometer_km
		elif self.resource_type == "Equipment":
			resource.current_hours = self.hours_copy

		# readings are locked against manual edits; fuel flows are exempt
		resource.flags.from_fuel_transaction = True
		resource.save()
