// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Adjustment", {
    date(frm) {
        warn_if_future(frm);
        fetch_system_balance(frm);
    },
    posting_time(frm) {
        fetch_system_balance(frm);
    },
    set_posting_time(frm) {
        fetch_system_balance(frm);
    },
    refresh(frm) {
        fetch_system_balance(frm);
    },
    fuel_tanker(frm) {
        fetch_system_balance(frm);
    },
    adjustment_mode(frm) {
        compute_preview(frm);
    },
    measured_balance(frm) {
        compute_preview(frm);
    },
    quantity(frm) {
        compute_preview(frm);
    },
    validate(frm) {
        if (frm.doc.reason === "Other" && !(frm.doc.remarks || "").trim()) {
            frappe.msgprint(__("Remarks are required when the reason is Other."));
            frappe.validated = false;
        }
    },
    before_submit(frm) {
        if (!flt(frm.doc.adjustment_litres, 3)) {
            frappe.msgprint(__("The computed adjustment is zero litres; there is nothing to adjust."));
            frappe.validated = false;
        }
    },
});

function fetch_system_balance(frm) {
    // Preview only: the server re-reads the balance at submit time.
    // Submitted documents keep their stamped audit value.
    if (frm.doc.docstatus > 0) return;
    if (!frm.doc.fuel_tanker || !frm.doc.date) {
        frm.set_value("system_balance", 0);
        return;
    }
    // The balance on the adjustment's own date and time, as the server
    // measures it — not today's live Fuel Balance, which would refuse a
    // backdated dip count as "nothing to adjust" or preview the wrong figure.
    frappe.call({
        method: "fuel_tracker.fuel_tracker.fuel_ledger.get_tanker_balance_on",
        args: {
            fuel_tanker: frm.doc.fuel_tanker,
            date: frm.doc.date,
            // unticked, the server stamps the time of submission onto the date
            posting_time: frm.doc.set_posting_time ? frm.doc.posting_time : frappe.datetime.now_time(),
        },
        callback(r) {
            frm.set_value("system_balance", flt(r.message));
            compute_preview(frm);
        },
    });
}

function compute_preview(frm) {
    if (frm.doc.docstatus > 0) return;
    let adjustment = 0;
    if (frm.doc.adjustment_mode === "Measured Balance") {
        adjustment = flt(frm.doc.measured_balance) - flt(frm.doc.system_balance);
    } else if (frm.doc.adjustment_mode === "Quantity") {
        adjustment = flt(frm.doc.quantity);
    }
    frm.set_value("adjustment_litres", flt(adjustment, 3));
}

function warn_if_future(frm) {
    // Fuel movements record something that already happened. The server
    // refuses a future date outright; this just says so straight away,
    // without touching the date picker's own options.
    if (frm.doc.date && frm.doc.date > frappe.datetime.get_today()) {
        frappe.msgprint({
            title: __("Future Dated"),
            message: __("Date cannot be in the future. Fuel is recorded after it moves; backdating is allowed."),
            indicator: "red",
        });
        frm.set_value("date", frappe.datetime.get_today());
    }
}
