// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Tanker", {
	setup(frm) {
		// Let a typed tanker name that matches no Item survive the link
		// control's client-side validation (which otherwise clears it on
		// blur). The server auto-creates the Item on save — see
		// FuelTanker.ensure_tanker_item in fuel_tanker.py.
		frm.get_field("tanker").df.ignore_link_validation = true;
	},
});
