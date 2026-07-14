import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class FuelSupplied(Document):
    def before_submit(self):
        self.validate_fuel_quantity()

    def on_submit(self):
        previous_balance, balance_doc = self.get_or_create_fuel_balance()
        self.warn_if_above_threshold(previous_balance)
        self.create_fuel_entry(previous_balance, supplied=True)

    def validate_fuel_quantity(self):
        if flt(self.fuel_supplied) <= 0:
            frappe.throw(_("Fuel Supplied (LTS) must be greater than zero."))

    def warn_if_above_threshold(self, previous_balance):
        threshold = flt(frappe.db.get_value("Fuel Tanker", self.fuel_tanker, "tanker_threshold"))
        new_balance = flt(previous_balance) + flt(self.fuel_supplied)
        if threshold and new_balance > threshold:
            frappe.msgprint(
                _("This supply raises the balance of tanker {0} to {1} L, above its maximum threshold of {2} L.")
                .format(self.fuel_tanker, new_balance, threshold),
                indicator="orange",
                alert=True,
            )

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
            # Create a new Fuel Balance if none exists. Left as a draft on
            # purpose (same as Fuel Used): submitting a Fuel Balance seeds an
            # opening-balance Fuel Entry, and that must stay a deliberate user
            # action, not a zero-litre side effect of the first supply.
            new_balance_entry = frappe.get_doc({
                "doctype": "Fuel Balance",
                "fuel_tanker": self.fuel_tanker,
                "balance": 0,  # Initialize with zero; will be updated
                "site": self.site,
                "date": self.date,
            })
            new_balance_entry.insert()
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

