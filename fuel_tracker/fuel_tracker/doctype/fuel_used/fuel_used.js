// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Used", {
    refresh(frm) {
        show_entry_notice(frm);
        show_balance_on_date(frm);
        add_correct_reading_button(frm);
    },
    entry_type(frm) {
        // A miscellaneous issue fuels no resource, so drop any that was
        // picked (and the readings fetched with it) before the switch
        if (is_miscellaneous(frm)) {
            clear_resource(frm);
        }
        show_entry_notice(frm);
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
        warn_if_future(frm);
        show_balance_on_date(frm);
    },
    // No client-side "reading went backwards" check: the previous reading
    // shown here is the resource's newest one, so comparing against it would
    // refuse a legitimately backdated fill. The server checks the reading
    // against the fills either side of the posting moment and names them.
    before_submit(frm) {
        // drafts stay saveable; the block applies at submit (server check
        // in fuel_used.py is authoritative and re-reads the live resource)
        if (is_miscellaneous(frm) || frm.doc.meter_faulty) return;

        if (frm.doc.resource_type === "Truck" && !flt(frm.doc.previous_odometer_km)) {
            missing_reading_message(frm, __("Resource {0} has no Current Odometer reading. Set it on the Resource record before dispensing fuel, or flag its meter as faulty.", [frm.doc.resource]));
            frappe.validated = false;
        } else if (frm.doc.resource_type === "Equipment" && !flt(frm.doc.previous_hours_copy)) {
            missing_reading_message(frm, __("Resource {0} has no Current Hours reading. Set it on the Resource record before dispensing fuel, or flag its meter as faulty.", [frm.doc.resource]));
            frappe.validated = false;
        }
    }
});

const RESOURCE_FIELDS = [
    "resource", "resource_type", "meter_faulty", "stationed_site", "reg_no", "make", "type", "model",
    "previous_odometer_km", "odometer_km", "previous_hours_copy", "hours_copy",
];

function is_miscellaneous(frm) {
    return frm.doc.entry_type === "Miscellaneous";
}

function clear_resource(frm) {
    // mirrors clear_resource() in fuel_used.py, which is authoritative
    const values = {};
    RESOURCE_FIELDS.forEach((fieldname) => {
        if (frm.doc[fieldname]) values[fieldname] = null;
    });
    if (Object.keys(values).length) frm.set_value(values);
}

function show_entry_notice(frm) {
    frm.dashboard.clear_headline();

    if (is_miscellaneous(frm)) {
        frm.dashboard.set_headline(
            __("Miscellaneous issue: fuel given out for site use rather than to a vehicle or machine. It reduces the tanker balance but is excluded from consumption reporting."),
            "blue"
        );
        return;
    }

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

// Roles allowed to correct a submitted reading; mirrors
// READING_CORRECTION_ROLES in resource_ledger.py, which is authoritative.
const READING_CORRECTION_ROLES = ["Fuel Tracker Manager", "System Manager"];

function add_correct_reading_button(frm) {
    if (frm.doc.docstatus !== 1 || is_miscellaneous(frm) || frm.doc.meter_faulty) return;
    if (!["Truck", "Equipment"].includes(frm.doc.resource_type)) return;
    if (!READING_CORRECTION_ROLES.some((role) => frappe.user.has_role(role))) return;

    frm.add_custom_button(__("Correct Reading"), () => correct_reading_dialog(frm));
}

function correct_reading_dialog(frm) {
    const is_truck = frm.doc.resource_type === "Truck";
    const label = is_truck ? __("Odometer (KM)") : __("Hours");
    const recorded = is_truck ? frm.doc.odometer_km : frm.doc.hours_copy;
    const recorded_previous = is_truck ? frm.doc.previous_odometer_km : frm.doc.previous_hours_copy;
    // set in FuelUsed.onload; empty means this is the resource's first fill,
    // so its previous reading is the opening reading and is corrected here
    const previous_fill = (frm.doc.__onload || {}).previous_fill;

    const previous_field = previous_fill
        ? {
            fieldname: "previous_reading",
            label: __("Previous Reading"),
            fieldtype: "Float",
            default: recorded_previous,
            read_only: 1,
            description: __("This is the reading recorded on {0}. To change it, correct that fill.", [
                `<a href="/app/fuel-used/${encodeURIComponent(previous_fill)}">${frappe.utils.escape_html(previous_fill)}</a>`,
            ]),
        }
        : {
            fieldname: "previous_reading",
            label: __("Opening Reading"),
            fieldtype: "Float",
            default: recorded_previous,
            reqd: 1,
            description: __("This is the resource's first fill, so its previous reading is the opening reading the history starts from."),
        };

    const dialog = new frappe.ui.Dialog({
        title: __("Correct {0}", [label]),
        fields: [
            previous_field,
            {
                fieldname: "new_reading",
                label: __("Reading on This Fill"),
                fieldtype: "Float",
                default: recorded,
                reqd: 1,
                description: __("Must sit between the readings either side of this fill. No fuel moves; later fills are re-measured from it."),
            },
            {
                fieldname: "reason",
                label: __("Reason"),
                fieldtype: "Small Text",
                reqd: 1,
                description: __("e.g. digit mistyped, read from the wrong vehicle"),
            },
        ],
        primary_action_label: __("Correct"),
        primary_action(values) {
            const args = { new_reading: values.new_reading, reason: values.reason };
            if (!previous_fill) args.previous_reading = values.previous_reading;

            frm.call("correct_reading", args).then(() => {
                dialog.hide();
                frappe.show_alert({ message: __("Reading corrected"), indicator: "green" });
                frm.reload_doc();
            });
        },
    });
    dialog.show();
}
