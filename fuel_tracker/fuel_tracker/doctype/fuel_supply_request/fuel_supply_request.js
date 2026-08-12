// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Supply Request", {
	refresh(frm) {
		show_fulfilment_headline(frm);

		if (frm.doc.docstatus === 1 && frm.doc.status !== "Fully Supplied") {
			frm.add_custom_button(__("Fuel Supplied"), () => {
				frappe.model.open_mapped_doc({
					method: "fuel_tracker.fuel_tracker.doctype.fuel_supply_request.fuel_supply_request.make_fuel_supplied",
					frm: frm,
				});
			}, __("Create"));
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}
	},
});

function show_fulfilment_headline(frm) {
	frm.dashboard.clear_headline();
	if (frm.doc.docstatus !== 1) return;

	const indicator = { "Pending": "orange", "Partially Supplied": "yellow", "Fully Supplied": "green" }[frm.doc.status];
	if (!indicator) return;

	frm.dashboard.set_headline(
		__("{0} L supplied of {1} L requested — {2} L outstanding.", [
			format_number(frm.doc.supplied_litres, null, 2),
			format_number(frm.doc.requested_litres, null, 2),
			format_number(frm.doc.pending_litres, null, 2),
		]),
		indicator
	);
}
