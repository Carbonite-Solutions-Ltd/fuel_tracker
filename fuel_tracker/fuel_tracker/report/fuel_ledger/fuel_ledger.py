import frappe

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)

    # Add total row
    if data:
        total_row = {
            "date": None,
            "site": "Total",
            "utilization_type": None,
            "fuel_tanker": None,
            "resource_type": None,
            "resource": None,
            "litres_supplied": sum(row.get("litres_supplied") or 0 for row in data),
            "litres_dispensed": sum(row.get("litres_dispensed") or 0 for row in data),
            "previous_balance": None,
            "current_balance": None,
            "previous_odometer_km": None,
            "odometer_km": None,
            "diff_odometer": sum(row.get("diff_odometer") or 0 for row in data),
            "previous_hours_copy": None,
            "hours_copy": None,
            "diff_hours_copy": sum(row.get("diff_hours_copy") or 0 for row in data),
            "name": None
        }
        data.append(total_row)

    return columns, data

def get_columns():
    """Returns the columns for the report."""
    columns = [
        {"label": "Date", "fieldname": "date", "fieldtype": "Date", "width": 150},
        {"label": "Site", "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 150},
        {"label": "Utilization Type", "fieldname": "utilization_type", "fieldtype": "Data", "width": 150},
        {"label": "Fuel Tanker", "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 150},
        {"label": "Resource Type", "fieldname": "resource_type", "fieldtype": "Data", "width": 150},
        {"label": "Resource", "fieldname": "resource", "fieldtype": "Link", "options": "Resource", "width": 150},
        {"label": "Litres Supplied", "fieldname": "litres_supplied", "fieldtype": "Float", "width": 150},
        {"label": "Litres Dispensed", "fieldname": "litres_dispensed", "fieldtype": "Float", "width": 150},
        {"label": "Previous Balance", "fieldname": "previous_balance", "fieldtype": "Float", "width": 150},
        {"label": "Current Balance", "fieldname": "current_balance", "fieldtype": "Float", "width": 150},
        {"label": "Previous Odometer", "fieldname": "previous_odometer_km", "fieldtype": "Float", "width": 150},
        {"label": "Current Odometer", "fieldname": "odometer_km", "fieldtype": "Float", "width": 150},
        {"label": "Kilometers", "fieldname": "diff_odometer", "fieldtype": "Float", "width": 150},
        {"label": "Previous Hours", "fieldname": "previous_hours_copy", "fieldtype": "Float", "width": 150},
        {"label": "Current Hours", "fieldname": "hours_copy", "fieldtype": "Float", "width": 150},
        {"label": "Diff Hours", "fieldname": "diff_hours_copy", "fieldtype": "Float", "width": 150},
        {"label": "Transaction ID", "fieldname": "name", "fieldtype": "Link", "options": "Fuel Entry", "width": 180}
    ]
    return columns

def get_data(filters):
    """Fetches the data based on filters."""
    conditions = get_conditions(filters)
    data = frappe.db.sql(f"""
        SELECT
            fe.date, fe.site, fe.utilization_type, fe.fuel_tanker,
            fu.resource_type, fu.resource, fu.reg_no, fe.litres_supplied, fe.litres_dispensed,
            fe.previous_balance, fe.current_balance, fu.previous_odometer_km, fu.odometer_km, fe.diff_odometer, fu.previous_hours_copy, fu.hours_copy, fe.diff_hours_copy, fe.name
        FROM
            `tabFuel Entry` fe
        LEFT JOIN
            `tabFuel Used` fu ON fe.fuel_utilization_id = fu.name
        WHERE
            {conditions}
        """, filters, as_dict=1)
    for row in data:
        if row["litres_supplied"]:
            row["litres_supplied_style"] = "color: green;"
        if row["litres_dispensed"]:
            row["litres_dispensed_style"] = "color: red;"
    return data

def get_conditions(filters):
    """Returns SQL conditions based on filters."""
    conditions = "1=1"
    status_map = {"Submitted": 1}  # Map string values to integers

    if filters.get("from_date"):
        conditions += " AND fe.date >= %(from_date)s"
    if filters.get("to_date"):
        conditions += " AND fe.date <= %(to_date)s"
    if filters.get("fuel_tanker"):
        conditions += " AND fe.fuel_tanker IN %(fuel_tanker)s"
    if filters.get("site"):
        conditions += " AND fe.site IN %(site)s"
    if filters.get("resource"):
        conditions += " AND fu.resource IN %(resource)s"
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


