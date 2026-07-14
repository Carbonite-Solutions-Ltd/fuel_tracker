# Copyright (c) 2024, Carbonite Solutions Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

TANKER_ITEM_GROUP = "Trucks & Vehicles"
TANKER_ASSET_CATEGORY = "TRUCKS & VEHICLES"
TANKER_ASSET_NAMING_SERIES = "ACC-ASS-.YYYY.-"


class FuelTanker(Document):
	def _validate_links(self):
		# On insert, frappe validates links before any controller hook runs
		# (Document.insert calls _validate_links first), so the Item for a
		# new tanker must be created right before the check. This also runs
		# before naming, so self.tanker is set in time for the autoname.
		self.ensure_tanker_item()
		super()._validate_links()

	def after_rename(self, old, new, merge=False):
		"""Carry the linked records along when the tanker is renamed.

		Renaming happens via the Rename action (editing the tanker field on
		a saved doc is reverted by frappe's autoname sync). The linked Item
		and the tanker's Fuel Balance are autonamed after this document, so
		both follow the new name. If an Item/Fuel Balance already exists
		under the new name, it is left alone and simply gets linked.
		"""
		if merge:
			return

		if frappe.db.exists("Item", old) and not frappe.db.exists("Item", new):
			frappe.rename_doc("Item", old, new, show_alert=False)

		if frappe.db.exists("Fuel Balance", old) and not frappe.db.exists("Fuel Balance", new):
			# force: Fuel Balance deliberately has allow_rename off for users;
			# this controlled rename just keeps its name mirroring the tanker.
			frappe.rename_doc("Fuel Balance", old, new, force=True, show_alert=False)

	def ensure_tanker_item(self):
		"""Create and link the Item for a tanker registered as new.

		With "New Tanker Item" ticked, the name entered in new_tanker_name
		becomes the tanker link; if no Item with that name exists yet it is
		created as a non-stock fixed-asset Item (resource type Truck, asset
		category TRUCKS & VEHICLES, auto-create assets on purchase). Without
		the flag, the tanker link must point at an existing Item and normal
		link validation applies.
		"""
		if not (self.is_new_tanker and (self.new_tanker_name or "").strip()):
			return

		self.tanker = self.new_tanker_name.strip()
		self.is_new_tanker = 0
		self.new_tanker_name = None

		if frappe.db.exists("Item", self.tanker):
			return

		uom = "Nos" if frappe.db.exists("UOM", "Nos") else frappe.get_all("UOM", limit=1, pluck="name")[0]
		item = frappe.get_doc({
			"doctype": "Item",
			"item_code": self.tanker,
			"item_name": self.tanker,
			"item_group": self.ensure_item_group(),
			"stock_uom": uom,
			"is_stock_item": 0,
			"custom_resource_type": "Truck",
			"is_fixed_asset": 1,
			"auto_create_assets": 1,
			"asset_naming_series": TANKER_ASSET_NAMING_SERIES,
			"asset_category": self.ensure_asset_category(),
		})
		item.flags.ignore_permissions = True
		item.insert()
		frappe.msgprint(
			_("Item {0} was created automatically and linked to this tanker.")
			.format(frappe.bold(self.tanker)),
			indicator="green",
			alert=True,
		)

	def ensure_item_group(self):
		if frappe.db.exists("Item Group", TANKER_ITEM_GROUP):
			return TANKER_ITEM_GROUP

		root = frappe.get_all("Item Group", filters={"is_group": 1, "parent_item_group": ""}, pluck="name")
		group = frappe.get_doc({
			"doctype": "Item Group",
			"item_group_name": TANKER_ITEM_GROUP,
			"parent_item_group": root[0] if root else "All Item Groups",
			"is_group": 0,
		})
		group.flags.ignore_permissions = True
		group.insert()
		return TANKER_ITEM_GROUP

	def ensure_asset_category(self):
		"""Create the TRUCKS & VEHICLES asset category if it doesn't exist.

		Asset Category requires at least one accounts row (company + fixed
		asset account), so the default company's first Fixed Asset account is
		used as a starting point; accountants can refine the category later.
		"""
		if frappe.db.exists("Asset Category", TANKER_ASSET_CATEGORY):
			return TANKER_ASSET_CATEGORY

		company = frappe.db.get_single_value("Global Defaults", "default_company")
		if not company:
			companies = frappe.get_all("Company", limit=1, pluck="name")
			company = companies[0] if companies else None

		def first_account(account_type):
			accounts = frappe.get_all(
				"Account",
				filters={"company": company, "account_type": account_type, "is_group": 0},
				pluck="name",
				limit=1,
			)
			return accounts[0] if accounts else None

		fixed_asset_account = first_account("Fixed Asset") if company else None
		if not (company and fixed_asset_account):
			frappe.throw(
				_("Cannot auto-create Asset Category {0}: no company with a Fixed Asset account was found. "
				"Create the Asset Category manually and try again.")
				.format(frappe.bold(TANKER_ASSET_CATEGORY))
			)

		category = frappe.get_doc({
			"doctype": "Asset Category",
			"asset_category_name": TANKER_ASSET_CATEGORY,
			"accounts": [{
				"company_name": company,
				"fixed_asset_account": fixed_asset_account,
				"accumulated_depreciation_account": first_account("Accumulated Depreciation"),
				"depreciation_expense_account": first_account("Depreciation"),
			}],
		})
		category.flags.ignore_permissions = True
		category.insert()
		frappe.msgprint(
			_("Asset Category {0} was created automatically with the accounts of company {1}. Review its account setup.")
			.format(frappe.bold(TANKER_ASSET_CATEGORY), frappe.bold(company)),
			indicator="orange",
			alert=True,
		)
		return TANKER_ASSET_CATEGORY
