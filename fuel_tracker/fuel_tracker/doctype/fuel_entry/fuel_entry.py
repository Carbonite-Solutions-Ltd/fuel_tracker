import frappe
from frappe.model.document import Document

class FuelEntry(Document):
    def on_submit(self):
        self.update_fuel_balance(submit=True)

    def on_cancel(self):
        self.update_fuel_balance(submit=False)

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
        # Check if it's draft and needs submitting; usually not needed for balance updates, so this might be optional
        # frappe.db.commit() might not be necessary due to Frappe's transaction management
