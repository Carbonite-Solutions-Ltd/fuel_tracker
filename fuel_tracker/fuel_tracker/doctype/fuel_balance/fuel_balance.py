import frappe
from frappe.model.document import Document

class FuelBalance(Document):
    def on_submit(self):
        # Only call create_fuel_entry if fuel_utilization_type is not empty
        if self.fuel_utilization_type:
            self.create_fuel_entry()

    def on_update_after_submit(self):
        # Similarly, only call create_fuel_entry on updates if fuel_utilization_type is not empty
        if self.fuel_utilization_type:
            self.create_fuel_entry()

    def create_fuel_entry(self):
        # Initialize variables to None for conditional checks later
        fuel_supplied_doc, fuel_utilization_doc = None, None

        # Determine which document to fetch based on the fuel_utilization_type
        if self.fuel_utilization_type == "Supplied" and hasattr(self, 'fuel_supplied_id') and self.fuel_supplied_id:
            fuel_supplied_doc = frappe.get_doc("Fuel Supplied", self.fuel_supplied_id)
        elif self.fuel_utilization_type == "Dispensed" and hasattr(self, 'fuel_utilization_id') and self.fuel_utilization_id:
            fuel_utilization_doc = frappe.get_doc("Fuel Utilization", self.fuel_utilization_id)

        # Calculate the previous balance based on the document fetched
        previous_balance = self.get_previous_balance(fuel_supplied_doc, fuel_utilization_doc)

        # Create the Fuel Entry document with appropriate values
        new_fuel_entry = frappe.get_doc({
            "doctype": "Fuel Entry",
            "date": self.date,
            "fuel_tanker": self.fuel_tanker,
            "site": self.site,
            "utilization_type": self.fuel_utilization_type,
            "current_balance": self.balance,
            "previous_balance": previous_balance,
            "litres_supplied": fuel_supplied_doc.fuel_supplied if fuel_supplied_doc else 0,
            "litres_dispensed": fuel_utilization_doc.fuel_issued_lts if fuel_utilization_doc else 0,
            "fuel_balance": self.name
        })
        new_fuel_entry.insert()
        new_fuel_entry.submit()
        # Transactions are handled by Frappe.

    def get_previous_balance(self, fuel_supplied_doc, fuel_utilization_doc):
        # Calculate the previous balance based on the document type and fuel_utilization_type
        if self.fuel_utilization_type == "Supplied" and fuel_supplied_doc:
            return self.balance - fuel_supplied_doc.fuel_supplied
        elif self.fuel_utilization_type == "Dispensed" and fuel_utilization_doc:
            return self.balance + fuel_utilization_doc.fuel_issued_lts
        else:
            return self.balance
