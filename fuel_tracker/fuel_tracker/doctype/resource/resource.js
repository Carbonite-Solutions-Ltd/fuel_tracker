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

		// Controlled correction for meter replacements/resets — System
		// Manager only (also enforced server-side in reset_reading)
		if (
			!frm.is_new()
			&& ["Truck", "Equipment"].includes(frm.doc.resource_type)
			&& frappe.user.has_role("System Manager")
		) {
			frm.add_custom_button(__("Reset Reading"), () => reset_reading_dialog(frm));
		}
	},
});

function reset_reading_dialog(frm) {
	const is_truck = frm.doc.resource_type === "Truck";
	const label = is_truck ? __("Current Odometer") : __("Current Hours");
	const current = is_truck ? frm.doc.current_odometer : frm.doc.current_hours;

	const dialog = new frappe.ui.Dialog({
		title: __("Reset {0}", [label]),
		fields: [
			{
				fieldname: "current_value",
				label: __("Current Value"),
				fieldtype: "Float",
				default: current,
				read_only: 1,
			},
			{
				fieldname: "new_reading",
				label: __("New Reading"),
				fieldtype: "Float",
				reqd: 1,
			},
			{
				fieldname: "reason",
				label: __("Reason"),
				fieldtype: "Small Text",
				reqd: 1,
				description: __("e.g. odometer replaced, hour meter reset"),
			},
		],
		primary_action_label: __("Reset"),
		primary_action(values) {
			frm.call("reset_reading", {
				new_reading: values.new_reading,
				reason: values.reason,
			}).then(() => {
				dialog.hide();
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}
