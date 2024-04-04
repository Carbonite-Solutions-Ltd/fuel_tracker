import frappe
from frappe import _
from frappe.model.document import Document

@frappe.whitelist(allow_guest=True)
def get_fuel_tanker_options():
    tankers = frappe.get_all('Fuel Tanker', fields=['name as value', 'name as label'])
    return tankers

@frappe.whitelist(allow_guest=True)
def get_site_options():
    sites = frappe.get_all('Site', fields=['name as value', 'name as label'])
    return sites

@frappe.whitelist(allow_guest=True)
def get_resources():
    try:
        resources = frappe.get_all('Resource', fields=['name as label', 'name as value'])
        return resources
    except Exception as e:
        frappe.log_error(f"Error fetching resources: {str(e)}", "get_resources")
        return {'message': f"Error: {str(e)}"}

@frappe.whitelist(allow_guest=True)
def get_resource_details(resource_name):
    try:
        resource_details = frappe.db.get_value('Resource', {'name': resource_name}, ['reg_no', 'resource_type', 'make', 'type'], as_dict=True)
        if resource_details:
            return resource_details
        else:
            return {'message': 'No details found for the selected resource.'}
    except Exception as e:
        frappe.log_error(f"Error fetching resource details: {str(e)}", "get_resource_details")
        return {'message': f"Error: {str(e)}"}
    








@frappe.whitelist(allow_guest=True)
def create_and_submit_fuel_used(site, fuel_tanker, resource, odometer_km, fuel_issued_lts, date):
    # Set the user as Administrator
    frappe.set_user("Administrator")

    # Create a new Fuel Used document
    doc = frappe.get_doc({
        'doctype': 'Fuel Used',
        'site': site,
        'fuel_tanker': fuel_tanker,
        'resource': resource,
        'odometer_km': odometer_km,
        'fuel_issued_lts': fuel_issued_lts,
        'date': date
    })

    # Insert the new document into the database
    doc.insert(ignore_permissions=True)

    # Submit the document to save it permanently
    doc.submit()

    # Check if the docstatus is 1, which means it is submitted
    if doc.docstatus == 1:
        return {"message": "Fuel entry submitted successfully."}
    else:
        # Log for debugging purposes
        frappe.log_error('Document was created but not submitted.', 'create_and_submit_fuel_used Error')
        return {"error": "Fuel entry failed."}


#get list of sites
@frappe.whitelist(allow_guest=True)
def sitelist():
    site = frappe.get_all("Site", fields=["name", "site_name",] )

    frappe.response['message'] = site

#get list of resource
@frappe.whitelist(allow_guest=True)
def resourcelist():
    resource = frappe.get_all("Resource", fields=["name", "reg_no"])

    frappe.response['message'] = resource


#get list of tanker
@frappe.whitelist(allow_guest=True)
def tankerlist():
    tanker = frappe.get_all("Fuel Tanker", fields=["name", "tanker"])

    frappe.response['message'] = tanker


#get sum of fuel used
@frappe.whitelist(allow_guest=True)
def totalfuelused():
    total_fuel_issued = frappe.db.sql("""
        SELECT SUM(fuel_issued_lts) as total_issued
        FROM `tabFuel Used`
        WHERE docstatus = 1
    """, as_dict=True)

    if total_fuel_issued:
        frappe.response['message'] = total_fuel_issued[0].get("total_issued", 0)
    else:
        frappe.response['message'] = 0


#get sum of fuel supplied
@frappe.whitelist(allow_guest=True)
def totalfuelsupplied():
    total_fuel_supplied = frappe.db.sql("""
        SELECT SUM(fuel_supplied) as total_supplied
        FROM `tabFuel Supplied`
        WHERE docstatus = 1
    """, as_dict=True)

    if total_fuel_supplied:
        frappe.response['message'] = total_fuel_supplied[0].get("total_supplied", 0)
    else:
        frappe.response['message'] = 0


#get sum of fuel balance
@frappe.whitelist(allow_guest=True)
def totalfuelbalance():
    total_fuel_balance_sum = frappe.db.sql("""
        SELECT SUM(balance) as total_balance
        FROM `tabFuel Balance`
        WHERE docstatus = 1
    """, as_dict=True)

    if total_fuel_balance_sum:
        frappe.response['message'] = total_fuel_balance_sum[0].get("total_balance", 0)
    else:
        frappe.response['message'] = 0

