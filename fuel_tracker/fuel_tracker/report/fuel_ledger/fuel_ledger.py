import frappe

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    """Returns the columns for the report."""
    columns = [
        {"label": "Date", "fieldname": "date", "fieldtype": "Date", "width": 100},
        {"label": "Site", "fieldname": "site", "fieldtype": "Link", "options": "Site", "width": 100},
        {"label": "Utilization Type", "fieldname": "utilization_type", "fieldtype": "Data", "width": 120},
        {"label": "Fuel Tanker", "fieldname": "fuel_tanker", "fieldtype": "Link", "options": "Fuel Tanker", "width": 100},
        {"label": "Resource Type", "fieldname": "resource_type", "fieldtype": "Data", "width": 120},
        {"label": "Resource", "fieldname": "resource", "fieldtype": "Link", "options": "Resource", "width": 100},
        {"label": "Litres Supplied", "fieldname": "litres_supplied", "fieldtype": "Float", "width": 100},
        {"label": "Litres Dispensed", "fieldname": "litres_dispensed", "fieldtype": "Float", "width": 110},
        {"label": "Previous Balance", "fieldname": "previous_balance", "fieldtype": "Float", "width": 120},
        {"label": "Current Balance", "fieldname": "current_balance", "fieldtype": "Float", "width": 120},
        {"label": "Transaction ID", "fieldname": "transaction_id", "fieldtype": "Dynamic Link", "options": "dynamic_link", "width": 150}
    ]
    return columns

def get_data(filters):
    """Fetches the data based on filters."""
    conditions = get_conditions(filters)
    data = frappe.db.sql(f"""
        SELECT
            fe.date, fe.site, fe.utilization_type, fe.fuel_tanker,
            fu.resource_type, fu.resource, fe.litres_supplied, fe.litres_dispensed,
            fe.previous_balance, fe.current_balance,
            CASE
                WHEN fe.utilization_type = 'Supplied' THEN fe.fuel_supplied_id
                WHEN fe.utilization_type = 'Dispensed' THEN fe.fuel_utilization_id
            END AS transaction_id,
            'Fuel Used' AS dynamic_link
        FROM
            `tabFuel Entry` fe
        LEFT JOIN
            `tabFuel Used` fu ON fe.fuel_utilization_id = fu.name
        WHERE
            {conditions}
        """, filters, as_dict=1)
    for row in data:
        row["dynamic_link"] = "Fuel Used" if row["utilization_type"] == "Dispensed" else "Fuel Supplied"
        if row["litres_supplied"]:
            row["litres_supplied_style"] = "color: green;"
        if row["litres_dispensed"]:
            row["litres_dispensed_style"] = "color: red;"
    return data

def get_conditions(filters):
    """Returns SQL conditions based on filters."""
    conditions = "1=1"
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
    return conditions
