import frappe 

@frappe.whitelist(allow_guest=True)
def fuelBalance(site, fuel_tanker):
    try:
        from datetime import datetime
        current_date = datetime.now().date()
        
        # Get the last Fuel Entry document for current date, filtered by site and fuel_tanker
        balance = frappe.db.get_value("Fuel Entry", 
            {
                "date": current_date,
                "site": site,
                "fuel_tanker": fuel_tanker,
                "docstatus": 1  # Only submitted documents
            },
            "current_balance",
            order_by="modified desc"
        )
        
        return balance
    except Exception as e:
        frappe.log_error(message=str(e), title="Fuel Balance API Error")
        frappe.throw(_("An error occurred while fetching the Fuel Balance: {0}").format(str(e)))