import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class FuelUsed(Document):
    def before_submit(self):
        if self.review_status == "Incoming Report":
            self.review_status = "Reviewed"
        self.validate_fuel_quantity()
        self.sync_and_validate_resource_reading()

    def on_submit(self):
        # Get the previous balance or create a new Fuel Balance if it doesn't exist
        previous_balance, balance_doc = self.get_or_create_fuel_balance()

        self.warn_if_overdrawing(previous_balance)

        # Create a Fuel Entry document to record the fuel used
        self.create_fuel_entry(previous_balance)

        # Update the current odometer or hours in the Resource doctype
        self.update_resource_usage()

    def validate_fuel_quantity(self):
        if flt(self.fuel_issued_lts) <= 0:
            frappe.throw(_("Fuel Issued (LTS) must be greater than zero."))

    def sync_and_validate_resource_reading(self):
        """Refresh the previous reading from the Resource, then validate.

        A draft (e.g. an incoming mobile report) can sit for a while before
        it is reviewed and submitted, so the previous reading fetched when
        the draft was created may be stale by then — another Fuel Used for
        the same resource may have been submitted in between. The Resource's
        stored reading is authoritative at submit time: it becomes the
        previous reading here (so the ledger diff is measured from it), and
        the new reading may not fall behind it.
        """
        resource = frappe.get_doc("Resource", self.resource)
        self.resource_type = resource.resource_type

        if self.resource_type == "Truck":
            self.previous_odometer_km = flt(resource.current_odometer)
            if flt(self.odometer_km) < self.previous_odometer_km:
                frappe.throw(
                    _("Odometer reading {0} km cannot be less than the resource's current reading: {1} km")
                    .format(flt(self.odometer_km), self.previous_odometer_km)
                )
        elif self.resource_type == "Equipment":
            self.previous_hours_copy = flt(resource.current_hours)
            if flt(self.hours_copy) < self.previous_hours_copy:
                frappe.throw(
                    _("Hours reading {0} cannot be less than the resource's current hours: {1}")
                    .format(flt(self.hours_copy), self.previous_hours_copy)
                )

    def warn_if_overdrawing(self, previous_balance):
        new_balance = flt(previous_balance) - flt(self.fuel_issued_lts)

        if new_balance < 0:
            frappe.msgprint(
                _("Dispensing {0} L exceeds the current balance of tanker {1} ({2} L); the balance will go negative.")
                .format(flt(self.fuel_issued_lts), self.fuel_tanker, flt(previous_balance)),
                indicator="orange",
                alert=True,
            )

        minimum_level = flt(frappe.db.get_value("Fuel Tanker", self.fuel_tanker, "minimum_level"))
        if minimum_level and new_balance < minimum_level:
            frappe.msgprint(
                _("The balance of tanker {0} falls below its minimum level of {1} L (new balance: {2} L). Consider reordering fuel.")
                .format(self.fuel_tanker, minimum_level, new_balance),
                indicator="orange",
                alert=True,
            )

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
        fuel_entry_data = {
            "doctype": "Fuel Entry",
            "date": self.date,
            "fuel_tanker": self.fuel_tanker,
            "site": self.site,
            "utilization_type": "Dispensed",
            "previous_balance": previous_balance,
            "litres_dispensed": self.fuel_issued_lts,  # Fuel issued (used) from this document
            "current_balance": previous_balance - self.fuel_issued_lts,  # Subtract used fuel from previous balance
            "fuel_utilization_id": self.name,  # Link back to this Fuel Used document
            "resource":self.resource
        }

        # Calculate the difference based on resource type
        if self.resource_type == "Truck":
            fuel_entry_data["diff_odometer"] = flt(self.odometer_km) - flt(self.previous_odometer_km)
        elif self.resource_type == "Equipment":
            fuel_entry_data["diff_hours_copy"] = flt(self.hours_copy) - flt(self.previous_hours_copy)

        fuel_entry = frappe.get_doc(fuel_entry_data)
        fuel_entry.flags.ignore_permissions = True  # If necessary to bypass permission checks
        fuel_entry.insert()
        fuel_entry.submit()

    def update_resource_usage(self):
        resource = frappe.get_doc("Resource", self.resource)

        if self.resource_type == "Truck":
            resource.current_odometer = self.odometer_km
        elif self.resource_type == "Equipment":
            resource.current_hours = self.hours_copy

        resource.save()
        


