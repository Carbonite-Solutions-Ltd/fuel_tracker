import frappe
from frappe.model.document import Document
from frappe.utils import flt

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
        elif self.utilization_type == "Adjustment" and self.fuel_adjustment_id:
            linked_docname = self.fuel_adjustment_id
            linked_doctype = "Fuel Adjustment"

        if linked_docname and linked_doctype:
            # Fetch the linked document
            linked_doc = frappe.get_doc(linked_doctype, linked_docname)

            # Cancel the linked document if it is not already cancelled.
            # No commit here: the whole cancel (this cascade, the balance
            # reversal and the resource restore) must stay one transaction,
            # or a failure partway leaves the ledger and balance diverged.
            if linked_doc.docstatus == 1:  # 1 indicates submitted document
                linked_doc.cancel()

    def update_fuel_balance(self, submit=True):
        # Fetch the existing Fuel Balance for the specified fuel_tanker
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])

        balance_entry = None
        if existing_balance:
            # Update the existing Fuel Balance
            balance_entry = frappe.get_doc("Fuel Balance", existing_balance[0].name)

            # A cancelled Fuel Balance can't be edited and no longer holds a live
            # figure to adjust, so leave it untouched. This keeps a Fuel Entry
            # cancellable even when its Fuel Balance was already cancelled.
            if balance_entry.docstatus == 2:
                return

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
            elif self.utilization_type == "Adjustment":
                # litres_adjusted is signed, so += moves the balance either way
                balance_entry.balance += self.litres_adjusted or 0
        else:
            # Reverse the balance adjustment if the document is being cancelled
            if self.utilization_type == "Supplied":
                balance_entry.balance -= self.litres_supplied or 0
            elif self.utilization_type == "Dispensed":
                balance_entry.balance += self.litres_dispensed or 0
            elif self.utilization_type == "Adjustment":
                balance_entry.balance -= self.litres_adjusted or 0

        balance_entry.save()

    def update_resource_usage_on_cancel(self):
        """Restore the resource's odometer/hours after this entry is cancelled.

        The reading is recomputed from the remaining submitted Fuel Used
        documents for the resource rather than blindly restored from the
        cancelled document, so cancelling a mid-history entry cannot drag
        the reading backwards past later, still-submitted readings. The
        cancelled document's previous reading is only used when no other
        submitted Fuel Used remains.
        """
        if not (self.utilization_type == "Dispensed" and self.fuel_utilization_id):
            return

        fuel_used_doc = frappe.get_doc("Fuel Used", self.fuel_utilization_id)
        resource = frappe.get_doc("Resource", fuel_used_doc.resource)

        if resource.resource_type == "Truck":
            reading_field, resource_field = "odometer_km", "current_odometer"
            fallback = fuel_used_doc.previous_odometer_km
        elif resource.resource_type == "Equipment":
            reading_field, resource_field = "hours_copy", "current_hours"
            fallback = fuel_used_doc.previous_hours_copy
        else:
            return

        remaining_readings = frappe.get_all(
            "Fuel Used",
            filters={
                "resource": fuel_used_doc.resource,
                "docstatus": 1,
                "name": ["!=", fuel_used_doc.name],
            },
            pluck=reading_field,
        )
        remaining_readings = [flt(r) for r in remaining_readings if r is not None]

        setattr(resource, resource_field, max(remaining_readings) if remaining_readings else flt(fallback))
        resource.save()
