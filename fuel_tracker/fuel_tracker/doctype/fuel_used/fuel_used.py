import frappe
from frappe.model.document import Document

class FuelUsed(Document):
    def on_submit(self):
        # Get the previous balance or create a new Fuel Balance if it doesn't exist
        previous_balance, balance_doc = self.get_or_create_fuel_balance()
        # Create a Fuel Entry document to record the fuel used
        self.create_fuel_entry(previous_balance)

    def get_or_create_fuel_balance(self):
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])
        if existing_balance:
            balance_doc = frappe.get_doc("Fuel Balance", existing_balance[0].name)
            balance_doc.date = self.date
        else:
            balance_doc = frappe.get_doc({
                "doctype": "Fuel Balance",
                "fuel_tanker": self.fuel_tanker,
                "balance": 0,  # Initialize with zero; it will be updated
                "site": self.site,
                "date": self.date,
            })
            balance_doc.insert()
            # No need to submit here; balance updates will be handled by Fuel Entry transactions
        return balance_doc.balance, balance_doc

    def create_fuel_entry(self, previous_balance):
        # Assume fuel_issued_lts and other relevant fields are defined in FuelUsed DocType
        fuel_entry = frappe.get_doc({
            "doctype": "Fuel Entry",
            "date": self.date,
            "fuel_tanker": self.fuel_tanker,
            "site": self.site,
            "utilization_type": "Dispensed",
            "previous_balance": previous_balance,
            "litres_dispensed": self.fuel_issued_lts,  # Fuel issued (used) from this document
            "current_balance": previous_balance - float(self.fuel_issued_lts),  # Subtract used fuel from previous balance
            "fuel_utilization_id": self.name,  # Link back to this Fuel Used document
        })
        fuel_entry.flags.ignore_permissions = True  # If necessary to bypass permission checks
        fuel_entry.insert()
        fuel_entry.submit()

