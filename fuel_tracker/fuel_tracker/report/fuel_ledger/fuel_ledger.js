frappe.query_reports["Fuel Ledger"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company"),
        },
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "width": "100px",
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "width": "100px",
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
        {
            "fieldname": "resource",
            "label": __("Resource"),
            "fieldtype": "MultiSelectList",
            "options": "Resource",
            get_data: function(txt) {
                return frappe.db.get_link_options('Resource', txt, {
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
