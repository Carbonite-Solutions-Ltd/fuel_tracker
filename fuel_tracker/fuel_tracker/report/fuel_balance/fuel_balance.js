// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Fuel Balance"] = {
    "filters": [
		{
            "fieldname": "docstatus",
            "label": __("Status"),
            "fieldtype": "Select",
            "options": ["Submitted"], // Add options as per your doctype's status values
            "default": "Submitted",// Optionally set a default status
			"hidden": 1
        },
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
        }

        return value;
    }
};

