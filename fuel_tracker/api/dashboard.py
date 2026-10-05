import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from fuel_tracker.fuel_tracker.fuel_ledger import PRECISION, get_balance_as_of, make_posting_datetime


@frappe.whitelist()
def fuelBalance(site, fuel_tanker, date=None):
    """Balance of a tanker at the end of `date` (today by default).

    Read from the ledger rather than from the last entry that happens to
    carry today's date: a tanker with no movement today still has a balance,
    and entries are ordered by posting datetime, not by `modified` — reposts
    deliberately leave `modified` alone.

    Requires a logged-in user who can read the tanker: stock levels are not
    public. `site` is accepted for compatibility with existing clients.
    """
    if not fuel_tanker or not frappe.db.exists("Fuel Tanker", fuel_tanker):
        frappe.throw(_("Fuel Tanker {0} does not exist.").format(frappe.bold(fuel_tanker)))
    frappe.has_permission("Fuel Tanker", "read", fuel_tanker, throw=True)

    try:
        as_at = make_posting_datetime(getdate(date or nowdate()), "23:59:59.999999")
        return get_balance_as_of(fuel_tanker, as_at)
    except Exception as e:
        frappe.log_error(message=str(e), title="Fuel Balance API Error")
        frappe.throw(_("An error occurred while fetching the Fuel Balance: {0}").format(str(e)))


@frappe.whitelist()
def get_total_fuel_balance(filters=None):
    """Fuel held across every tanker right now — the workspace number card.

    Summed from the ledger over the Fuel Tanker master, the same figure the
    Fuel Balance report closes on. Summing `Fuel Balance` rows instead counted
    balance rows left behind by tankers that no longer exist and dropped
    tankers whose balance row was never submitted.
    """
    frappe.has_permission("Fuel Balance", "read", throw=True)

    total = sum(get_balance_as_of(tanker) for tanker in frappe.get_all("Fuel Tanker", pluck="name"))
    return {"value": flt(total, PRECISION), "fieldtype": "Float"}
