import frappe
from frappe import _



# ? Function To Create a new document in Fuel Used
@frappe.whitelist(allow_guest=True)
def fuel_used():
    """
    Create a new document in the "Fuel Used" doctype with the provided data.

    The data is expected to be passed as JSON in the request body.
    """
    try:
        # Parse the incoming JSON payload
        request_data = frappe.request.get_data(as_text=True)
        if not request_data:
            frappe.throw(_("Missing required data in request"))

        # Convert JSON string to dictionary
        data = frappe.parse_json(request_data)

        # Create a new document using the correct fieldnames
        doc = frappe.get_doc({
            "doctype": "Fuel Used",
            "date": data.get("date"),
            "fuel_tanker": data.get("fuel_tanker"),
            "resource": data.get("resource"),
            "site": data.get("site"),
            "fuel_issued_lts": float(data.get("fuel_used", 0)),  # Update fieldname here
            "requisition_number": data.get("requisition_number"),
            "review_status":"Incoming Report"
        })

        # Insert the document into the database
        doc.insert()
        frappe.db.commit()

        # Return success response
        return {
            "status": "success",
            "message": "Fuel Used document created successfully",
            "docname": doc.name,
        }
    except Exception as e:
        frappe.log_error(message=str(e), title="Fuel Used API Error")
        frappe.throw(_("An error occurred while creating the document: {0}").format(str(e)))



  
# ? Function to delete document based on document name
@frappe.whitelist(allow_guest=True)
def delete_fuel_used_document():
    """
    Delete a document in the "Fuel Used" doctype based on the provided document name (ID).

    The document name is expected to be passed as a JSON key in the request body.
    """
    try:
        # Parse the incoming JSON payload
        request_data = frappe.request.get_data(as_text=True)
        if not request_data:
            frappe.throw(_("Missing required data in request"))

        # Convert JSON string to dictionary
        data = frappe.parse_json(request_data)

        # Get the document name (ID) from the request data
        docname = data.get("docname")
        if not docname:
            frappe.throw(_("Document name (ID) is required"))

        # Check if the document exists
        if not frappe.db.exists("Fuel Used", docname):
            frappe.throw(_("Document with name {0} does not exist").format(docname))

        # Delete the document
        frappe.delete_doc("Fuel Used", docname)
        frappe.db.commit()

        # Return success response
        return {
            "status": "success",
            "message": "Fuel Used document deleted successfully",
            "docname": docname,
        }
    except Exception as e:
        frappe.log_error(message=str(e), title="Delete Fuel Used API Error")
        frappe.throw(_("An error occurred while deleting the document: {0}").format(str(e)))




# ? Function to get the list of fuel tanker
@frappe.whitelist(allow_guest=True)
def get_fuel_tankers():
    """
    Fetch a list of all documents in the "Fuel Tanker" doctype and return the "tanker" field.
    """
    try:
        # Fetch all documents in the "Fuel Tanker" doctype
        tankers = frappe.get_all("Fuel Tanker", fields=["name"])

        # Return the list of tankers
        return {
            "status": "success",
            "data": tankers,
        }
    except Exception as e:
        # Log the error and return a failure response
        frappe.log_error(message=str(e), title="Get Fuel Tankers API Error")
        frappe.throw(_("An error occurred while fetching the Fuel Tankers: {0}").format(str(e)))




# ? Function To get THe Fixex Asset Truck From The List
@frappe.whitelist(allow_guest=True)
def get_filtered_items():
    """
    Fetch a list of items from the "Items" doctype with specific filters:
    - custom_resource_type is set (not null or empty)
    - is_fixed_asset is 1 (true)
    """
    try:
        # Define the filters
        filters = [
            ["Item", "custom_resource_type", "is", "set"],
            ["Item", "is_fixed_asset", "=", 1]
        ]

        # Fetch filtered items
        items = frappe.get_list(
            "Item",
            filters=filters,
            fields=["name", "item_code", "item_name", "custom_resource_type", "is_fixed_asset"]
        )

        # Return the filtered items
        return {
            "status": "success",
            "data": items,
        }
    except Exception as e:
        # Log the error and return a failure response
        frappe.log_error(message=str(e), title="Get Filtered Items API Error")
        frappe.throw(_("An error occurred while fetching the filtered items: {0}").format(str(e)))




# ? Function to get the list of fuel tanker
@frappe.whitelist(allow_guest=True)
def get_site():
    """
    Fetch a list of Sites in the "Fuel Tanker" doctype.
    """
    try:
        # Fetch all documents in the "Fuel Tanker" doctype
        site = frappe.get_all("Site", fields=["site_name"])

        # Return the list of tankers
        return {
            "status": "success",
            "data": site,
        }
    except Exception as e:
        # Log the error and return a failure response
        frappe.log_error(message=str(e), title="Get Fuel Sites API Error")
        frappe.throw(_("An error occurred while fetching the Fuel Sites: {0}").format(str(e)))




#  ? Function to get list of Fuel Used
@frappe.whitelist(allow_guest=True)
def fuel_list():
    """
    Fetch the list of all Fuel Used Documents
    """
    try:
        list = frappe.get_all("Fuel Used")

        return {
            "status": "success",
            "data": list,
        }
    except Exception as e:
        # Log the error and return a failure response
        frappe.log_error(message=str(e), title="Get Fuel List Documents Error")
        frappe.throw(_("An error occurred while fetching the Fuel Documents: {0}").format(str(e)))




#  ? Function to get list of Fuel Used Documents
@frappe.whitelist(allow_guest=True)
def get_all_fuel_used_records():
    # Fetch all records from the "Fuel Used" DocType with all fields
    fuel_used_records = frappe.get_all(
        "Fuel Used",  # The DocType name
        fields=["*"],  # Fetch all fields
        filters={},    # No filters, fetch all records
        order_by="creation"  # Optional: Order by creation date
    )
    
    return fuel_used_records


# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.fuel_used
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.delete_fuel_used_document
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.get_fuel_tankers
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.get_filtered_items
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.get_site
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.fuel_list
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.fuel_used.get_all_fuel_used_records