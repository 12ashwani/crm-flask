import csv
import io

from flask import Blueprint, Response, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user

from database import (
    create_lead,
    assign_to_operations,
    get_db_connection,
    get_department_dashboard,
    get_employees_by_department,
    get_export_rows,
    get_scoped_lead,
    return_lead_to_previous_stage,
)

marketing_bp = Blueprint("marketing", __name__, url_prefix="/marketing")


# ================================
# 🔒 HELPER: ROLE CHECK
# ================================
def check_marketing_access():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip().lower()

    if role != "marketing" and dept != "marketing":
        flash("Access denied. Marketing only.", "danger")
        return False
    session["last_panel"] = "marketing"
    return True


def build_marketing_export():
    rows = get_export_rows("marketing", current_user.employee_id)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id", "company_name", "service", "status", "pending_department",
            "total_fee", "govt_fee", "professional_fee", "paid_amount", "pending_amount",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return buffer.getvalue()


# ================================
# 📊 DASHBOARD
# ================================
@marketing_bp.route("/dashboard")
@login_required
def dashboard():

    if not check_marketing_access():
        return redirect(url_for("index"))

    leads = get_department_dashboard("marketing", current_user.employee_id)
    ops_employees = get_employees_by_department("operations")

    return render_template(
        "marketing/dashboard.html",
        leads=leads,
        ops_employees=ops_employees
    )


# ================================
# 📋 ALL LEADS
# ================================
@marketing_bp.route("/leads")
@login_required
def marketing_leads():

    if not check_marketing_access():
        return redirect(url_for("index"))

    leads = get_department_dashboard("marketing", current_user.employee_id)
    ops_employees = get_employees_by_department("operations")

    return render_template(
        "marketing/all_leads.html",
        leads=leads,
        ops_employees=ops_employees
    )


@marketing_bp.route("/download")
@login_required
def download_leads():
    if not check_marketing_access():
        return redirect(url_for("index"))

    return Response(
        build_marketing_export(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=marketing_leads_{current_user.employee_id}.csv"},
    )


# ================================
# ➕ CREATE LEAD
# ================================
@marketing_bp.route("/create", methods=["POST"])
@login_required
def create():

    if not check_marketing_access():
        return redirect(url_for("index"))

    try:
        create_lead(
            current_user.employee_id,
            request.form.get("company_name"),
            service=request.form.get("service"),
            email=request.form.get("email"),
            auth_person_name=request.form.get("contact_person"),
            auth_person_number=request.form.get("phone"),
            auth_person_email=request.form.get("contact_email")
        )

        flash("✅ Lead created successfully.", "success")

    except Exception as e:
        flash(f"❌ Error creating lead: {str(e)}", "danger")

    return redirect(url_for("marketing.marketing_leads"))


# ================================
# 🔁 ASSIGN TO OPERATIONS
# ================================
@marketing_bp.route("/assign/<int:lead_id>", methods=["POST"])
@login_required
def assign(lead_id):

    if not check_marketing_access():
        return redirect(url_for("index"))

    try:
        assign_to_operations(
            lead_id,
            request.form.get("operation_executive")
        )

        flash("🚀 Lead assigned to operations.", "success")

    except Exception as e:
        flash(f"❌ Error assigning lead: {str(e)}", "danger")

    return redirect(url_for("marketing.marketing_leads"))  # better than hardcoded URL


# ================================
# 🔍 SEARCH LEADS
# ================================
@marketing_bp.route("/search")
@login_required
def search():

    if not check_marketing_access():
        return redirect(url_for("index"))

    query = request.args.get("q", "").lower()

    leads = get_department_dashboard("marketing", current_user.employee_id)

    filtered = [
        lead for lead in leads
        if query in (lead.get("company_name") or "").lower()
    ]

    return render_template(
        "marketing/search_leads.html",
        leads=filtered,
        ops_employees=get_employees_by_department("operations")
    )


# ================================
# � VIEW LEAD (placeholder)
# ================================
@marketing_bp.route("/view/<int:lead_id>")
@login_required
def view_lead(lead_id):

    if not check_marketing_access():
        return redirect(url_for("index"))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM leads WHERE id=%s AND marketing_executive=%s",
            (lead_id, current_user.employee_id)
        )
        lead = cur.fetchone()

        if not lead:
            flash("Lead not found or not owned by you.", "danger")
            return redirect(url_for("marketing.marketing_leads"))

        return render_template("marketing/view_lead.html", lead=lead)
    except Exception as e:
        flash(f"Error loading lead: {str(e)}", "danger")
        return redirect(url_for("marketing.marketing_leads"))
    finally:
        if conn:
            conn.close()


# ================================
# ✏️ EDIT LEAD 
# ================================
@marketing_bp.route("/edit/<int:lead_id>", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id):

    if not check_marketing_access():
        return redirect(url_for("index"))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # validate ownership
        cur.execute("SELECT * FROM leads WHERE id=%s AND marketing_executive=%s", (lead_id, current_user.employee_id))
        lead = cur.fetchone()

        if not lead:
            flash("Lead not found or not owned by you.", "danger")
            return redirect(url_for("marketing.marketing_leads"))

        if request.method == "POST":
            company_name = request.form.get("company_name", "").strip()
            service = request.form.get("service", "").strip()
            auth_person_name = request.form.get("auth_person_name", "").strip()
            auth_person_number = request.form.get("auth_person_number", "").strip()
            auth_person_email = request.form.get("auth_person_email", "").strip()

            if not company_name:
                flash("Company name is required.", "warning")
                return render_template("marketing/edit_lead.html", lead=lead)

            cur.execute(
                """
                    UPDATE leads
                    SET company_name=%s, service=%s, auth_person_name=%s,
                        auth_person_number=%s, auth_person_email=%s
                    WHERE id=%s
                """,
                (
                    company_name,
                    service or None,
                    auth_person_name or None,
                    auth_person_number or None,
                    auth_person_email or None,
                    lead_id
                )
            )

            conn.commit()
            flash("Lead has been updated successfully.", "success")
            return redirect(url_for("marketing.marketing_leads"))

        return render_template("marketing/edit_lead.html", lead=lead)

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Error updating lead: {str(e)}", "danger")
        return redirect(url_for("marketing.marketing_leads"))

    finally:
        if conn:
            conn.close()


# ================================
# 🗑️ DELETE LEAD
# ================================
@marketing_bp.route("/delete/<int:lead_id>", methods=["POST"])
@login_required
def delete_lead(lead_id):

    if not check_marketing_access():
        return redirect(url_for("index"))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # validate ownership
        cur.execute("SELECT id FROM leads WHERE id=%s AND marketing_executive=%s", (lead_id, current_user.employee_id))
        if not cur.fetchone():
            flash("Lead not found or not owned by you.", "danger")
            return redirect(url_for("marketing.marketing_leads"))

        # delete child records first (to satisfy FK constraints)
        cur.execute("DELETE FROM operation_remarks WHERE lead_id=%s", (lead_id,))
        cur.execute("DELETE FROM operations WHERE lead_id=%s", (lead_id,))
        cur.execute("DELETE FROM payments WHERE lead_id=%s", (lead_id,))

        # delete lead
        cur.execute("DELETE FROM leads WHERE id=%s", (lead_id,))

        conn.commit()
        flash("Lead deleted successfully.", "success")

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Error deleting lead: {str(e)}", "danger")

    finally:
        if conn:
            conn.close()

    return redirect(url_for("marketing.marketing_leads"))


# ================================
# �📊 FILTER BY STATUS
# ================================
@marketing_bp.route("/filter/<status>")
@login_required
def filter_by_status(status):

    if not check_marketing_access():
        return redirect(url_for("index"))

    leads = get_department_dashboard("marketing", current_user.employee_id)

    filtered = [
        lead for lead in leads
        if lead.get("status") == status
    ]

    return render_template(
        "marketing/filter_leads.html",
        leads=filtered,
        ops_employees=get_employees_by_department("operations")
    )


@marketing_bp.route("/assigned-leads")
@login_required
def assigned_leads():

    if not check_marketing_access():
        return redirect(url_for("index"))

    leads = get_department_dashboard("marketing", current_user.employee_id)
    assigned = [
        lead for lead in leads
        if lead.get("status") == "Assigned to Operations"
    ]

    return render_template(
        "marketing/assign_leas.html",
        leads=assigned
    )


# ================================
# 📈 SIMPLE ANALYTICS
# ================================
@marketing_bp.route("/analytics")
@login_required
def analytics():

    if not check_marketing_access():
        return redirect(url_for("index"))

    leads = get_department_dashboard("marketing", current_user.employee_id)

    total = len(leads)
    assigned = len([l for l in leads if l["status"] == "Assigned to Operations"])
    new = len([l for l in leads if l["status"] == "New"])

    return render_template(
        "marketing/analytics.html",
        total=total,
        assigned=assigned,
        new=new
    )
@marketing_bp.route("/assign_ops/<int:lead_id>", methods=["POST"])
@login_required 
def assign_ops(lead_id):

    if not check_marketing_access():
        return redirect(url_for("index"))

    try:
        operation_executive_id = int(request.form.get("operation_executive"))
        assign_to_operations(
            lead_id,
            operation_executive_id
        )

        flash("🚀 Lead assigned to operations.", "success")
        return redirect(url_for("marketing.marketing_leads"))
    except Exception as e:
        flash(f"❌ Error assigning lead: {str(e)}", "danger")
        return redirect(url_for("marketing.marketing_leads"))


# =========================
# 📅 DEPARTMENT ATTENDANCE MANAGEMENT
# =========================
@marketing_bp.route("/return/<int:lead_id>", methods=["POST"])
@login_required
def return_lead(lead_id):

    if not check_marketing_access():
        return redirect(url_for("index"))

    scoped_lead = get_scoped_lead("marketing", lead_id, current_user.employee_id)
    if not scoped_lead:
        flash("Lead not found or not owned by you.", "danger")
        return redirect(url_for("marketing.marketing_leads"))

    try:
        return_lead_to_previous_stage(lead_id)
        flash("Lead returned to the previous workflow stage.", "success")
    except Exception as e:
        flash(f"Error returning lead: {str(e)}", "danger")

    return redirect(url_for("marketing.marketing_leads"))


@marketing_bp.route("/attendance")
@login_required
def attendance():
    """Marketing users cannot access attendance pages."""
    if not check_marketing_access():
        return redirect(url_for("index"))
    flash("Attendance access is restricted to HR and employee self-service.", "warning")
    return redirect(url_for("marketing.dashboard"))


# =========================
# 📋 DEPARTMENT LEAVE MANAGEMENT
# =========================
@marketing_bp.route("/leave-management")
@login_required
def leave_management():
    """Marketing users cannot access leave management."""
    if not check_marketing_access():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("marketing.dashboard"))


# =========================
# ✅ APPROVE LEAVE REQUEST
# =========================
@marketing_bp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):
    """Marketing users cannot approve leave requests."""
    if not check_marketing_access():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("marketing.dashboard"))


# =========================
# ❌ REJECT LEAVE REQUEST
# =========================
@marketing_bp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):
    """Marketing users cannot reject leave requests."""
    if not check_marketing_access():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("marketing.dashboard"))
    
