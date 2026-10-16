// Copyright (c) 2026, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Executive Fuel Summary"] = {
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
			"default": frappe.datetime.get_today(),
			"reqd": 1,
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
	],

	// sites are the top rows and open onto their tankers
	"tree": true,
	"name_field": "entity",
	"parent_field": "parent_entity",
	"initial_depth": 1,

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// the total row has no row data; leave it with the default formatting
		if (!data) return value;

		if (column.fieldname === "status" && data.status) {
			const styles = {
				"OK": "color: white; background-color: green;",
				"Low": "color: black; background-color: orange; font-weight: bold;",
				"Negative": "color: white; background-color: red; font-weight: bold;",
				"Check Ledger": "color: white; background-color: red; font-weight: bold;",
			};
			const style = styles[data.status] || "";
			value = `<span title="${frappe.utils.escape_html(data.status_note || "")}" style="${style} padding: 2px 8px; border-radius: 3px;">${value}</span>`;
		} else if (["litres_supplied", "transferred_in"].includes(column.fieldname) && data[column.fieldname]) {
			value = `<span style="color: green;">${value}</span>`;
		} else if (["litres_dispensed", "litres_miscellaneous", "transferred_out"].includes(column.fieldname) && data[column.fieldname]) {
			value = `<span style="color: red;">${value}</span>`;
		} else if (column.fieldname === "current_balance" && data.current_balance < 0) {
			value = `<span style="color: red; font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === "days_of_stock" && data.days_of_stock) {
			// under a week of stock left at the period's rate of use is urgent
			if (data.days_of_stock < 7) {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else if (data.days_of_stock < 14) {
				value = `<span style="color: orange; font-weight: bold;">${value}</span>`;
			}
		} else if (column.fieldname === "consumption_alerts" && data.consumption_alerts) {
			value = `<span style="color: white; background-color: red; padding: 2px 8px; border-radius: 3px;">${value}</span>`;
		}

		// site rows read as headings
		if (data.indent === 0 && column.fieldname === "entity") {
			value = `<b>${value}</b>`;
		}

		return value;
	},
};
