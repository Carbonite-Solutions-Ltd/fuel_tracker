// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Miscellaneous Fuel Register"] = {
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
			"fieldname": "site",
			"label": __("Site"),
			"fieldtype": "MultiSelectList",
			"options": "Site",
			get_data: function (txt) {
				return frappe.db.get_link_options("Site", txt, {});
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
			"fieldname": "include_cancelled",
			"label": __("Include Cancelled"),
			"fieldtype": "Check",
		},
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// the total row has no row data; leave it with the default formatting
		if (!data) return value;

		if (column.fieldname === "litres" && data.litres) {
			value = `<span style="color: red; font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === "status" && data.status === __("Cancelled")) {
			value = `<span style="color: white; background-color: gray; padding: 2px 8px; border-radius: 3px;">${value}</span>`;
		}

		// hovering the status shows the same one-line explanation as the column
		if (column.fieldname === "status" && data.status_note) {
			value = `<span title="${frappe.utils.escape_html(data.status_note)}">${value}</span>`;
		}

		return value;
	},
};
