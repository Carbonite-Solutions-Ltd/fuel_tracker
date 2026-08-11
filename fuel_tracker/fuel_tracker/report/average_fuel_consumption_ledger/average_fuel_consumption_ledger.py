# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

#: Litres per km on a truck is a small number, so two decimals would round a
#: genuine reading away to zero and leave the row looking unscored.
PRECISION = 4


def score(entry, litres, distance, avg_consumption):
    """Consumption for one fill, and the band it falls in.

    Returns `(consumption, alert_status)`. Anything that cannot honestly be
    scored gets a status naming the reason rather than a zero that reads like
    a measurement — a blank or a 0.00 km/L is indistinguishable from a real
    result, and that is how bad meter data hides.
    """
    if entry.meter_faulty:
        # No reading was captured, so distance is unknown. Scoring this would
        # divide by a phantom zero and brand a healthy machine a fuel thief.
        return 0, _("Meter Faulty")

    if distance < 0:
        # The resource's reading went *down* between fills — a mis-keyed
        # odometer, a replaced meter, or two machines sharing a record.
        return 0, _("Check Reading")

    if not litres:
        # No earlier fill, so there is no tank-to-tank interval to measure.
        return 0, _("First Fill")

    if not distance:
        # Measured, but the resource had not moved: consumption is undefined
        # rather than zero.
        return 0, _("No Movement")

    consumption = flt(litres / distance, PRECISION)

    if avg_consumption <= 0:
        return consumption, _("No Baseline")

    # Below the baseline means burning less than expected, which is good.
    if consumption <= avg_consumption:
        return consumption, _("Good")

    variance_pct = ((consumption - avg_consumption) / avg_consumption) * 100
    if variance_pct > 20:
        return consumption, _("High Alert")
    if variance_pct > 10:
        return consumption, _("Warning")
    return consumption, _("Above Average")


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
            fe.meter_faulty,
            fu.odometer_km as current_odometer,
            fu.hours_copy as current_hours,
            (SELECT fe2.litres_dispensed
             FROM `tabFuel Entry` fe2
             WHERE fe2.resource = fe.resource
             AND fe2.utilization_type = 'Dispensed'
             AND fe2.docstatus = 1
             AND (fe2.posting_datetime < fe.posting_datetime
                  OR (fe2.posting_datetime = fe.posting_datetime AND fe2.creation < fe.creation))
             ORDER BY fe2.posting_datetime DESC, fe2.creation DESC
             LIMIT 1) as prev_litres_dispensed
        FROM `tabFuel Entry` fe
        LEFT JOIN `tabFuel Used` fu ON fu.name = fe.fuel_utilization_id
        WHERE fe.utilization_type = 'Dispensed'
        AND fe.docstatus = 1
        {conditions}
        ORDER BY fe.posting_datetime DESC, fe.creation DESC, fe.resource
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

        # Consumption is measured tank-to-tank: the litres put in at the
        # *previous* fill are what the resource burned covering the distance
        # recorded since that fill.
        litres = flt(entry.prev_litres_dispensed)
        avg_consumption = flt(entry.average_consumption)
        distance = flt(entry.diff_hours_copy if entry.resource_type == "Equipment" else entry.diff_odometer)

        consumption, alert = score(entry, litres, distance, avg_consumption)

        row["consumption"] = consumption
        row["alert_status"] = alert
        if consumption and avg_consumption > 0:
            row["variance"] = flt(consumption - avg_consumption, PRECISION)
            row["fuel_supposed_to_be_used"] = flt(avg_consumption * distance, 2)

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
