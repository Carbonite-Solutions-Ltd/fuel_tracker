import frappe
from frappe import _

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
    

@frappe.whitelist()
def submit_fuel_used(data):
    try:
        # Assuming `data` is a JSON string representing the document to be created and submitted
        doc_data = frappe.parse_json(data)
        doc = frappe.get_doc(doc_data)
        doc.insert()
        doc.save()
        doc.submit()
        return {'message': 'Successfully submitted Fuel Used', 'docname': doc.name}
    except Exception as e:
        frappe.log_error(message=str(e), title="Fuel Used Submission Error")
        return {'error': str(e)}
