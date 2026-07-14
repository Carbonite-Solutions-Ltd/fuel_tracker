# Copyright (c) 2026, Carbonite Solutions Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from fuel_tracker.tests.utils import ensure_site, make_tanker, supply

test_ignore = ["Item", "Company"]


class TestFuelTanker(FrappeTestCase):
	def test_new_tanker_creates_item_with_asset_settings(self):
		tanker = make_tanker("TEST-FT-TKR-1")
		self.assertEqual(tanker.tanker, "TEST-FT-TKR-1")
		self.assertEqual(tanker.is_new_tanker, 0)
		self.assertFalse(tanker.new_tanker_name)

		item = frappe.get_doc("Item", "TEST-FT-TKR-1")
		self.assertEqual(item.is_stock_item, 0)
		self.assertEqual(item.custom_resource_type, "Truck")
		self.assertEqual(item.is_fixed_asset, 1)
		self.assertEqual(item.auto_create_assets, 1)
		self.assertEqual(item.asset_naming_series, "ACC-ASS-.YYYY.-")
		self.assertEqual(item.asset_category, "TRUCKS & VEHICLES")
		self.assertEqual(item.item_group, "Trucks & Vehicles")

		category = frappe.get_doc("Asset Category", "TRUCKS & VEHICLES")
		self.assertTrue(category.accounts)
		self.assertTrue(category.accounts[0].company_name)
		self.assertTrue(category.accounts[0].fixed_asset_account)
		self.assertEqual(
			frappe.db.get_value("Item Group", "Trucks & Vehicles", "parent_item_group"),
			"All Item Groups",
		)

	def test_existing_item_is_linked_untouched(self):
		item_group = frappe.get_all("Item Group", limit=1, pluck="name")[0]
		frappe.get_doc({
			"doctype": "Item", "item_code": "TEST-FT-TKR-2", "item_name": "TEST-FT-TKR-2",
			"item_group": item_group, "stock_uom": "Nos", "is_stock_item": 0,
			"custom_resource_type": "Truck",
		}).insert()

		tanker = make_tanker("TEST-FT-TKR-2")
		self.assertEqual(tanker.tanker, "TEST-FT-TKR-2")
		self.assertEqual(frappe.db.get_value("Item", "TEST-FT-TKR-2", "item_group"), item_group)

	def test_unknown_tanker_rejected_outside_new_mode(self):
		with self.assertRaises(frappe.LinkValidationError):
			frappe.get_doc({
				"doctype": "Fuel Tanker",
				"tanker": "TEST-FT-NO-SUCH-ITEM",
				"site": ensure_site(),
			}).insert()

	def test_rename_cascades_to_item_and_fuel_balance(self):
		tanker = make_tanker("TEST-FT-TKR-3").name
		supply(tanker, 50)  # creates the draft Fuel Balance named after the tanker

		frappe.rename_doc("Fuel Tanker", tanker, "TEST-FT-TKR-3R", show_alert=False)

		self.assertTrue(frappe.db.exists("Fuel Tanker", "TEST-FT-TKR-3R"))
		self.assertEqual(frappe.db.get_value("Fuel Tanker", "TEST-FT-TKR-3R", "tanker"), "TEST-FT-TKR-3R")
		self.assertTrue(frappe.db.exists("Item", "TEST-FT-TKR-3R"))
		self.assertFalse(frappe.db.exists("Item", "TEST-FT-TKR-3"))
		self.assertEqual(frappe.db.get_value("Item", "TEST-FT-TKR-3R", "custom_resource_type"), "Truck")
		self.assertTrue(frappe.db.exists("Fuel Balance", "TEST-FT-TKR-3R"))
		self.assertEqual(frappe.db.get_value("Fuel Balance", "TEST-FT-TKR-3R", "fuel_tanker"), "TEST-FT-TKR-3R")

	def test_tanker_field_edit_on_saved_doc_reverts(self):
		make_tanker("TEST-FT-TKR-4")
		make_tanker("TEST-FT-TKR-5")

		doc = frappe.get_doc("Fuel Tanker", "TEST-FT-TKR-4")
		doc.tanker = "TEST-FT-TKR-5"
		doc.save()

		# frappe's autoname sync keeps the field mirroring the doc name;
		# renames must go through the Rename action
		self.assertEqual(doc.tanker, "TEST-FT-TKR-4")
