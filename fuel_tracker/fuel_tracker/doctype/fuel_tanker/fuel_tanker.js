// Copyright (c) 2024, Carbonite Solutions Ltd and contributors
// For license information, please see license.txt

// New-tanker registration is handled declaratively: the "New Tanker Item"
// checkbox toggles between the select-only tanker link and the
// new_tanker_name Data field (depends_on in fuel_tanker.json), and the
// server creates the Item on save (fuel_tanker.py).
frappe.ui.form.on("Fuel Tanker", {});
