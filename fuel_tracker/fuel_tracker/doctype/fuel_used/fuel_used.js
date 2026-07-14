// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Used", {
    refresh(frm) {
        // Custom client-side logic can be added here if needed
    },
    validate(frm) {
        if (frm.doc.resource_type === "Truck") {
            if (frm.doc.odometer_km < frm.doc.previous_odometer_km) {
                frappe.msgprint(__("Odometer reading cannot be less than the previous reading: {0} km", [frm.doc.previous_odometer_km]));
                frappe.validated = false;
            }
        } else if (frm.doc.resource_type === "Equipment") {
            if (frm.doc.hours_copy < frm.doc.previous_hours_copy) {
                frappe.msgprint(__("Hours reading cannot be less than the previous hours: {0}", [frm.doc.previous_hours_copy]));
                frappe.validated = false;
            }
        }
    },
    before_submit(frm) {
        // drafts stay saveable; the block applies at submit (server check
        // in fuel_used.py is authoritative and re-reads the live resource)
        if (frm.doc.resource_type === "Truck" && !flt(frm.doc.previous_odometer_km)) {
            missing_reading_message(frm, __("Resource {0} has no Current Odometer reading. Set it on the Resource record before dispensing fuel.", [frm.doc.resource]));
            frappe.validated = false;
        } else if (frm.doc.resource_type === "Equipment" && !flt(frm.doc.previous_hours_copy)) {
            missing_reading_message(frm, __("Resource {0} has no Current Hours reading. Set it on the Resource record before dispensing fuel.", [frm.doc.resource]));
            frappe.validated = false;
        }
    }
});

function missing_reading_message(frm, message) {
    frappe.msgprint({
        title: __("Missing Resource Reading"),
        message: message,
        indicator: "red",
        primary_action: {
            label: __("Open Resource"),
            action() {
                frappe.hide_msgprint();
                frappe.set_route("Form", "Resource", frm.doc.resource);
            },
        },
    });
}