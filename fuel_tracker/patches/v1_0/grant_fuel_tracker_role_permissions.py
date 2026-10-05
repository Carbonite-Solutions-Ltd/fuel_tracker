"""Give the site's Fuel Tracker roles the access their work needs.

Both roles are created on the site rather than shipped by the app, so this
only acts where they exist:

* **Fuel Tracker Manager** gets on Fuel Adjustment the rights it already holds
  on every other source document. Without them a manager could not correct
  stock, and cancelling an adjustment's ledger line — which cascades a cancel
  to the adjustment — failed with a permission error.
* **Fuel Tracker Attendant** gets read/create/write/delete on Fuel Used,
  limited to the documents they created. The mobile app records fills through
  it, and without the permission every insert from an attendant failed.
  Submitting stays with managers, who review what comes in.

Only grants: nothing an administrator has already set is revoked.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

#: (doctype, role, only-if-creator, rights)
GRANTS = (
	(
		"Fuel Adjustment",
		"Fuel Tracker Manager",
		0,
		("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "print", "select"),
	),
	("Fuel Used", "Fuel Tracker Attendant", 1, ("read", "write", "create", "delete")),
)


def execute():
	for doctype, role, if_owner, rights in GRANTS:
		if frappe.db.exists("Role", role):
			grant(doctype, role, if_owner, rights)

	frappe.clear_cache()


def grant(doctype, role, if_owner, rights):
	existing = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}, "if_owner"
	)
	if existing is None:
		# copies the doctype's standard rules first, so System Manager keeps its row
		add_permission(doctype, role, 0)
		# a new rule starts with Frappe's defaults (export is on); grant only what is listed
		for right in ("export", "print", "email", "share", "report"):
			if right not in rights:
				update_permission_property(doctype, role, 0, right, 0, if_owner=0)
		if if_owner:
			update_permission_property(doctype, role, 0, "if_owner", 1, if_owner=0)
	else:
		# a rule an administrator already set up keeps its own scope
		if_owner = existing

	for right in rights:
		update_permission_property(doctype, role, 0, right, 1, if_owner=if_owner)
