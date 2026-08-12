// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Resource Fuel Summary"] = {
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
			"fieldname": "resource_type",
			"label": __("Resource Type"),
			"fieldtype": "Select",
			"options": "\nTruck\nEquipment\nOthers",
		},
		{
			"fieldname": "resource",
			"label": __("Resource"),
			"fieldtype": "MultiSelectList",
			"options": "Resource",
			get_data: function (txt) {
				return frappe.db.get_link_options("Resource", txt, {});
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
			// Shortlist for populating Average Consumption on the Resource
			"fieldname": "only_without_baseline",
			"label": __("Only Without Baseline"),
			"fieldtype": "Check",
		},
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "status") {
			const styles = {
				"High Alert": "color: white; background-color: red; font-weight: bold;",
				"Warning": "color: black; background-color: orange; font-weight: bold;",
				"Above Average": "color: black; background-color: yellow;",
				"Good": "color: white; background-color: green; font-weight: bold;",
				"Set Baseline": "color: white; background-color: #0984e3;",
				"Check Readings": "color: white; background-color: #d63031; font-weight: bold;",
				"Not Measurable": "color: #555; background-color: #eee;",
			};
			const style = styles[data.status];
			if (style) {
				value = `<span style="${style} padding: 2px 8px; border-radius: 3px;">${value}</span>`;
			}
		} else if (column.fieldname === "observed_consumption" && data.observed_consumption) {
			value = `<span style="font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === "variance_pct" && data.variance_pct) {
			value = `<span style="color: ${data.variance_pct > 0 ? "red" : "green"};">${value}</span>`;
		}

		return value;
	},
};
