# Copyright (c) 2026, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

"""Every fill, scored tank-to-tank against the resource's baseline.

The scoring itself lives in `fuel_tracker.consumption`, shared with the
Resource Fuel Summary so the two can never disagree. This report shows it
fill by fill: the litres put in since the previous metered fill over the
distance recorded since, and the band that figure falls in.
"""

import frappe
from frappe import _
from frappe.utils import flt

from fuel_tracker.fuel_tracker.consumption import PRECISION, as_list, get_fills, in_period, status_note


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {
            "fieldname": "alert_status",
            "label": _("Alert"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "status_note",
            "label": _("What It Means"),
            "fieldtype": "Data",
            "width": 380
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
            "precision": 2,
            "width": 150
        },
        {
            "fieldname": "diff_hours",
            "label": _("Difference in Hours"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 200
        },
        {
            "fieldname": "previous_odometer",
            "label": _("Previous Odometer (KM)"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 200
        },
        {
            "fieldname": "current_odometer",
            "label": _("Current Odometer (KM)"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 200
        },
        {
            "fieldname": "kilometers",
            "label": _("Kilometers"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 150
        },
        {
            "fieldname": "litres_dispensed",
            "label": _("Previous Litres Dispensed"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 200
        },
        {
            "fieldname": "fuel_supposed_to_be_used",
            "label": _("Fuel Supposed to be Used"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 200
        },
        {
            "fieldname": "consumption",
            "label": _("Consumption"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 150
        },
        {
            "fieldname": "average_consumption",
            "label": _("Average Consumption"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 200
        },
        {
            "fieldname": "variance",
            "label": _("Variance"),
            "fieldtype": "Float",
            "precision": 2,
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
    # The walk needs each resource's whole history up to the end of the
    # period — the first fill in the window is scored with fuel put in
    # before it — so only resource-level filters narrow the query; the
    # period, site and tanker filters pick which scored fills are shown.
    fills = get_fills(
        resource=filters.get("resource"),
        resource_type=filters.get("resource_type"),
        to_date=filters.get("to_date"),
    )
    sites = set(as_list(filters.get("site"))) if filters.get("site") else None
    tankers = set(as_list(filters.get("fuel_tanker"))) if filters.get("fuel_tanker") else None

    result = []
    for fill in fills:
        if not in_period(fill, filters.get("from_date"), filters.get("to_date")):
            continue
        if sites and fill.site not in sites:
            continue
        if tankers and fill.fuel_tanker not in tankers:
            continue

        baseline = flt(fill.average_consumption)
        row = {
            "date": fill.date,
            "resource": fill.resource,
            "resource_type": fill.resource_type,
            "site": fill.site,
            "fuel_tanker": fill.fuel_tanker,
            "utilization_type": fill.utilization_type,
            "current_hours": flt(fill.hours_copy),
            "diff_hours": flt(fill.diff_hours_copy),
            "previous_odometer": flt(fill.odometer_km) - flt(fill.diff_odometer),
            "current_odometer": flt(fill.odometer_km),
            "kilometers": flt(fill.diff_odometer),
            "litres_dispensed": flt(fill.litres),
            "fuel_supposed_to_be_used": 0,
            "consumption": fill.consumption,
            # the live baseline, so one set after the fact applies to history
            "average_consumption": baseline,
            "variance": 0,
            "reference_document": fill.fuel_utilization_id,
            "alert_status": fill.status,
            "status_note": status_note(fill.status),
            "posting_datetime": fill.posting_datetime,
            "creation": fill.creation,
        }

        if fill.scored and baseline > 0:
            row["variance"] = flt(fill.consumption - baseline, PRECISION)
            row["fuel_supposed_to_be_used"] = flt(baseline * fill.distance, 2)

        result.append(row)

    result.sort(key=lambda r: (r["posting_datetime"], r["creation"]), reverse=True)
    return result
