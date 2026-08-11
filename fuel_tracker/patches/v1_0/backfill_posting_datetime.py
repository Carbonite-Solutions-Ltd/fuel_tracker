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


def backfill_posting_times():
	"""Copy the time-of-day from `creation` into `posting_time`."""
	for doctype in ("Fuel Entry", "Fuel Supplied", "Fuel Used", "Fuel Adjustment"):
		if not frappe.db.has_column(doctype, "posting_time"):
			continue

		frappe.db.sql(
			"""
			UPDATE `tab{doctype}`
			SET posting_time = TIME(creation)
			WHERE posting_time IS NULL
			""".format(doctype=doctype)
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

	frappe.db.sql(
		"""
		UPDATE `tabFuel Entry`
		SET posting_datetime = TIMESTAMP(date, posting_time)
		WHERE date IS NOT NULL
		"""
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
