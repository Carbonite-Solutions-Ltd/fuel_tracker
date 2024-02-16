import frappe
from frappe.model.document import Document

class FuelUsed(Document):
    def on_submit(self):
        # Attempt to find an existing Fuel Balance for the fuel_tanker
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])
        
        if existing_balance:
            # If exists, update the existing balance entry
            balance_entry = frappe.get_doc("Fuel Balance", existing_balance[0].name)
            balance_entry.date = self.date
            balance_entry.balance -= self.fuel_issued_lts  # Assuming you're deducting issued fuel from the balance
            balance_entry.fuel_used_type = "Dispensed"
            balance_entry.fuel_used_id = self.name
            balance_entry.fuel_supplied_id = ""
            balance_entry.submit()
        else:
            # If no existing balance, create a new Fuel Balance entry
            # You need to decide what the initial balance should be before fuel is dispensed.
            # This example simply logs the dispensed amount as a negative balance.
            new_balance_entry = frappe.get_doc({
                "doctype": "Fuel Balance",
                "date": self.date,
                "fuel_tanker": self.fuel_tanker,
                # Initial balance before dispensing might need clarification.
                "balance": -self.fuel_issued_lts,
                "site": self.site,
                "fuel_used_type": "Dispensed",
                "fuel_used_id": self.name,
                "fuel_supplied_id": ""  # Assuming this is intentional for new entries without a supply record
            })
            new_balance_entry.insert()
            new_balance_entry.submit()
