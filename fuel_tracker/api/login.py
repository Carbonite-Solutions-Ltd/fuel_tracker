import frappe
from frappe import _
import secrets

# ? --------------- API POST CALL TO CONFIRM LOGIN AUTHENTICATION ----------------------------
@frappe.whitelist(allow_guest=True)
def verify_login(username, password):
    """Verify the user's login credentials."""
    try:
        # Check if the user exists
        user = frappe.db.get_value("User", {"email": username})
        if not user:
            return {"status": "failed", "message": _("Invalid username")}

        # Validate the credentials using Frappe's authenticate method
        user_doc = frappe.get_doc("User", user)
        if user_doc and frappe.utils.password.check_password(user_doc.name, password):
            # Fetch API key and secret for the user
            api_key = user_doc.api_key
            api_secret = user_doc.get_password('api_secret')
            
            # If the credentials are valid, return success with full name, api_key, and api_secret
            return {
                "status": "success",
                "message": _("Login successful"),
                "full_name": user_doc.full_name,
                "api_key": api_key,
                "api_secret": api_secret
            }
        else:
            return {"status": "failed", "message": _("Invalid password")}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}



# ? --------------- API POST CALL TO CONFIRM LOGIN AUTHENTICATION ----------------------------
# http://127.0.0.1:8000/api/v2/method/fuel_tracker.api.login.verify_login