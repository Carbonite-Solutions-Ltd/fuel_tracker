// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Used", {
    onload(frm) {
        // Fuel movements record something that already happened, so the picker
        // stops at today. The server refuses a future date regardless.
        frm.set_df_property("date", "max_date", frappe.datetime.get_today());
    },
    refresh(frm) {
        show_faulty_meter_notice(frm);
        show_balance_on_date(frm);
    },
    resource(frm) {
        // meter_faulty is fetched from the resource; refresh the notice once
        // the fetch lands so the operator sees why the reading went optional
        frm.trigger("refresh");
    },
    fuel_tanker(frm) {
        show_balance_on_date(frm);
    },
    date(frm) {
        show_balance_on_date(frm);
    },
    validate(frm) {
        // A faulty meter yields no trustworthy reading, so nothing to compare
        if (frm.doc.meter_faulty) return;

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
        if (frm.doc.meter_faulty) return;

        if (frm.doc.resource_type === "Truck" && !flt(frm.doc.previous_odometer_km)) {
            missing_reading_message(frm, __("Resource {0} has no Current Odometer reading. Set it on the Resource record before dispensing fuel, or flag its meter as faulty.", [frm.doc.resource]));
            frappe.validated = false;
        } else if (frm.doc.resource_type === "Equipment" && !flt(frm.doc.previous_hours_copy)) {
            missing_reading_message(frm, __("Resource {0} has no Current Hours reading. Set it on the Resource record before dispensing fuel, or flag its meter as faulty.", [frm.doc.resource]));
            frappe.validated = false;
        }
    }
});

function show_faulty_meter_notice(frm) {
    frm.dashboard.clear_headline();
    if (!frm.doc.meter_faulty) return;

    const label = frm.doc.resource_type === "Equipment" ? __("hour meter") : __("odometer");
    frm.dashboard.set_headline(
        __("The {0} on {1} is flagged as faulty, so no reading is required. This dispense is excluded from consumption reporting.", [label, frm.doc.resource]),
        "orange"
    );
}

function show_balance_on_date(frm) {
    // Backdated documents are priced against the balance on their own date,
    // so show that figure rather than leaving the user guessing from today's.
    if (!frm.doc.fuel_tanker || !frm.doc.date || frm.doc.docstatus !== 0) return;

    frappe.call({
        method: "fuel_tracker.fuel_tracker.fuel_ledger.get_tanker_balance_on",
        args: {
            fuel_tanker: frm.doc.fuel_tanker,
            date: frm.doc.date,
            posting_time: frm.doc.posting_time,
        },
        callback(r) {
            if (r.message === undefined) return;
            frm.set_df_property(
                "fuel_issued_lts",
                "description",
                __("Tanker balance on {0}: {1} L", [frappe.datetime.str_to_user(frm.doc.date), format_number(r.message, null, 2)])
            );
            frm.refresh_field("fuel_issued_lts");
        },
    });
}

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
