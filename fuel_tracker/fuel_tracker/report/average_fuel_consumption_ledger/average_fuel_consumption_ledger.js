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

		if (column.fieldname == "alert_status") {
			if (data.alert_status == "High Alert") {
				value = "<span style='color: white; background-color: red; padding: 2px 8px; border-radius: 3px; font-weight: bold;'>" + value + "</span>";
			} else if (data.alert_status == "Warning") {
				value = "<span style='color: black; background-color: orange; padding: 2px 8px; border-radius: 3px; font-weight: bold;'>" + value + "</span>";
			} else if (data.alert_status == "Above Average") {
				value = "<span style='color: black; background-color: yellow; padding: 2px 8px; border-radius: 3px;'>" + value + "</span>";
			} else if (data.alert_status == "Good") {
				value = "<span style='color: white; background-color: green; padding: 2px 8px; border-radius: 3px; font-weight: bold;'>" + value + "</span>";
			} else if (data.alert_status == "No Baseline") {
				value = "<span style='color: white; background-color: gray; padding: 2px 8px; border-radius: 3px;'>" + value + "</span>";
			}
		}

		// Negative variance = good (consumption < average, more efficient)
		// Positive variance = bad (consumption > average, less efficient)
		if (column.fieldname == "variance" && data.variance > 0) {
			value = "<span style='color: red; font-weight: bold;'>" + value + "</span>";
		} else if (column.fieldname == "variance" && data.variance < 0) {
			value = "<span style='color: green;'>" + value + "</span>";
		}

		return value;
	}
};
