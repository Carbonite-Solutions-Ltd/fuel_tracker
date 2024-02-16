import frappe
from frappe.model.document import Document

class FuelUsed(Document):
    def on_submit(self):
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])
        
        if existing_balance:
            balance_entry = frappe.get_doc("Fuel Balance", existing_balance[0].name)
            balance_entry.date = self.date
            balance_entry.balance -= self.fuel_issued_lts  # Adjusting balance for fuel dispensed
            balance_entry.fuel_used_type = "Dispensed"
            balance_entry.fuel_used_id = self.name  # Ensure this field now correctly references "Fuel Used"
            balance_entry.fuel_supplied_id = ""  # Keeping empty if no supply is associated
            # Use .save() and .submit() if necessary, but ensure the document's state allows for submission
            balance_entry.save()
            if balance_entry.docstatus == 0:
                balance_entry.submit()
        else:
            new_balance_entry = frappe.get_doc({
                "doctype": "Fuel Balance",
                "date": self.date,
                "fuel_tanker": self.fuel_tanker,
                "balance": -self.fuel_issued_lts,  # Initial negative balance due to dispensing
                "site": self.site,
                "fuel_used_type": "Dispensed",
                "fuel_used_id": self.name,  # Correctly linking to "Fuel Used"
                "fuel_supplied_id": ""  # Assuming no supply record
            })
            new_balance_entry.insert()
            new_balance_entry.submit()
