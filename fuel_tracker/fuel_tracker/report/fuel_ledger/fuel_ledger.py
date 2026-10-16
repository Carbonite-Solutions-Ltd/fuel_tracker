import frappe

def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = get_columns()
    data = get_data(filters)

    # No hand-built total row: the report's own total row (add_total_row)
    # is pinned below the table and recomputes as rows are filtered in the
    # desk. Appending one here as well made the desk add it into its own
    # totals, doubling every figure. Running balances and meter readings
    # are excluded from it in get_columns — adding those up means nothing.
    return columns, data

def get_columns():
    """Returns the columns for the report."""
    columns = [
        {"label": "Date", "fieldname": "date", "fieldtype": "Date", "width": 110},
        {"label": "Time", "fieldname": "posting_time", "fieldtype": "Time", "width": 90},
        {"label": "Site", "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 150},
        {"label": "Utilization Type", "fieldname": "utilization_type", "fieldtype": "Data", "width": 150},
        {"label": "Fuel Tanker", "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 150},
        {"label": "Resource Type", "fieldname": "resource_type", "fieldtype": "Data", "width": 150},
        {"label": "Resource", "fieldname": "resource", "fieldtype": "Link", "options": "Resource", "width": 150},
        {"label": "Description", "fieldname": "description", "fieldtype": "Small Text", "width": 220},
        {"label": "Litres Supplied", "fieldname": "litres_supplied", "fieldtype": "Float", "precision": 2, "width": 150},
        {"label": "Litres Dispensed", "fieldname": "litres_dispensed", "fieldtype": "Float", "precision": 2, "width": 150},
        {"label": "Litres Adjusted", "fieldname": "litres_adjusted", "fieldtype": "Float", "precision": 2, "width": 150},
        {"label": "Previous Balance", "fieldname": "previous_balance", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
        {"label": "Current Balance", "fieldname": "current_balance", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
        {"label": "Previous Odometer", "fieldname": "previous_odometer_km", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
        {"label": "Current Odometer", "fieldname": "odometer_km", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
        {"label": "Kilometers", "fieldname": "diff_odometer", "fieldtype": "Float", "precision": 2, "width": 150},
        {"label": "Previous Hours", "fieldname": "previous_hours_copy", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
        {"label": "Current Hours", "fieldname": "hours_copy", "fieldtype": "Float", "precision": 2, "disable_total": 1, "width": 150},
        {"label": "Diff Hours", "fieldname": "diff_hours_copy", "fieldtype": "Float", "precision": 2, "width": 150},
        {"label": "Transaction ID", "fieldname": "name", "fieldtype": "Link", "options": "Fuel Entry", "width": 180}
    ]
    return columns

def get_data(filters):
    """Fetches the data based on filters.

    Ordered by tanker first, then posting moment. Previous/Current Balance are
    a *per-tanker* running balance, so a purely chronological order across
    several tankers would interleave unrelated balances and read as though the
    figures jumped about. Sort on the Date column in the UI for a fleet-wide
    chronological view.
    """
    conditions = get_conditions(filters)
    data = frappe.db.sql(f"""
        SELECT
            fe.date, fe.posting_time, fe.site, fe.utilization_type, fe.fuel_tanker,
            fu.resource_type, fu.resource, fu.reg_no, fu.description, fe.litres_supplied, fe.litres_dispensed, fe.litres_adjusted,
            fe.previous_balance, fe.current_balance, fu.previous_odometer_km, fu.odometer_km, fe.diff_odometer, fu.previous_hours_copy, fu.hours_copy, fe.diff_hours_copy, fe.name
        FROM
            `tabFuel Entry` fe
        LEFT JOIN
            `tabFuel Used` fu ON fe.fuel_utilization_id = fu.name
        LEFT JOIN
            `tabFuel Tanker` ft ON fe.fuel_tanker = ft.name
        WHERE
            {conditions}
        ORDER BY
            fe.fuel_tanker, fe.posting_datetime, fe.creation
        """, filters, as_dict=1)
    for row in data:
        if row["litres_supplied"]:
            row["litres_supplied_style"] = "color: green;"
        if row["litres_dispensed"]:
            row["litres_dispensed_style"] = "color: red;"
    return data

def get_conditions(filters):
    """Returns SQL conditions based on filters."""
    # Only submitted entries belong in the ledger; drafts and cancelled
    # entries (docstatus 0/2) must never appear.
    conditions = "fe.docstatus = 1"

    # Multi-select filters arrive as lists from the desk but as a plain
    # string from API calls and old saved filters; IN needs a tuple either way.
    for key in ("fuel_tanker", "site", "resource"):
        if filters.get(key) and not isinstance(filters[key], (list, tuple)):
            filters[key] = [filters[key]]

    if filters.get("from_date"):
        conditions += " AND fe.date >= %(from_date)s"
    if filters.get("to_date"):
        conditions += " AND fe.date <= %(to_date)s"
    if filters.get("fuel_tanker"):
        conditions += " AND fe.fuel_tanker IN %(fuel_tanker)s"
    if filters.get("site"):
        # The tanker's own site, as the Fuel Balance report uses. The site
        # keyed on each entry varies, so filtering on it would show part of a
        # tanker's running balance and leave the figures jumping between rows.
        conditions += " AND ft.site IN %(site)s"
    if filters.get("resource"):
        conditions += " AND fu.resource IN %(resource)s"
    if filters.get("utilization_type"):
        conditions += " AND fe.utilization_type = %(utilization_type)s"

    return conditions


