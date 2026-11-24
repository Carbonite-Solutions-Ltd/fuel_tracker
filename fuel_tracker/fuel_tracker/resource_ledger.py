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


def get_neighbouring_fill(resource, posting_datetime, exclude=None, after=False):
	"""The submitted, metered fill either side of a moment, or None.

	Same cut-off as `get_previous_reading` / `get_next_reading` (time only, no
	creation tiebreak), so it names exactly the fill those readings came from.
	"""
	values = {"resource": resource, "posting_datetime": posting_datetime, "exclude": exclude or ""}
	row = frappe.db.sql(
		"""
		SELECT name
		FROM `tabFuel Used`
		WHERE resource = %(resource)s AND docstatus = 1 AND IFNULL(meter_faulty, 0) = 0
			AND name != %(exclude)s
			AND posting_datetime {op} %(posting_datetime)s
		ORDER BY posting_datetime {order}, creation {order}
		LIMIT 1
		""".format(op=">" if after else "<", order="ASC" if after else "DESC"),
		values,
	)
	return row[0][0] if row else None


def clashing_fill_hint(fill):
	"""Point at the fill a reading clashes with, and how to fix it if it's wrong.

	A reading keyed too high on one fill makes every correct fill after it
	look as though it goes backwards; without the fill's name the person
	submitting has no way to find the real mistake.
	"""
	if not fill:
		return ""
	return "<br><br>" + _(
		"If the reading on {0} is the one that is wrong, correct it there first (Correct Reading, Fuel Tracker Manager), then try again. A draft keeps its reading in the meantime."
	).format(frappe.bold(fill)) + '<br><br><a class="btn btn-primary btn-sm" href="{0}">{1}</a>'.format(
		frappe.utils.get_url_to_form("Fuel Used", fill), _("Open {0}").format(fill)
	)


def validate_reading_fits_sequence(doc, resource_type):
	"""A reading must not go backwards, in either direction.

	Checked against both neighbours rather than only the newest reading, so a
	document can be slotted into the middle of the history as long as it sits
	between the fills either side of it. Measuring against the newest reading
	is what used to make backdating impossible.

	The error names the fill it clashes with: often that fill is the one with
	the mistake, and it is the one to correct.
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
		fill = get_neighbouring_fill(doc.resource, doc.posting_datetime, exclude=doc.name)
		message = (
			_("{0} reading {1} is lower than the {2} recorded on {3} before it ({4}).")
			.format(label, reading, label, frappe.bold(fill), flt(previous))
			if fill
			else _("{0} reading {1} is lower than this resource's opening reading ({2}).")
			.format(label, reading, flt(previous))
		)
		frappe.throw(message + clashing_fill_hint(fill), title=_("Reading Goes Backwards"))

	following = get_next_reading(
		doc.resource, resource_type, doc.posting_datetime, exclude=doc.name
	)
	if following is not None and reading > flt(following):
		fill = get_neighbouring_fill(doc.resource, doc.posting_datetime, exclude=doc.name, after=True)
		frappe.throw(
			_("{0} reading {1} is higher than the {2} already recorded on {3} after it ({4}). Check the date and the reading.")
			.format(label, reading, label, frappe.bold(fill), flt(following))
			+ clashing_fill_hint(fill),
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


#: Roles allowed to correct a reading on a submitted `Fuel Used`.
READING_CORRECTION_ROLES = ("Fuel Tracker Manager", "System Manager")


def get_previous_fill(doc):
	"""The submitted, metered fill immediately before `doc`, or None.

	None means `doc` is the resource's first fill: its previous reading is
	then the opening reading the sequence is anchored on, not another fill's.
	"""
	row = frappe.db.sql(
		"""
		SELECT name
		FROM `tabFuel Used`
		WHERE resource = %(resource)s AND docstatus = 1 AND IFNULL(meter_faulty, 0) = 0
			AND name != %(name)s
			AND (posting_datetime < %(posting_datetime)s
				OR (posting_datetime = %(posting_datetime)s AND creation < %(creation)s))
		ORDER BY posting_datetime DESC, creation DESC
		LIMIT 1
		""",
		{
			"resource": doc.resource,
			"name": doc.name,
			"posting_datetime": doc.posting_datetime,
			"creation": doc.creation,
		},
	)
	return row[0][0] if row else None


def get_anchor_document(resource):
	"""The document `get_anchor_reading` takes the opening reading from.

	The earliest metered fill, submitted *or cancelled* — see
	`get_anchor_reading` for why cancelled ones count.
	"""
	row = frappe.db.sql(
		"""
		SELECT name
		FROM `tabFuel Used`
		WHERE resource = %s AND docstatus IN (1, 2) AND IFNULL(meter_faulty, 0) = 0
		ORDER BY posting_datetime ASC, creation ASC
		LIMIT 1
		""",
		resource,
	)
	return row[0][0] if row else None


def correct_reading(doc, new_reading=None, reason=None, previous_reading=None):
	"""Fix a mistyped reading on a submitted `Fuel Used`, in place.

	Without this the only fix was cancelling the fill's `Fuel Entry`, which
	unwinds and reposts the tanker's fuel too — heavy-handed for a typo, and
	a manager's job. No litres move here: only readings change, and the
	reading ledger is reposted from this document onward, so the distance on
	its own entry and the next fill's, every later document's previous
	reading and the `Resource`'s current reading all follow.

	`new_reading` is this fill's own reading. It must still sit between the
	fills either side of it, exactly as it would have had to at submission.

	`previous_reading` may only be changed on a resource's **first** fill. On
	any other fill the previous reading is simply the reading of the fill
	before it, so that is the one to correct. On the first fill it is the
	opening reading the whole sequence is anchored on, which nothing else can
	reach: it is written to the anchor document (`get_anchor_document`), so
	the ledger starts from it from then on.

	An audit comment records the old and new values, the user and the reason,
	on the document and on the resource.
	"""
	# not frappe.only_for: that returns early under tests, so the gate could
	# never be tested. Administrator holds every role, as only_for allows.
	if frappe.session.user != "Administrator" and set(READING_CORRECTION_ROLES).isdisjoint(frappe.get_roles()):
		frappe.throw(
			_("Only a Fuel Tracker Manager can correct a submitted reading."),
			frappe.PermissionError,
		)

	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted Fuel Used can have its reading corrected. Edit the draft instead."))
	if doc.is_miscellaneous():
		frappe.throw(_("A miscellaneous issue has no resource, so it has no reading to correct."))
	if doc.meter_faulty:
		frappe.throw(_("This fill was recorded against a faulty meter, so it carries no reading to correct."))

	fields = get_reading_fields(doc.resource_type)
	if not fields:
		frappe.throw(_("Readings apply only to Truck or Equipment resources."))

	reading_field, previous_field, _diff_field, _current_field = fields
	label = _("Odometer (KM)") if doc.resource_type == "Truck" else _("Hours")

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required to correct a reading."))

	old_reading = flt(doc.get(reading_field))
	old_previous = flt(doc.get(previous_field))
	reading = old_reading if new_reading in (None, "") else flt(new_reading)
	previous = old_previous if previous_reading in (None, "") else flt(previous_reading)

	reading_changed = reading != old_reading
	previous_changed = previous != old_previous
	if not reading_changed and not previous_changed:
		frappe.throw(_("The corrected readings are the same as the ones recorded."))
	if reading <= 0:
		frappe.throw(_("The corrected {0} reading must be greater than zero.").format(label))

	if previous_changed:
		previous_fill = get_previous_fill(doc)
		if previous_fill:
			frappe.throw(
				_("The previous reading on this fill is the reading recorded on {0}. Correct that fill instead.")
				.format(frappe.get_desk_link("Fuel Used", previous_fill)),
				title=_("Not the First Fill"),
			)
		# 0 is how the ledger says "no opening reading" (get_anchor_reading
		# would fall back to the resource's live reading), so it can't be set
		if previous <= 0:
			frappe.throw(_("The opening {0} reading must be greater than zero.").format(label))
		if reading < previous:
			frappe.throw(
				_("{0} reading {1} is lower than the opening reading {2}.").format(label, reading, previous),
				title=_("Reading Goes Backwards"),
			)
		following = get_next_reading(doc.resource, doc.resource_type, doc.posting_datetime, exclude=doc.name)
		if following is not None and reading > flt(following):
			frappe.throw(
				_("{0} reading {1} is higher than the {2} already recorded after it on this resource ({3}). Check the date and the reading.")
				.format(label, reading, label, flt(following)),
				title=_("Reading Overtakes a Later One"),
			)
	else:
		# checked against the neighbours as at submission; throws if it doesn't fit
		doc.set(reading_field, reading)
		validate_reading_fits_sequence(doc, doc.resource_type)

	# everything is validated before anything is written. These are
	# deliberate user edits, so `modified` is bumped (ledger queries never
	# order by it); the derived figures are reposted without bumping it
	if previous_changed:
		for name in {get_anchor_document(doc.resource), doc.name}:
			frappe.db.set_value("Fuel Used", name, previous_field, previous)
	if reading_changed:
		frappe.db.set_value("Fuel Used", doc.name, reading_field, reading)
	repost_resource_readings(doc.resource, doc.resource_type, doc.posting_datetime)

	changes = []
	if previous_changed:
		changes.append(_("opening {0} changed from {1} to {2}").format(label, old_previous, previous))
	if reading_changed:
		changes.append(_("{0} changed from {1} to {2}").format(label, old_reading, reading))
	note = _("Reading corrected on {0}: {1} by {2}. Reason: {3}").format(
		doc.name, "; ".join(changes), frappe.session.user, reason
	)
	doc.add_comment("Comment", note)
	frappe.get_doc("Resource", doc.resource).add_comment("Comment", note)

	return reading
