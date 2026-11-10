// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Balance", {
	refresh(frm) {
		frm.dashboard.clear_headline();
		if (frm.doc.docstatus === 0 && frm.doc.fuel_tanker) {
			// nothing can be recorded on the tanker until this is submitted
			frm.dashboard.set_headline(
				__("This is {0}'s opening balance. Until it is submitted, no fuel can be supplied, dispensed, transferred or adjusted on the tanker. Enter the litres it held at the start of the Date and submit.", [`<b>${frappe.utils.escape_html(frm.doc.fuel_tanker)}</b>`]),
				"orange"
			);
		}

		// Once the tanker's ledger holds a submitted Fuel Entry, lock the
		// balance down: every field becomes read-only and saving is disabled.
		// Cancel/delete are blocked server-side (see fuel_balance.py).
		if (!frm.doc.fuel_tanker || frm.doc.docstatus !== 1) {
			return;
		}

		frappe.db.get_list("Fuel Entry", {
			filters: { fuel_tanker: frm.doc.fuel_tanker, docstatus: 1 },
			limit: 1,
		}).then((entries) => {
			if (entries && entries.length) {
				frm.set_read_only();
				frm.disable_save();
			}
		});
	},
});
