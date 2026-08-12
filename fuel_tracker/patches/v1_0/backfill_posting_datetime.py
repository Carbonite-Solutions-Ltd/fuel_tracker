# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Give existing documents a posting time, then repost every tanker's ledger.

Before the date-aware ledger, entries carried only a `date` and were appended
in creation order. Their recorded order is therefore the time they were keyed
in, so `creation`'s time-of-day is the best available posting time — it
reproduces exactly the sequence the old ledger used, which means this patch
re-derives the same balances it already had, only now anchored to a sort key
that backdated entries can slot into.

The repost afterwards is what makes the historical data trustworthy going
forward: every entry's `previous_balance`/`current_balance` is recomputed from
its tanker's opening balance and the chain of movements after it, so any drift
left by the old append-only arithmetic is corrected in place.
"""

import frappe


def execute():
	backfill_posting_times()
	repost_all_tankers()


#: Legacy rows all share one posting time so that `creation` — the second half
#: of the ledger's sort key — decides their order.
LEGACY_TIME = "00:00:01"


def backfill_posting_times():
	"""Give legacy rows a posting time that preserves the order they were keyed.

	The obvious move is `TIME(creation)`, but that is wrong: it keeps the
	time-of-day and throws the creation *date* away. Almost nothing here is
	recorded on the day the fuel moved — 461 of 462 documents on the site this
	was written against were keyed in days later — so two fills sharing a fuel
	date get ordered by what time of day somebody happened to type them, not by
	which was entered first. That invents an order the old ledger never had,
	and where it disagrees with reality it shows up as an odometer running
	backwards.

	The old ledger ordered by `(date, creation)`: entries were appended in
	creation order and the reports sorted on date then name. Giving every
	legacy row the same posting time reproduces that exactly, because
	`creation` is already the tiebreaker in the new sort key.
	"""
	for doctype in ("Fuel Entry", "Fuel Supplied", "Fuel Used", "Fuel Adjustment"):
		if not frappe.db.has_column(doctype, "posting_time"):
			continue

		frappe.db.sql(
			"""
			UPDATE `tab{doctype}`
			SET posting_time = %(legacy_time)s
			WHERE posting_time IS NULL
			   OR posting_time = TIME(creation)
			""".format(doctype=doctype),
			{"legacy_time": LEGACY_TIME},
		)

	# The opening balance anchors its tanker's ledger, so it must sort ahead of
	# everything else recorded on its date rather than at the moment it was keyed.
	frappe.db.sql(
		"""
		UPDATE `tabFuel Entry`
		SET posting_time = '00:00:00'
		WHERE utilization_type = 'Opening Balance'
		"""
	)

	for doctype in ("Fuel Entry", "Fuel Used"):
		if not frappe.db.has_column(doctype, "posting_datetime"):
			continue

		frappe.db.sql(
			"""
			UPDATE `tab{doctype}`
			SET posting_datetime = TIMESTAMP(date, posting_time)
			WHERE date IS NOT NULL
			""".format(doctype=doctype)
		)


def repost_all_tankers():
	"""Recompute the running balance of every tanker's ledger."""
	from fuel_tracker.fuel_tracker.fuel_ledger import repost_tanker

	tankers = frappe.get_all(
		"Fuel Entry", filters={"docstatus": 1}, distinct=True, pluck="fuel_tanker"
	)
	tankers = [t for t in tankers if t]

	for tanker in tankers:
		repost_tanker(tanker)

	# No commit here: the patch runner commits once the whole patch succeeds and
	# rolls back if it raises. Committing mid-patch would strand a half-reposted
	# ledger if a later tanker failed.
	print("Reposted the fuel ledger for {0} tanker(s).".format(len(tankers)))
