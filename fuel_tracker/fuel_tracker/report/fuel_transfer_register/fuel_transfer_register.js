// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Fuel Transfer Register"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
		},
		{
			"fieldname": "fuel_tanker",
			"label": __("Fuel Tanker"),
			"fieldtype": "MultiSelectList",
			"options": "Fuel Tanker",
			get_data: function (txt) {
				return frappe.db.get_link_options("Fuel Tanker", txt, {});
			},
		},
		{
			"fieldname": "site",
			"label": __("Site"),
			"fieldtype": "MultiSelectList",
			"options": "Site",
			get_data: function (txt) {
				return frappe.db.get_link_options("Site", txt, {});
			},
		},
		{
			"fieldname": "include_cancelled",
			"label": __("Include Cancelled"),
			"fieldtype": "Check",
		},
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "route" && data.route === __("Cross-site")) {
			value = `<span style="color: #0984e3; font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === "status" && data.status === __("Cancelled")) {
			value = `<span style="color: white; background-color: gray; padding: 2px 8px; border-radius: 3px;">${value}</span>`;
		} else if (column.fieldname === "litres_transferred") {
			value = `<span style="font-weight: bold;">${value}</span>`;
		}

		return value;
	},
};
