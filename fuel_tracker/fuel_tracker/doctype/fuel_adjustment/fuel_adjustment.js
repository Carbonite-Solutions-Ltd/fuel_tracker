// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Adjustment", {
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
    // Preview only: the server re-reads the live balance at submit time.
    // Submitted documents keep their stamped audit value.
    if (frm.doc.docstatus > 0) return;
    if (!frm.doc.fuel_tanker) {
        frm.set_value("system_balance", 0);
        return;
    }
    // Fuel Balance is autonamed field:fuel_tanker, so the docname is the tanker
    frappe.db.get_value("Fuel Balance", frm.doc.fuel_tanker, "balance").then((r) => {
        frm.set_value("system_balance", flt(r.message && r.message.balance));
        compute_preview(frm);
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
