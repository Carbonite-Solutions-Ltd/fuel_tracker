"""Turn the Fuel Ledger's own total row back on.

The report used to append a hand-built "Total" row on top of the report's
total row, so the desk added that row into its totals and every figure came
out doubled — which is presumably why sites switched "Add Total Row" off.
The hand-built row is gone, so the report's total row is the only one and
must be on. Migrate deliberately keeps a site's existing `add_total_row`
(see `ignore_values` in frappe.modules.import_file), hence a patch.
"""

import frappe


def execute():
	if frappe.db.exists("Report", "Fuel Ledger"):
		frappe.db.set_value("Report", "Fuel Ledger", "add_total_row", 1, update_modified=False)
