# Copyright (c) 2024, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    """Defines the columns for the report."""
    columns = [
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
        {"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 150},
        {"label": _("Fuel Tanker"), "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 150},
        {"label": _("Liters Supplied"), "fieldname": "litres_supplied", "fieldtype": "Float", "width": 120},
        {"label": _("Liters Dispensed"), "fieldname": "litres_dispensed", "fieldtype": "Float", "width": 120},
        {"label": _("Current Balance"), "fieldname": "current_balance", "fieldtype": "Float", "width": 120},
    ]
    return columns

def get_data(filters):
    conditions = get_conditions(filters)
    data = frappe.db.sql(f"""
        SELECT
            MAX(fe.date) as date,
            fe.site,
            fe.fuel_tanker,
            SUM(fe.litres_supplied) as litres_supplied,
            SUM(fe.litres_dispensed) as litres_dispensed,
            (SUM(fe.litres_supplied) - SUM(fe.litres_dispensed)) as current_balance
        FROM
            `tabFuel Entry` fe
        WHERE
            {conditions}
        GROUP BY
            fe.site, fe.fuel_tanker
        ORDER BY
            MAX(fe.date)
    """, filters, as_dict=1)
    for row in data:
        if row["litres_supplied"]:
            row["litres_supplied_style"] = "color: green;"
        if row["litres_dispensed"]:
            row["litres_dispensed_style"] = "color: red;"
    return data

def get_conditions(filters):
    conditions = "1=1"
    status_map = {"Draft": 0, "Submitted": 1}  # Map string values to integers

    if filters.get("from_date"):
        conditions += " AND fe.date >= %(from_date)s"
    if filters.get("to_date"):
        conditions += " AND fe.date <= %(to_date)s"
    if filters.get("fuel_tanker"):
        conditions += " AND fe.fuel_tanker IN %(fuel_tanker)s"
    if filters.get("site"):
        conditions += " AND fe.site IN %(site)s"
    if filters.get("docstatus"):
        # Map the string status to its corresponding docstatus integer
        docstatus_value = status_map.get(filters["docstatus"], None)
        if docstatus_value is not None:
            filters["docstatus"] = docstatus_value  # Update the filter to use the integer value
            conditions += " AND fe.docstatus = %(docstatus)s"
    else:
        # Optionally handle cases where no status is provided or an invalid status is provided
        pass

    return conditions
