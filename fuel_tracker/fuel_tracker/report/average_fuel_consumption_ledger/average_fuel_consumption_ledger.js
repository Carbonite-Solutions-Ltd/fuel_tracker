// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Average Fuel Consumption Ledger"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			"reqd": 0
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 0
		},
		{
			"fieldname": "resource",
			"label": __("Resource"),
			"fieldtype": "Link",
			"options": "Resource",
			"reqd": 0
		},
		{
			"fieldname": "resource_type",
			"label": __("Resource Type"),
			"fieldtype": "Select",
			"options": "\nTruck\nEquipment\nOthers",
			"reqd": 0
		},
		{
			"fieldname": "site",
			"label": __("Site"),
			"fieldtype": "Link",
			"options": "Site",
			"reqd": 0
		},
		{
			"fieldname": "fuel_tanker",
			"label": __("Fuel Tanker"),
			"fieldtype": "Link",
			"options": "Fuel Tanker",
			"reqd": 0
		}
	],
	"formatter": function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname == "alert_status" && data.alert_status) {
			// Scored bands carry a colour; the "cannot be scored" statuses are
			// deliberately neutral so they read as missing data, not as a result.
			const styles = {
				"High Alert": "color: white; background-color: red; font-weight: bold;",
				"Warning": "color: black; background-color: orange; font-weight: bold;",
				"Above Average": "color: black; background-color: yellow;",
				"Good": "color: white; background-color: green; font-weight: bold;",
				"No Baseline": "color: white; background-color: gray;",
				"First Fill": "color: #555; background-color: #eee;",
				"No Movement": "color: #555; background-color: #eee;",
				"Meter Faulty": "color: white; background-color: #6c5ce7;",
				"Check Reading": "color: white; background-color: #d63031; font-weight: bold;",
			};
			const style = styles[data.alert_status];
			if (style) {
				value = `<span style='${style} padding: 2px 8px; border-radius: 3px;'>${value}</span>`;
			}
		}

		return value;
	}
};
