import frappe
from frappe.model.document import Document

class FuelEntry(Document):
    def on_submit(self):
        self.update_fuel_balance(submit=True)

    def on_cancel(self):
        self.cancel_linked_document()
        self.update_fuel_balance(submit=False)
        self.update_resource_usage_on_cancel()

    def cancel_linked_document(self):
        """
        Cancel the linked Fuel Supplied or Fuel Used document when the Fuel Entry is cancelled.
        """
        linked_docname = None
        linked_doctype = None

        if self.utilization_type == "Supplied" and self.fuel_supplied_id:
            linked_docname = self.fuel_supplied_id
            linked_doctype = "Fuel Supplied"
        elif self.utilization_type == "Dispensed" and self.fuel_utilization_id:
            linked_docname = self.fuel_utilization_id
            linked_doctype = "Fuel Used"

        if linked_docname and linked_doctype:
            # Fetch the linked document
            linked_doc = frappe.get_doc(linked_doctype, linked_docname)

            # Cancel the linked document if it is not already cancelled
            if linked_doc.docstatus == 1:  # 1 indicates submitted document
                linked_doc.cancel()
                frappe.db.commit()  # Ensure changes are committed to the database

    def update_fuel_balance(self, submit=True):
        # Fetch the existing Fuel Balance for the specified fuel_tanker
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])

        balance_entry = None
        if existing_balance:
            # Update the existing Fuel Balance
            balance_entry = frappe.get_doc("Fuel Balance", existing_balance[0].name)
            balance_entry.date = self.date
        else:
            # Or create a new Fuel Balance if none exists
            balance_entry = frappe.get_doc({
                "doctype": "Fuel Balance",
                "fuel_tanker": self.fuel_tanker,
                "balance": 0,  # Initialize with zero balance
                "site": self.site,
                "date": self.date,
            })
            balance_entry.insert()  # Insert new balance entry if creating for the first time

        if submit:
            # Adjust the balance based on whether fuel was supplied or utilized
            if self.utilization_type == "Supplied":
                balance_entry.balance += self.litres_supplied or 0
            elif self.utilization_type == "Dispensed":
                balance_entry.balance -= self.litres_dispensed or 0
        else:
            # Reverse the balance adjustment if the document is being cancelled
            if self.utilization_type == "Supplied":
                balance_entry.balance -= self.litres_supplied or 0
            elif self.utilization_type == "Dispensed":
                balance_entry.balance += self.litres_dispensed or 0

        balance_entry.save()

    def update_resource_usage_on_cancel(self):
        """
        Update the current_hours_copy or current_odometer of the resource when Fuel Entry is cancelled.
        """
        linked_docname = None

        if self.utilization_type == "Dispensed" and self.fuel_utilization_id:
            linked_docname = self.fuel_utilization_id

        if linked_docname:
            # Fetch the linked Fuel Used document
            fuel_used_doc = frappe.get_doc("Fuel Used", linked_docname)

            # Fetch the related resource
            resource = frappe.get_doc("Resource", fuel_used_doc.resource)

            # Update the appropriate field based on the resource type
            if fuel_used_doc.resource_type == "Truck":
                resource.current_odometer = fuel_used_doc.previous_odometer_km
            elif fuel_used_doc.resource_type == "Equipment":
                resource.current_hours_copy = fuel_used_doc.previous_hours_copy

            resource.save()
