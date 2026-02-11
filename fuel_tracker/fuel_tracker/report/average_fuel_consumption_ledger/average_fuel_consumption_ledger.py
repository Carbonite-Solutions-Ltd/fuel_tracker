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
            "fieldname": "current_hours",
            "label": _("Current Hours"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "diff_hours",
            "label": _("Difference in Hours"),
            "fieldtype": "Float",
            "width": 200
        },
        {
            "fieldname": "previous_odometer",
            "label": _("Previous Odometer (KM)"),
            "fieldtype": "Float",
            "width": 200
        },
        {
            "fieldname": "current_odometer",
            "label": _("Current Odometer (KM)"),
            "fieldtype": "Float",
            "width": 200
        },
        {
            "fieldname": "kilometers",
            "label": _("Kilometers"),
            "fieldtype": "Float",
            "width": 150
        },
        {
            "fieldname": "litres_dispensed",
            "label": _("Previous Litres Dispensed"),
            "fieldtype": "Float",
            "width": 200
        },
        {
            "fieldname": "fuel_supposed_to_be_used",
            "label": _("Fuel Supposed to be Used"),
            "fieldtype": "Float",
            "width": 200
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
            "width": 200
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
            fe.name,
            fe.date,
            fe.resource,
            fe.resource_type,
            fe.site,
            fe.fuel_tanker,
            fe.utilization_type,
            fe.diff_hours_copy,
            fe.diff_odometer,
            fe.litres_dispensed,
            fe.average_consumption,
            fe.fuel_utilization_id,
            fu.odometer_km as current_odometer,
            fu.hours_copy as current_hours,
            (SELECT fe2.litres_dispensed
             FROM `tabFuel Entry` fe2
             WHERE fe2.resource = fe.resource
             AND fe2.utilization_type = 'Dispensed'
             AND fe2.docstatus = 1
             AND (fe2.date < fe.date OR (fe2.date = fe.date AND fe2.name < fe.name))
             ORDER BY fe2.date DESC, fe2.name DESC
             LIMIT 1) as prev_litres_dispensed
        FROM `tabFuel Entry` fe 
        LEFT JOIN `tabFuel Used` fu ON fu.name = fe.fuel_utilization_id
        WHERE fe.utilization_type = 'Dispensed'
        AND fe.docstatus = 1
        {conditions}
        ORDER BY fe.date DESC, fe.resource
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
            "current_hours": entry.current_hours or 0,
            "diff_hours": entry.diff_hours_copy or 0,
            "previous_odometer": (entry.current_odometer or 0) - (entry.diff_odometer or 0),
            "current_odometer": entry.current_odometer or 0,
            "kilometers": entry.diff_odometer or 0,
            "litres_dispensed": entry.prev_litres_dispensed or 0,
            "fuel_supposed_to_be_used": 0,
            "consumption": 0,
            "average_consumption": entry.average_consumption or 0,
            "variance": 0,
            "reference_document": entry.fuel_utilization_id,
            "alert_status": ""
        }

        litres = entry.prev_litres_dispensed or 0
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

        # Calculate fuel supposed to be used (average * hours/km)
        fuel_supposed = 0
        if avg_consumption > 0:
            if entry.resource_type == "Equipment":
                diff_hours = entry.diff_hours_copy or 0
                if diff_hours > 0:
                    fuel_supposed = round(avg_consumption * diff_hours, 2)
            elif entry.resource_type == "Truck":
                diff_km = entry.diff_odometer or 0
                if diff_km > 0:
                    fuel_supposed = round(avg_consumption * diff_km, 2)
        row["fuel_supposed_to_be_used"] = fuel_supposed

        row["consumption"] = consumption

        # Calculate variance (consumption - average)
        if avg_consumption > 0:
            row["variance"] = round(consumption - avg_consumption, 2)

        # Set alert status
        # If consumption <= average_consumption = Good (using less fuel)
        # If consumption > average_consumption = Alert (using more fuel than expected)
        if consumption > 0 and avg_consumption > 0:
            if consumption <= avg_consumption:
                row["alert_status"] = "Good"
            else:
                # consumption is above average - calculate how much above
                variance_pct = ((consumption - avg_consumption) / avg_consumption) * 100
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
        conditions += " AND fe.date >= %(from_date)s"

    if filters.get("to_date"):
        conditions += " AND fe.date <= %(to_date)s"

    if filters.get("resource"):
        conditions += " AND fe.resource = %(resource)s"

    if filters.get("resource_type"):
        conditions += " AND fe.resource_type = %(resource_type)s"

    if filters.get("site"):
        conditions += " AND fe.site = %(site)s"

    if filters.get("fuel_tanker"):
        conditions += " AND fe.fuel_tanker = %(fuel_tanker)s"

    return conditions
