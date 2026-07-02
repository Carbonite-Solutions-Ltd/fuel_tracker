// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Balance", {
	refresh(frm) {
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
