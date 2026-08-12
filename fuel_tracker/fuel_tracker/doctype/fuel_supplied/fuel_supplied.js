// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Supplied", {
    onload(frm) {
        // Fuel movements record something that already happened, so the picker
        // stops at today. The server refuses a future date regardless.
        frm.set_df_property("date", "max_date", frappe.datetime.get_today());
    },
	setup(frm) {
		// Only open requests can be answered, and only for this tanker — a
		// supply booked against another tanker's request credits the wrong
		// bowser (the server rejects it too).
		frm.set_query("fuel_supply_request", () => {
			const filters = { docstatus: 1, status: ["!=", "Fully Supplied"] };
			if (frm.doc.fuel_tanker) filters.fuel_tanker = frm.doc.fuel_tanker;
			return { filters };
		});
	},

	refresh(frm) {
		show_variance_headline(frm);

		if (frm.doc.docstatus === 1 && frm.doc.fuel_supply_request) {
			frm.add_custom_button(__("Fuel Supply Request"), () => {
				frappe.set_route("Form", "Fuel Supply Request", frm.doc.fuel_supply_request);
			});
		}
	},

	fuel_tanker(frm) {
		// The request must match the tanker, so a tanker change invalidates it
		if (frm.doc.fuel_supply_request) {
			frm.set_value("fuel_supply_request", null);
		}
	},

	fuel_supplied(frm) {
		show_variance_headline(frm);
	},
});

function show_variance_headline(frm) {
	frm.dashboard.clear_headline();

	const requested = flt(frm.doc.requested_litres);
	const supplied = flt(frm.doc.fuel_supplied);
	if (!requested || !supplied) return;

	// Deliveries routinely differ from the request; surface the gap rather
	// than blocking it, since the delivered litres are what actually arrived.
	const variance = supplied - requested;
	if (Math.abs(variance) < 0.001) return;

	frm.dashboard.set_headline(
		variance < 0
			? __("{0} L short of the {1} L requested.", [format_number(-variance, null, 2), format_number(requested, null, 2)])
			: __("{0} L over the {1} L requested.", [format_number(variance, null, 2), format_number(requested, null, 2)]),
		variance < 0 ? "orange" : "blue"
	);
}
