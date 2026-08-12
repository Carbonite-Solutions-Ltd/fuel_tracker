# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Date-aware odometer / hour-meter readings for a resource.

The fuel ledger made *balances* date-aware; this does the same for *readings*.
Without it, backdating is only half-implemented: a `Fuel Used` took its
previous reading from the live `Resource`, which holds the newest reading of
all. Keying in a fill that was missed last week — with the odometer that
genuinely applied last week — was therefore rejected as "less than the
resource's current reading", and the distance recorded against it (which is
what the consumption report divides by) was measured from the wrong point.

Readings form their own small ledger, ordered like the fuel one by
`(posting_datetime, creation)` over the submitted `Fuel Used` documents of a
resource:

* the previous reading is the one recorded immediately *before* a document,
  not the newest one on record;
* a reading must sit between its neighbours, so slotting a document into the
  middle of the history cannot break the sequence;
* inserting or cancelling a document reposts the readings after it, rewriting
  each one's stored previous reading and the distance/hours on its ledger
  entry, and leaves `Resource` holding the latest reading.

Resources flagged `has_faulty_meter` record no reading at all, so their
documents are skipped entirely — they neither supply a previous reading nor
consume one, and the gap simply spans them.
"""

import frappe
from frappe import _
from frappe.utils import flt

#: (reading field on Fuel Used, previous-reading field, diff field on Fuel
#: Entry, current-reading field on Resource) per resource type.
READING_FIELDS = {
	"Truck": ("odometer_km", "previous_odometer_km", "diff_odometer", "current_odometer"),
	"Equipment": ("hours_copy", "previous_hours_copy", "diff_hours_copy", "current_hours"),
}


def get_reading_fields(resource_type):
	return READING_FIELDS.get(resource_type)


def get_reading_documents(resource, resource_type, from_datetime=None, exclude=None):
	"""Submitted, metered `Fuel Used` documents for a resource, in order.

	Documents recorded against a faulty meter are left out: they carry no
	reading, so they take no part in the sequence.
	"""
	fields = get_reading_fields(resource_type)
	if not fields:
		return []

	reading_field, previous_field, _diff_field, _current_field = fields

	filters = {"resource": resource, "docstatus": 1, "meter_faulty": 0}
	if from_datetime:
		filters["posting_datetime"] = [">=", from_datetime]
	if exclude:
		filters["name"] = ["!=", exclude]

	return frappe.get_all(
		"Fuel Used",
		filters=filters,
		fields=["name", "posting_datetime", "creation", reading_field, previous_field],
		order_by="posting_datetime asc, creation asc",
	)


def get_anchor_reading(resource, resource_type):
	"""The reading the sequence starts from.

	`Resource.current_odometer` is mutated as fuel is issued, so once any fill
	exists it is no longer the opening reading. The earliest document's stored
	previous reading is, and it plays the same role the opening balance plays
	in the fuel ledger: an anchor that is never recomputed.

	Cancelled documents are consulted too, and deliberately so. Cancelling
	every fill must put the resource back to the reading it started at, but by
	then no submitted document remains to say what that was — only the
	cancelled ones still carry it. Falling back to the resource's own field
	instead would hand back the very reading being unwound.
	"""
	fields = get_reading_fields(resource_type)
	if not fields:
		return 0.0

	reading_field, previous_field, _diff_field, current_field = fields

	earliest = frappe.db.sql(
		"""
		SELECT `{previous_field}`
		FROM `tabFuel Used`
		WHERE resource = %s AND docstatus IN (1, 2) AND IFNULL(meter_faulty, 0) = 0
		ORDER BY posting_datetime ASC, creation ASC
		LIMIT 1
		""".format(previous_field=previous_field),
		resource,
	)
	if earliest and flt(earliest[0][0]):
		return flt(earliest[0][0])

	return flt(frappe.db.get_value("Resource", resource, current_field))


def get_previous_reading(resource, resource_type, posting_datetime, exclude=None, creation=None):
	"""The reading recorded immediately before a moment in the sequence."""
	fields = get_reading_fields(resource_type)
	if not fields:
		return 0.0

	reading_field, _previous_field, _diff_field, _current_field = fields

	conditions = [
		"resource = %(resource)s",
		"docstatus = 1",
		"IFNULL(meter_faulty, 0) = 0",
	]
	values = {"resource": resource, "posting_datetime": posting_datetime}

	if creation:
		values["creation"] = creation
		conditions.append(
			"(posting_datetime < %(posting_datetime)s"
			" OR (posting_datetime = %(posting_datetime)s AND creation < %(creation)s))"
		)
	else:
		conditions.append("posting_datetime < %(posting_datetime)s")

	if exclude:
		conditions.append("name != %(exclude)s")
		values["exclude"] = exclude

	row = frappe.db.sql(
		"""
		SELECT `{reading_field}`
		FROM `tabFuel Used`
		WHERE {conditions}
		ORDER BY posting_datetime DESC, creation DESC
		LIMIT 1
		""".format(reading_field=reading_field, conditions=" AND ".join(conditions)),
		values,
	)

	if row:
		return flt(row[0][0])

	return get_anchor_reading(resource, resource_type)


def get_next_reading(resource, resource_type, posting_datetime, exclude=None, creation=None):
	"""The reading recorded immediately after a moment, or None if it is last."""
	fields = get_reading_fields(resource_type)
	if not fields:
		return None

	reading_field, _previous_field, _diff_field, _current_field = fields

	conditions = [
		"resource = %(resource)s",
		"docstatus = 1",
		"IFNULL(meter_faulty, 0) = 0",
	]
	values = {"resource": resource, "posting_datetime": posting_datetime}

	if creation:
		values["creation"] = creation
		conditions.append(
			"(posting_datetime > %(posting_datetime)s"
			" OR (posting_datetime = %(posting_datetime)s AND creation > %(creation)s))"
		)
	else:
		conditions.append("posting_datetime > %(posting_datetime)s")

	if exclude:
		conditions.append("name != %(exclude)s")
		values["exclude"] = exclude

	row = frappe.db.sql(
		"""
		SELECT `{reading_field}`
		FROM `tabFuel Used`
		WHERE {conditions}
		ORDER BY posting_datetime ASC, creation ASC
		LIMIT 1
		""".format(reading_field=reading_field, conditions=" AND ".join(conditions)),
		values,
	)

	return flt(row[0][0]) if row else None


def validate_reading_fits_sequence(doc, resource_type):
	"""A reading must not go backwards, in either direction.

	Checked against both neighbours rather than only the newest reading, so a
	document can be slotted into the middle of the history as long as it sits
	between the fills either side of it. Measuring against the newest reading
	is what used to make backdating impossible.
	"""
	fields = get_reading_fields(resource_type)
	if not fields:
		return

	reading_field, _previous_field, _diff_field, _current_field = fields
	reading = flt(doc.get(reading_field))
	label = _("Odometer (KM)") if resource_type == "Truck" else _("Hours")

	previous = get_previous_reading(
		doc.resource, resource_type, doc.posting_datetime, exclude=doc.name
	)
	if reading < flt(previous):
		frappe.throw(
			_("{0} reading {1} is lower than the {2} recorded before it on this resource ({3}).")
			.format(label, reading, label, flt(previous)),
			title=_("Reading Goes Backwards"),
		)

	following = get_next_reading(
		doc.resource, resource_type, doc.posting_datetime, exclude=doc.name
	)
	if following is not None and reading > flt(following):
		frappe.throw(
			_("{0} reading {1} is higher than the {2} already recorded after it on this resource ({3}). Check the date and the reading.")
			.format(label, reading, label, flt(following)),
			title=_("Reading Overtakes a Later One"),
		)


def repost_resource_readings(resource, resource_type=None, from_datetime=None):
	"""Rewrite previous readings and distances after a change.

	Mirrors `repost_tanker`: walks the metered documents from a point onward,
	rewrites each one's stored previous reading and the distance/hours on its
	`Fuel Entry`, and finally points the `Resource` at the newest reading.
	Submitted rows are written with `frappe.db.set_value(update_modified=False)`
	because these figures are derived state, not user input.
	"""
	if not resource:
		return

	resource_type = resource_type or frappe.db.get_value("Resource", resource, "resource_type")
	fields = get_reading_fields(resource_type)
	if not fields:
		return

	reading_field, previous_field, diff_field, current_field = fields
	documents = get_reading_documents(resource, resource_type, from_datetime)

	if documents:
		running = get_previous_reading(
			resource,
			resource_type,
			documents[0].posting_datetime,
			creation=documents[0].creation,
		)

		for document in documents:
			reading = flt(document.get(reading_field))
			previous = flt(running)

			if flt(document.get(previous_field)) != previous:
				frappe.db.set_value(
					"Fuel Used", document.name, previous_field, previous, update_modified=False
				)

			entry = frappe.db.get_value(
				"Fuel Entry", {"fuel_utilization_id": document.name, "docstatus": 1}, "name"
			)
			if entry:
				frappe.db.set_value(
					"Fuel Entry", entry, diff_field, reading - previous, update_modified=False
				)

			running = reading

	sync_resource_reading(resource, resource_type)


def sync_resource_reading(resource, resource_type=None):
	"""Point the resource at the newest reading recorded against it.

	Taken from the last document in posting order rather than from whichever
	one was submitted most recently, so cancelling or backdating leaves the
	resource holding the reading that genuinely applies now.
	"""
	resource_type = resource_type or frappe.db.get_value("Resource", resource, "resource_type")
	fields = get_reading_fields(resource_type)
	if not fields:
		return

	reading_field, _previous_field, _diff_field, current_field = fields

	documents = get_reading_documents(resource, resource_type)
	latest = flt(documents[-1].get(reading_field)) if documents else get_anchor_reading(resource, resource_type)

	if flt(frappe.db.get_value("Resource", resource, current_field)) == latest:
		return

	# readings are locked against manual edits; fuel flows are exempt
	doc = frappe.get_doc("Resource", resource)
	doc.set(current_field, latest)
	doc.flags.from_fuel_transaction = True
	doc.save(ignore_permissions=True)
