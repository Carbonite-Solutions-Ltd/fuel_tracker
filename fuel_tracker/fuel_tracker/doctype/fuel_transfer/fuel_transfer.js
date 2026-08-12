// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Transfer", {
	onload(frm) {
		// Fuel movements record something that already happened, so the picker
		// stops at today. The server refuses a future date regardless.
		frm.set_df_property("date", "max_date", frappe.datetime.get_today());
	},

	setup(frm) {
		// A transfer moves fuel between two tankers, so never offer the same
		// one on both sides.
		frm.set_query("to_tanker", () => ({
			filters: { name: ["!=", frm.doc.from_tanker || ""] },
		}));
		frm.set_query("from_tanker", () => ({
			filters: { name: ["!=", frm.doc.to_tanker || ""] },
		}));
	},

	refresh(frm) {
		show_route_headline(frm);

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Fuel Ledger"), () => {
				frappe.set_route("query-report", "Fuel Ledger", {
					fuel_tanker: [frm.doc.from_tanker, frm.doc.to_tanker],
				});
			});
		}
	},

	from_tanker(frm) {
		refresh_balances(frm);
	},
	to_tanker(frm) {
		refresh_balances(frm);
	},
	date(frm) {
		refresh_balances(frm);
	},
	posting_time(frm) {
		refresh_balances(frm);
	},

	litres_transferred(frm) {
		if (flt(frm.doc.litres_transferred) > flt(frm.doc.from_balance)) {
			frappe.show_alert({
				message: __("{0} holds only {1} L at this date and time.", [
					frm.doc.from_tanker,
					format_number(frm.doc.from_balance, null, 2),
				]),
				indicator: "orange",
			});
		}
	},
});

function show_route_headline(frm) {
	frm.dashboard.clear_headline();
	if (!frm.doc.from_site || !frm.doc.to_site) return;

	if (frm.doc.from_site === frm.doc.to_site) {
		frm.dashboard.set_headline(
			__("Both tankers are on site {0}; this transfer moves fuel within the site.", [frm.doc.from_site]),
			"blue"
		);
	} else {
		frm.dashboard.set_headline(
			__("{0} will decrease and {1} will increase.", [frm.doc.from_site, frm.doc.to_site]),
			"blue"
		);
	}
}

function refresh_balances(frm) {
	// Show each tanker as it stood at the posting moment, so a backdated
	// transfer is keyed against the balances that actually applied then.
	if (frm.doc.docstatus !== 0 || !frm.doc.date) return;

	["from", "to"].forEach((side) => {
		const tanker = frm.doc[`${side}_tanker`];
		if (!tanker) return;

		frappe.call({
			method: "fuel_tracker.fuel_tracker.fuel_ledger.get_tanker_balance_on",
			args: { fuel_tanker: tanker, date: frm.doc.date, posting_time: frm.doc.posting_time },
			callback(r) {
				if (r.message === undefined) return;
				frm.set_value(`${side}_balance`, r.message);
			},
		});
	});
}
