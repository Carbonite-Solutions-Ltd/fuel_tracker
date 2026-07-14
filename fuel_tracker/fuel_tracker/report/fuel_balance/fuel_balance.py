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
        {"label": _("AS @ Date"), "fieldname": "date", "fieldtype": "Date", "width": 200},
        {"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 220},
        {"label": _("Fuel Tanker"), "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 200},
        {"label": _("Opening Balance"), "fieldname": "opening_balance", "fieldtype": "Float", "width": 180},
        {"label": _("Liters Supplied"), "fieldname": "litres_supplied", "fieldtype": "Float", "width": 200},
        {"label": _("Liters Dispensed"), "fieldname": "litres_dispensed", "fieldtype": "Float", "width": 200},
        {"label": _("Liters Adjusted"), "fieldname": "litres_adjusted", "fieldtype": "Float", "width": 200},
        {"label": _("Current Balance"), "fieldname": "current_balance", "fieldtype": "Float", "width": 200},
    ]
    return columns

def get_data(filters):
    conditions = get_conditions(filters)
    # Opening Balance entries carry their amount in current_balance (not in
    # litres_supplied/litres_dispensed), so the balance must start from them
    # to tally with the Fuel Balance doctype.
    data = frappe.db.sql(f"""
        SELECT
            MAX(fe.date) as date,
            fe.site,
            fe.fuel_tanker,
            SUM(CASE WHEN fe.utilization_type = 'Opening Balance' THEN COALESCE(fe.current_balance, 0) ELSE 0 END) as opening_balance,
            COALESCE(SUM(fe.litres_supplied), 0) as litres_supplied,
            COALESCE(SUM(fe.litres_dispensed), 0) as litres_dispensed,
            COALESCE(SUM(fe.litres_adjusted), 0) as litres_adjusted,
            (SUM(CASE WHEN fe.utilization_type = 'Opening Balance' THEN COALESCE(fe.current_balance, 0) ELSE 0 END)
                + COALESCE(SUM(fe.litres_supplied), 0)
                - COALESCE(SUM(fe.litres_dispensed), 0)
                + COALESCE(SUM(fe.litres_adjusted), 0)) as current_balance
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
    # Only submitted entries move the balance; drafts and cancelled entries
    # (docstatus 0/2) must never count towards it.
    conditions = "fe.docstatus = 1"

    if filters.get("date"):
        conditions += " AND fe.date <= %(date)s"
    if filters.get("fuel_tanker"):
        conditions += " AND fe.fuel_tanker IN %(fuel_tanker)s"
    if filters.get("site"):
        conditions += " AND fe.site IN %(site)s"

    return conditions
