import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class FuelAdjustment(Document):
    """Stock correction for a tanker (dip-count variance, spillage, theft, ...).

    On submit this creates a Fuel Entry with utilization_type="Adjustment"
    carrying the signed adjustment_litres, so the correction flows through the
    ledger like every other movement. Cancellation goes through the Fuel Entry
    (its cascade cancels this document); a submitted adjustment cannot be
    cancelled directly because the Fuel Entry links back to it.

    Note: a submitted adjustment counts as an active Fuel Entry for the tanker,
    so it forfeits later Opening Balance seeding — same as Supplied/Dispensed
    entries. A Measured Balance adjustment captures true stock anyway.
    """

    def before_submit(self):
        self.validate_reason_remarks()
        self.sync_system_balance_and_compute_adjustment()
        self.validate_nonzero_adjustment()

    def on_submit(self):
        previous_balance, balance_doc = self.get_or_create_fuel_balance()
        self.warn_if_out_of_bounds(previous_balance)
        self.create_fuel_entry(previous_balance)

    def validate_reason_remarks(self):
        if self.reason == "Other" and not (self.remarks or "").strip():
            frappe.throw(_("Remarks are required when the reason is Other."))

    def sync_system_balance_and_compute_adjustment(self):
        """Refresh the system balance from the live Fuel Balance, then compute.

        A draft can sit for a while before submission, so the balance captured
        while drafting may be stale. The live balance is authoritative at
        submit time: it becomes system_balance, and in Measured Balance mode
        the adjustment is measured against it. A tanker with no Fuel Balance
        yet has a system balance of 0 (the balance row is created lazily in
        on_submit, like the other source doctypes).
        """
        if not self.site:
            self.site = frappe.db.get_value("Fuel Tanker", self.fuel_tanker, "site")

        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])
        self.system_balance = flt(existing_balance[0].balance) if existing_balance else 0

        # Round to 3 decimals so float noise (e.g. measured == system apart
        # from 1e-13) cannot produce phantom adjustments or dodge the zero check.
        if self.adjustment_mode == "Measured Balance":
            self.adjustment_litres = flt(flt(self.measured_balance) - self.system_balance, 3)
        elif self.adjustment_mode == "Quantity":
            self.adjustment_litres = flt(self.quantity, 3)
        else:
            frappe.throw(_("Invalid adjustment mode: {0}").format(self.adjustment_mode))

    def validate_nonzero_adjustment(self):
        if not self.adjustment_litres:
            if self.adjustment_mode == "Measured Balance":
                frappe.throw(_("The measured balance equals the system balance; there is nothing to adjust."))
            frappe.throw(_("Adjustment Quantity (L) cannot be zero."))

    def get_or_create_fuel_balance(self):
        existing_balance = frappe.get_list("Fuel Balance",
                                           filters={"fuel_tanker": self.fuel_tanker},
                                           fields=["name", "balance"])
        if existing_balance:
            balance_doc = frappe.get_doc("Fuel Balance", existing_balance[0].name)
            balance_doc.date = self.date
            return balance_doc.balance, balance_doc

        # Create a new Fuel Balance if none exists. Left as a draft on purpose
        # (same as Fuel Supplied/Fuel Used): submitting a Fuel Balance seeds an
        # opening-balance Fuel Entry, and that must stay a deliberate user
        # action, not a side effect of an adjustment.
        new_balance_entry = frappe.get_doc({
            "doctype": "Fuel Balance",
            "fuel_tanker": self.fuel_tanker,
            "balance": 0,  # Initialize with zero; will be updated
            "site": self.site,
            "date": self.date,
        })
        new_balance_entry.insert()
        return 0, new_balance_entry

    def warn_if_out_of_bounds(self, previous_balance):
        new_balance = flt(previous_balance) + flt(self.adjustment_litres)
        if new_balance < 0:
            frappe.msgprint(
                _("This adjustment takes the balance of tanker {0} to {1} L (negative).")
                .format(self.fuel_tanker, new_balance),
                indicator="orange",
                alert=True,
            )

        limits = frappe.db.get_value(
            "Fuel Tanker", self.fuel_tanker, ["tanker_threshold", "minimum_level"], as_dict=True
        ) or frappe._dict()
        threshold = flt(limits.tanker_threshold)
        minimum_level = flt(limits.minimum_level)

        if threshold and new_balance > threshold:
            frappe.msgprint(
                _("This adjustment raises the balance of tanker {0} to {1} L, above its maximum threshold of {2} L.")
                .format(self.fuel_tanker, new_balance, threshold),
                indicator="orange",
                alert=True,
            )
        if minimum_level and new_balance < minimum_level:
            frappe.msgprint(
                _("The balance of tanker {0} falls below its minimum level of {1} L (new balance: {2} L). Consider reordering fuel.")
                .format(self.fuel_tanker, minimum_level, new_balance),
                indicator="orange",
                alert=True,
            )

    def create_fuel_entry(self, previous_balance):
        fuel_entry = frappe.get_doc({
            "doctype": "Fuel Entry",
            "date": self.date,
            "fuel_tanker": self.fuel_tanker,
            "site": self.site,
            "utilization_type": "Adjustment",
            "previous_balance": previous_balance,
            "litres_adjusted": self.adjustment_litres,
            "current_balance": flt(previous_balance) + flt(self.adjustment_litres),
            "fuel_adjustment_id": self.name,
        })
        fuel_entry.flags.ignore_permissions = True
        fuel_entry.insert()
        fuel_entry.submit()
