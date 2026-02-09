# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "fieldname": "alert_status",
            "label": _("Alert"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 150
        },
        {
            "fieldname": "resource",
            "label": _("Resource"),
            "fieldtype": "Link",
            "options": "Resource",
            "width": 150
        },
        {
            "fieldname": "resource_type",
            "label": _("Resource Type"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "site",
            "label": _("Site"),
            "fieldtype": "Link",
            "options": "Site",
            "width": 150
        },
        {
            "fieldname": "fuel_tanker",
            "label": _("Fuel Tanker"),
            "fieldtype": "Link",
            "options": "Fuel Tanker",
            "width": 150
        },
        {
            "fieldname": "utilization_type",
            "label": _("Utilization Type"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "diff_hours",
            "label": _("Difference in Hours"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "kilometers",
            "label": _("Kilometers"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "litres_dispensed",
            "label": _("Litres Dispensed"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "consumption",
            "label": _("Consumption"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "average_consumption",
            "label": _("Average Consumption"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "variance",
            "label": _("Variance"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "reference_document",
            "label": _("Reference Document"),
            "fieldtype": "Link",
            "options": "Fuel Used",
            "width": 150
        },
    ]


def get_data(filters):
    conditions = get_conditions(filters)

    entries = frappe.db.sql("""
        SELECT
            name,
            date,
            resource,
            resource_type,
            site,
            fuel_tanker,
            utilization_type,
            diff_hours_copy,
            diff_odometer,
            litres_dispensed,
            average_consumption,
            fuel_utilization_id
        FROM `tabFuel Entry`
        WHERE utilization_type = 'Dispensed'
        AND docstatus = 1
        {conditions}
        ORDER BY date DESC, resource
    """.format(conditions=conditions), filters, as_dict=1)

    result = []
    for entry in entries:
        row = {
            "date": entry.date,
            "resource": entry.resource,
            "resource_type": entry.resource_type,
            "site": entry.site,
            "fuel_tanker": entry.fuel_tanker,
            "utilization_type": entry.utilization_type,
            "diff_hours": entry.diff_hours_copy or 0,
            "kilometers": entry.diff_odometer or 0,
            "litres_dispensed": entry.litres_dispensed or 0,
            "consumption": 0,
            "average_consumption": entry.average_consumption or 0,
            "variance": 0,
            "reference_document": entry.fuel_utilization_id,
            "alert_status": ""
        }

        litres = entry.litres_dispensed or 0
        avg_consumption = entry.average_consumption or 0

        # Calculate consumption based on resource type
        consumption = 0
        if entry.resource_type == "Equipment":
            diff_hours = entry.diff_hours_copy or 0
            if diff_hours > 0 and litres > 0:
                consumption = round(litres / diff_hours, 2)
        elif entry.resource_type == "Truck":
            diff_km = entry.diff_odometer or 0
            if diff_km > 0 and litres > 0:
                consumption = round(litres / diff_km, 2)

        row["consumption"] = consumption

        # Calculate variance (consumption - average)
        if avg_consumption > 0:
            row["variance"] = round(consumption - avg_consumption, 2)

        # Set alert status
        # If consumption >= average_consumption = Good (efficient)
        # If consumption < average_consumption = Alert (using more fuel than expected)
        if consumption > 0 and avg_consumption > 0:
            if consumption >= avg_consumption:
                row["alert_status"] = "Good"
            else:
                # consumption is below average - calculate how much below
                variance_pct = ((avg_consumption - consumption) / avg_consumption) * 100
                if variance_pct > 20:
                    row["alert_status"] = "High Alert"
                elif variance_pct > 10:
                    row["alert_status"] = "Warning"
                else:
                    row["alert_status"] = "Above Average"
        elif consumption > 0:
            row["alert_status"] = "No Baseline"

        result.append(row)

    return result


def get_conditions(filters):
    conditions = ""

    if filters.get("from_date"):
        conditions += " AND date >= %(from_date)s"

    if filters.get("to_date"):
        conditions += " AND date <= %(to_date)s"

    if filters.get("resource"):
        conditions += " AND resource = %(resource)s"

    if filters.get("resource_type"):
        conditions += " AND resource_type = %(resource_type)s"

    if filters.get("site"):
        conditions += " AND site = %(site)s"

    if filters.get("fuel_tanker"):
        conditions += " AND fuel_tanker = %(fuel_tanker)s"

    return conditions
