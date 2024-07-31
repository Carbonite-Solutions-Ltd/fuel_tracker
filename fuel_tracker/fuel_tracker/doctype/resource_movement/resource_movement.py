import frappe
from frappe.model.document import Document

class ResourceMovement(Document):
    pass

@frappe.whitelist()
def populate_current_resources(current_site):
    items = frappe.get_list("Item", filters={"custom_stationed_site": current_site}, fields=["name as resource"])
    return items

@frappe.whitelist()
def populate_new_resources(new_site):
    items = frappe.get_list("Item", filters={"custom_stationed_site": new_site}, fields=["name as resource"])
    return items

@frappe.whitelist()
def move_resources(doc):
    doc = frappe.get_doc(frappe.parse_json(doc))
    if not doc.new_site:
        frappe.throw("Please select a new site to move the resources to.")

    # Check for the implicit selection using `__checked` attribute
    selected_items = [d.resource for d in doc.current_resource_list if d.get('__checked')]
    movement_date = doc.get("date") or frappe.utils.nowdate()  # Use provided date or current date

    for item_name in selected_items:
        item = frappe.get_doc("Item", item_name)
        old_site = item.custom_stationed_site

        # Update the custom_stationed_site of the item
        item.custom_stationed_site = doc.new_site
        item.save()

        # Create an entry in the Resource Movement Ledger
        ledger_entry = frappe.get_doc({
            "doctype": "Resource Movement Ledger",
            "old_site": old_site,
            "new_site": doc.new_site,
            "resource": item.name,
            "date": movement_date,  # Use the provided date or current date
        })
        ledger_entry.insert()

    frappe.msgprint(f"{len(selected_items)} items moved successfully.")
