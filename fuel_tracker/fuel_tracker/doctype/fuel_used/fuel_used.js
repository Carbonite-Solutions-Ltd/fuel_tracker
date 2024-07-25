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
                frappe.msgprint(__("hours_copy cannot be less than the previous hours_copy: {0} hours_copy", [frm.doc.previous_hours_copy]));
                frappe.validated = false;
            }
        }
    }
});