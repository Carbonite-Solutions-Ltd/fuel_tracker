# Copyright (c) 2024, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class FuelSupplied(Document):
    def on_submit(self):
        # Check if there's an existing Fuel Balance for the fuel_tanker
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])
        
        # If exists, update
        if existing_balance:
            balance_entry = frappe.get_doc("Fuel Balance", existing_balance[0].name)
            balance_entry.date = self.date
            balance_entry.balance += self.fuel_supplied
            balance_entry.fuel_used_type = "Supplied"
            balance_entry.fuel_supplied_id = self.name
            balance_entry.fuel_used_id = ""
            balance_entry.submit()
            frappe.db.commit()
        else:
            # Create a new Fuel Balance entry
            new_balance_entry = frappe.get_doc({
                "doctype": "Fuel Balance",
                "date": self.date,
                "fuel_tanker": self.fuel_tanker,
                "balance": self.fuel_supplied,
                "site": self.site,
                "fuel_used_type": "Supplied",
                "fuel_supplied_id": self.name,
                "fuel_used_id": ""
            })
            new_balance_entry.insert()
            new_balance_entry.submit()
            frappe.db.commit()
