frappe.ui.form.on("Resource Movement", {
    refresh: function(frm) {
        frm.disable_save();
        frm.add_custom_button(__('Move'), function () {
            frm.trigger("move_resources");
        }).addClass('btn-primary');

        // Add a query filter to the "new_site" field
        frm.fields_dict.new_site.get_query = function(doc) {
            return {
                filters: {
                    "name": ["!=", doc.current_site] // Exclude the selected "current_site"
                }
            };
        };
    },

    move_resources: function(frm) {
        frappe.call({
            method: "fuel_tracker.fuel_tracker.doctype.resource_movement.resource_movement.move_resources",
            args: {
                doc: frm.doc
            },
            callback: function(r) {
                if (!r.exc) {
                    frappe.msgprint(__(`Items successfully moved from ${frm.doc.current_site} to ${frm.doc.new_site}.`));
                    frm.trigger("refresh_tables");
                }
            }
        });
    },

    refresh_tables: function(frm) {
        // Refresh current_resource_list
        frappe.call({
            method: "fuel_tracker.fuel_tracker.doctype.resource_movement.resource_movement.populate_current_resources",
            args: { current_site: frm.doc.current_site },
            callback: function(r) {
                if (r.message) {
                    frm.clear_table("current_resource_list");
                    $.each(r.message, function(_i, d) {
                        let row = frm.add_child("current_resource_list");
                        row.resource = d.resource;
                        row.type = d.custom_type;  // Added type
                        row.make = d.custom_make;  // Added make
                        row.registration = d.custom_reg_no;  // Added registration number
                    });
                    frm.refresh_field("current_resource_list");
                }
            }
        });

        // Refresh new_resource_list
        frappe.call({
            method: "fuel_tracker.fuel_tracker.doctype.resource_movement.resource_movement.populate_new_resources",
            args: { new_site: frm.doc.new_site },
            callback: function(r) {
                if (r.message) {
                    frm.clear_table("new_resource_list");
                    $.each(r.message, function(_i, d) {
                        let row = frm.add_child("new_resource_list");
                        row.resource = d.resource;
                        row.type = d.custom_type;  // Added type
                        row.make = d.custom_make;  // Added make
                        row.registration = d.custom_reg_no;  // Added registration number
                    });
                    frm.refresh_field("new_resource_list");
                }
            }
        });
    },

    current_site: function(frm) {
        if (!frm.doc.current_site) return;
        frappe.call({
            method: "fuel_tracker.fuel_tracker.doctype.resource_movement.resource_movement.populate_current_resources",
            args: { current_site: frm.doc.current_site },
            callback: function(r) {
                if (r.message) {
                    frm.clear_table("current_resource_list");
                    $.each(r.message, function(_i, d) {
                        let row = frm.add_child("current_resource_list");
                        row.resource = d.resource;
                        row.type = d.custom_type;  // Added type
                        row.make = d.custom_make;  // Added make
                        row.registration = d.custom_reg_no;  // Added registration number
                    });
                    frm.refresh_field("current_resource_list");
                }
            }
        });
    },

    new_site: function(frm) {
        if (!frm.doc.new_site) return;
        frappe.call({
            method: "fuel_tracker.fuel_tracker.doctype.resource_movement.resource_movement.populate_new_resources",
            args: { new_site: frm.doc.new_site },
            callback: function(r) {
                if (r.message) {
                    frm.clear_table("new_resource_list");
                    $.each(r.message, function(_i, d) {
                        let row = frm.add_child("new_resource_list");
                        row.resource = d.resource;
                        row.type = d.custom_type;  // Added type
                        row.make = d.custom_make;  // Added make
                        row.registration = d.custom_reg_no;  // Added registration number
                    });
                    frm.refresh_field("new_resource_list");
                }
            }
        });
    }
});
