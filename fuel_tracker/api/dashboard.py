import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from fuel_tracker.fuel_tracker.fuel_ledger import get_balance_as_of, make_posting_datetime


@frappe.whitelist(allow_guest=True)
def fuelBalance(site, fuel_tanker, date=None):
    """Balance of a tanker at the end of `date` (today by default).

    Read from the ledger rather than from the last entry that happens to
    carry today's date: a tanker with no movement today still has a balance,
    and entries are ordered by posting datetime, not by `modified` — reposts
    deliberately leave `modified` alone.
    """
    try:
        as_at = make_posting_datetime(getdate(date or nowdate()), "23:59:59.999999")
        return get_balance_as_of(fuel_tanker, as_at)
    except Exception as e:
        frappe.log_error(message=str(e), title="Fuel Balance API Error")
        frappe.throw(_("An error occurred while fetching the Fuel Balance: {0}").format(str(e)))
