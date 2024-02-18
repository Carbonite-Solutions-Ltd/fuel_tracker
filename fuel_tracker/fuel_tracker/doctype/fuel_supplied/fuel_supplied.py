import frappe
from frappe.model.document import Document

# Assuming similar necessary imports and class definition
class FuelSupplied(Document):
    def on_submit(self):
        previous_balance, _ = self.get_or_create_fuel_balance()
        self.create_fuel_entry(previous_balance, supplied=True)

    def get_or_create_fuel_balance(self):
        # Check if there's an existing Fuel Balance for the fuel_tanker
        balance_entry = frappe.get_list("Fuel Balance",
                                        filters={"fuel_tanker": self.fuel_tanker},
                                        fields=["name", "balance"])
        
        if balance_entry:
            # Existing balance found
            balance_doc = frappe.get_doc("Fuel Balance", balance_entry[0].name)
            balance_doc.date = self.date
            return balance_doc.balance, balance_doc
        else:
            # Create a new Fuel Balance if none exists
            new_balance_entry = frappe.get_doc({
                "doctype": "Fuel Balance",
                "fuel_tanker": self.fuel_tanker,
                "balance": 0,  # Initialize with zero; will be updated
                "site": self.site,
                "date": self.date,
            })
            new_balance_entry.insert()
            new_balance_entry.submit()
            return 0, new_balance_entry  # Initial balance is zero

    def create_fuel_entry(self, previous_balance, supplied=False):
        # Create the Fuel Entry document
        fuel_entry = frappe.get_doc({
            "doctype": "Fuel Entry",
            "date": self.date,
            "fuel_tanker": self.fuel_tanker,
            "site": self.site,
            "utilization_type": "Supplied" if supplied else "Dispensed",
            "previous_balance": previous_balance,
            "litres_supplied": self.fuel_supplied if supplied else 0,
            "current_balance": previous_balance + self.fuel_supplied if supplied else previous_balance,
            # "litres_dispensed" would be set similarly for "Fuel Used"
            "fuel_supplied_id": self.name if supplied else "",
            # "fuel_utilization_id" would be set similarly for "Fuel Used"
        })
        fuel_entry.insert()
        fuel_entry.submit()

