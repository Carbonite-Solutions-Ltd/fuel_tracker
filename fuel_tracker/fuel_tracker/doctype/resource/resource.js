// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Resource", {
	refresh(frm) {
		// Once a reading is saved it becomes ledger state: read-only in the
		// form, moved only by fuel transactions. The server enforces this
		// too (resource.py block_reading_edits); this mirrors it in the UI.
		if (!frm.is_new()) {
			if (flt(frm.doc.current_odometer)) {
				frm.set_df_property("current_odometer", "read_only", 1);
			}
			if (flt(frm.doc.current_hours)) {
				frm.set_df_property("current_hours", "read_only", 1);
			}
		}
	},
});
