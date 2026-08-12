// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Fuel Supply Request Status"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
		},
		{
			"fieldname": "only_outstanding",
			"label": __("Only Outstanding"),
			"fieldtype": "Check",
			"default": 1,
		},
		{
			"fieldname": "status",
			"label": __("Status"),
			"fieldtype": "MultiSelectList",
			get_data: function () {
				return ["Pending", "Partially Supplied", "Fully Supplied"].map((v) => ({
					value: v,
					description: "",
				}));
			},
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
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "status") {
			const styles = {
				"Pending": "color: black; background-color: orange;",
				"Partially Supplied": "color: black; background-color: yellow;",
				"Fully Supplied": "color: white; background-color: green;",
			};
			const style = styles[data.status];
			if (style) {
				value = `<span style="${style} padding: 2px 8px; border-radius: 3px; font-weight: bold;">${value}</span>`;
			}
		} else if (column.fieldname === "overdue" && data.overdue) {
			value = `<span style="color: white; background-color: red; padding: 2px 8px; border-radius: 3px; font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === "pending_litres" && data.pending_litres) {
			value = `<span style="color: red;">${value}</span>`;
		}

		return value;
	},
};
