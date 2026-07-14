// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Fuel Balance"] = {
    "filters": [
        {
            "fieldname": "date",
            "label": __("As At Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "width": "80",
            "reqd": 1
        },
        {
            "fieldname": "fuel_tanker",
            "label": __("Fuel Tanker"),
            "fieldtype": "MultiSelectList",
            "options": "Fuel Tanker",
            get_data: function(txt) {
                return frappe.db.get_link_options('Fuel Tanker', txt, {
                    // Additional filters can be applied here if needed
                });
            }
        },
        {
            "fieldname": "site",
            "label": __("Site"),
            "fieldtype": "MultiSelectList",
            "options": "Site",
            get_data: function(txt) {
                return frappe.db.get_link_options('Site', txt, {
                    // Additional filters can be applied here if needed
                });
            }
        },
    ],

	"formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        
        if (column.fieldname === "litres_supplied" && data.litres_supplied) {
            value = `<span style="color: green;">${value}</span>`;
        } else if (column.fieldname === "litres_dispensed" && data.litres_dispensed) {
            value = `<span style="color: red;">${value}</span>`;
        } else if (column.fieldname === "litres_adjusted" && data.litres_adjusted) {
            value = `<span style="color: ${data.litres_adjusted > 0 ? "green" : "red"};">${value}</span>`;
        } else if (column.fieldname === "status" && data.status) {
            if (data.status === "Low") {
                value = `<span style="color: white; background-color: red; padding: 2px 8px; border-radius: 3px; font-weight: bold;">${value}</span>`;
            } else {
                value = `<span style="color: green;">${value}</span>`;
            }
        }

        return value;
    }
};

