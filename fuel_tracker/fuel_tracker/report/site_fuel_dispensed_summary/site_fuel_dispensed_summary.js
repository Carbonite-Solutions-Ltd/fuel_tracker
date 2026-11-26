// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Site Fuel Dispensed Summary"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_start(),
			"reqd": 1,
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 1,
		},
		{
			"fieldname": "site",
			"label": __("Site"),
			"fieldtype": "Link",
			"options": "Site",
		},
		{
			"fieldname": "resource_type",
			"label": __("Type"),
			"fieldtype": "Select",
			"options": "\nTruck\nEquipment\nOthers",
		},
		{
			"fieldname": "resource",
			"label": __("Reg. No / Machine"),
			"fieldtype": "MultiSelectList",
			"options": "Resource",
			get_data: function (txt) {
				return frappe.db.get_link_options("Resource", txt, {});
			},
		},
		{
			// the sheet lists the whole fleet, fuelled or not
			"fieldname": "show_idle",
			"label": __("Show Resources With No Fuel"),
			"fieldtype": "Check",
			"default": 1,
		},
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// the total row has no row data; leave it with the default formatting
		if (!data) return value;

		if (column.fieldname === "status") {
			const styles = {
				"High Alert": "color: white; background-color: red; font-weight: bold;",
				"Warning": "color: black; background-color: orange; font-weight: bold;",
				"Above Average": "color: black; background-color: yellow;",
				"Good": "color: white; background-color: green; font-weight: bold;",
				"Set Baseline": "color: white; background-color: #0984e3;",
				"Check Readings": "color: white; background-color: #d63031; font-weight: bold;",
				"Not Measurable": "color: #555; background-color: #eee;",
				"Not Metered": "color: #555; background-color: #eee;",
				"No Fuel Drawn": "color: #555; background-color: #eee;",
			};
			const style = styles[data.status];
			if (style) {
				value = `<span style="${style} padding: 2px 8px; border-radius: 3px;">${value}</span>`;
			}
			if (data.status_note) {
				value = `<span title="${frappe.utils.escape_html(data.status_note)}">${value}</span>`;
			}
		} else if (column.fieldname === "total_litres") {
			value = `<span style="font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === "variance" && data.variance) {
			value = `<span style="color: ${data.variance > 0 ? "red" : "green"};">${value}</span>`;
		}

		return value;
	},
};
