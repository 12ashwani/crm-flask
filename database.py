import mysql.connector
from mysql.connector import Error
from datetime import datetime
from calendar import monthrange
from werkzeug.security import generate_password_hash, check_password_hash
from typing import List, Dict, Optional
import os

from dotenv import load_dotenv

load_dotenv()

# =========================================================
# MySQL CONFIGURATION
# =========================================================
MYSQL_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "crm_db"),
    "port": int(os.environ.get("DB_PORT", "3306")),
}

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_db_connection():
    """Create and return a MySQL database connection."""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except Error as e:
        raise RuntimeError(f"Database connection failed: {e}")


def fetchall_dict(cursor) -> List[Dict]:
    """Convert MySQL cursor results to list of dictionaries."""
    columns = cursor.column_names
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


LEAD_PAYMENT_SELECT = """
    COALESCE(p.total_amount, 0) AS total_fee,
    COALESCE(p.govt_amount, 0) AS govt_fee,
    COALESCE(p.professional_amount, 0) AS professional_fee,
    COALESCE(p.govt_amount, 0) + COALESCE(p.professional_amount, 0) AS paid_amount,
    GREATEST(COALESCE(p.total_amount, 0) - (COALESCE(p.govt_amount, 0) + COALESCE(p.professional_amount, 0)), 0) AS pending_amount
"""

LEAD_PENDING_DEPARTMENT_SELECT = """
    CASE
        WHEN l.status = 'New' THEN 'Marketing'
        WHEN l.status = 'Assigned to Operations' THEN 'Operations'
        WHEN l.status = 'Ready for Accounts' THEN 'Accounts'
        WHEN l.status = 'Assigned to Accounts' THEN 'Accounts'
        WHEN l.status = 'Pending' AND p.lead_id IS NOT NULL THEN 'Accounts'
        WHEN l.status = 'Pending' AND o.lead_id IS NOT NULL THEN 'Operations'
        WHEN l.status = 'Failed' AND p.lead_id IS NOT NULL THEN 'Accounts'
        WHEN l.status = 'Failed' AND o.lead_id IS NOT NULL THEN 'Operations'
        WHEN l.status = 'Completed' THEN 'Accounts'
        ELSE 'Marketing'
    END AS pending_department
"""

LATEST_OPERATION_REMARK_SELECT = """
    (
        SELECT r.remark
        FROM operation_remarks r
        WHERE r.lead_id = l.id
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT 1
    ) AS operation_remark
"""

# =========================================================
# TABLE CREATION
# =========================================================

def create_tables():
    """Create all necessary tables if they do not exist in MySQL."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255),
            email VARCHAR(255),
            phone VARCHAR(50),
            department VARCHAR(100),
            role VARCHAR(50)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE,
            password VARCHAR(255),
            department VARCHAR(100),
            role VARCHAR(50),
            employee_id INT,
            theme VARCHAR(10) DEFAULT 'light',
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INT AUTO_INCREMENT PRIMARY KEY,
            date DATE,
            company_name VARCHAR(255),
            email VARCHAR(255),
            auth_person_name VARCHAR(255),
            auth_person_number VARCHAR(50),
            auth_person_email VARCHAR(255),
            marketing_executive INT,
            service VARCHAR(255),
            status VARCHAR(50) DEFAULT 'New',
            account_executive INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(marketing_executive) REFERENCES employees(id),
            FOREIGN KEY(account_executive) REFERENCES employees(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            lead_id INT UNIQUE,
            client_login VARCHAR(255),
            client_password VARCHAR(255),
            file_status VARCHAR(50) DEFAULT 'pending',
            filing_date DATE,
            operation_executive INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(operation_executive) REFERENCES employees(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            lead_id INT UNIQUE,
            govt_payment_status VARCHAR(50) DEFAULT 'pending',
            professional_payment_status VARCHAR(50) DEFAULT 'pending',
            total_amount DECIMAL(10,2),
            govt_amount DECIMAL(10,2),
            professional_amount DECIMAL(10,2),
            payment_date DATE,
            remarks TEXT,
            account_executive INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(account_executive) REFERENCES employees(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS operation_remarks (
            id INT AUTO_INCREMENT PRIMARY KEY,
            lead_id INT,
            employee_id INT,
            remark TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id INT,
            date DATE,
            status ENUM('present', 'absent', 'late', 'half_day') DEFAULT 'present',
            check_in_time TIME,
            check_out_time TIME,
            working_hours DECIMAL(4,2),
            remarks TEXT,
            marked_by INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY(employee_id) REFERENCES employees(id),
            FOREIGN KEY(marked_by) REFERENCES employees(id),
            UNIQUE KEY unique_employee_date (employee_id, date)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id INT,
            leave_type ENUM('casual', 'sick', 'annual', 'maternity', 'paternity', 'emergency') DEFAULT 'casual',
            start_date DATE,
            end_date DATE,
            total_days INT,
            reason TEXT,
            status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
            applied_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_by INT,
            approved_on TIMESTAMP NULL,
            remarks TEXT,
            FOREIGN KEY(employee_id) REFERENCES employees(id),
            FOREIGN KEY(approved_by) REFERENCES employees(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS employee_salary_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id INT NOT NULL UNIQUE,
            monthly_salary DECIMAL(10,2) NOT NULL,
            effective_from DATE NOT NULL,
            updated_by INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            FOREIGN KEY(updated_by) REFERENCES employees(id) ON DELETE SET NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS holidays (
            id INT AUTO_INCREMENT PRIMARY KEY,
            holiday_date DATE NOT NULL UNIQUE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            created_by INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES employees(id) ON DELETE SET NULL
        )
    ''')

    conn.commit()
    
    # ============ MIGRATION: Add theme column if it doesn't exist ============
    try:
        cur.execute("ALTER TABLE users ADD COLUMN theme VARCHAR(10) DEFAULT 'light'")
        conn.commit()
    except:
        pass  # Column already exists

    try:
        cur.execute("ALTER TABLE users ADD COLUMN is_active TINYINT(1) DEFAULT 1")
        conn.commit()
    except:
        pass  # Column already exists

    try:
        cur.execute("ALTER TABLE users ADD COLUMN department VARCHAR(100)")
        conn.commit()
    except:
        pass  # Column already exists

    try:
        cur.execute("""
            UPDATE users u
            JOIN employees e ON e.id = u.employee_id
            SET u.department = e.department
            WHERE (u.department IS NULL OR u.department = '')
              AND e.department IS NOT NULL
        """)
        conn.commit()
    except:
        pass

    try:
        cur.execute("ALTER TABLE payments ADD COLUMN total_amount DECIMAL(10,2)")
        conn.commit()
    except:
        pass  # Column already exists
    
    try:
        cur.execute("ALTER TABLE payments ADD COLUMN remarks TEXT")
        conn.commit()
    except:
        pass  # Column already exists
    
    cur.close()
    conn.close()
    print("✅ MySQL tables ready")

# =========================================================
# EMPLOYEE MANAGEMENT
# =========================================================

def insert_employee(name: str, email: str, phone: str, department: str, role: str):
    """Add a new employee."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO employees (name, email, phone, department, role)
        VALUES (%s, %s, %s, %s, %s)
    """, (name, email, phone, department, role))
    conn.commit()
    cur.close()
    conn.close()


def get_all_employees() -> List[Dict]:
    """Retrieve all employees."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM employees ORDER BY id DESC")
    rows = fetchall_dict(cur)
    cur.close()
    conn.close()
    return rows


def get_employees_by_department(department: str) -> List[Dict]:
    """Get employees filtered by department."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM employees WHERE department=%s", (department,))
    rows = fetchall_dict(cur)
    cur.close()
    conn.close()
    return rows

# =========================================================
# LEADS (MARKETING)
# =========================================================

def create_lead(marketing_exec_id: int, company_name: str, **kwargs) -> int:
    """Insert a new lead for a marketing executive."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO leads (
            marketing_executive, company_name, date, email,
            auth_person_name, auth_person_number, auth_person_email, service
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        marketing_exec_id,
        company_name,
        kwargs.get('date', datetime.now().strftime('%Y-%m-%d')),
        kwargs.get('email'),
        kwargs.get('auth_person_name'),
        kwargs.get('auth_person_number'),
        kwargs.get('auth_person_email'),
        kwargs.get('service')
    ))
    lead_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return lead_id

# =========================================================
# OPERATIONS
# =========================================================

def assign_to_operations(lead_id: int, operation_executive_id: int):
    """Assign a lead to an operations executive."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO operations (lead_id, operation_executive)
        VALUES (%s, %s)
    """, (lead_id, operation_executive_id))
    cur.execute("UPDATE leads SET status='Assigned to Operations' WHERE id=%s", (lead_id,))
    conn.commit()
    cur.close()
    conn.close()


def update_operation(
        lead_id: int,
        file_status: str = 'done',
        filing_date: Optional[str] = None,
        client_login: Optional[str] = None,
        client_password: Optional[str] = None):
    """Update operation details and keep the lead in the correct workflow stage."""
    conn = get_db_connection()
    cur = conn.cursor()

    normalized_status = (file_status or "done").strip().lower()
    if normalized_status == "done":
        lead_status = "Ready for Accounts"
        effective_filing_date = filing_date or datetime.now().strftime('%Y-%m-%d')
    elif normalized_status == "pending":
        lead_status = "Pending"
        effective_filing_date = filing_date
    elif normalized_status == "failed":
        lead_status = "Failed"
        effective_filing_date = filing_date
    else:
        lead_status = "Assigned to Operations"
        effective_filing_date = filing_date

    cur.execute('''
        UPDATE operations
        SET file_status=%s,
            filing_date=COALESCE(%s, filing_date),
            client_login=COALESCE(%s, client_login),
            client_password=COALESCE(%s, client_password)
        WHERE lead_id=%s
    ''', (
        normalized_status,
        effective_filing_date,
        client_login,
        client_password,
        lead_id
    ))
    cur.execute("""
        UPDATE leads SET status=%s WHERE id=%s
    """, (lead_status, lead_id))
    conn.commit()
    cur.close()
    conn.close()

# =========================================================
# ACCOUNTS
# =========================================================

def assign_to_accounts(lead_id: int, account_executive_id: int):
    conn = get_db_connection()
    cur = conn.cursor()

    # Ensure payment row exists + assign exec
    cur.execute("""
        INSERT INTO payments (lead_id, account_executive)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE account_executive=VALUES(account_executive)
    """, (lead_id, account_executive_id))

    # Update lead stage
    cur.execute("""
        UPDATE leads SET status='Assigned to Accounts'
        WHERE id=%s
    """, (lead_id,))

    conn.commit()
    cur.close()
    conn.close()

def update_payment(
        lead_id: int,
        govt_amount: float,
        professional_amount: float,
        govt_status: str = 'done',
        prof_status: str = 'done'):
    """Update payment status and finalize the lead."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE payments
        SET govt_payment_status=%s,
            professional_payment_status=%s,
            govt_amount=%s,
            professional_amount=%s,
            payment_date=%s
        WHERE lead_id=%s
    """, (
        govt_status,
        prof_status,
        govt_amount,
        professional_amount,
        datetime.now().strftime('%Y-%m-%d'),
        lead_id
    ))
    cur.execute("UPDATE leads SET status='Completed' WHERE id=%s", (lead_id,))
    conn.commit()
    cur.close()
    conn.close()
def get_accounts_data():
    leads = get_leads_for_accounts()   # NEW FUNCTION (DB FILE)
    employees = get_employees_by_department("accounts")
    return leads, employees


def get_admin_leads_overview(
    team: Optional[str] = None,
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    lead_date: Optional[str] = None,
) -> List[Dict]:
    """Return all leads with joined team ownership details for the admin dashboard."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    current_team_select = """
        CASE
            WHEN p.account_executive IS NOT NULL
                 OR l.status IN ('Ready for Accounts', 'Assigned to Accounts', 'Pending', 'Completed', 'Failed')
                THEN 'Accounts'
            WHEN o.operation_executive IS NOT NULL
                 OR l.status = 'Assigned to Operations'
                THEN 'Operations'
            ELSE 'Marketing'
        END
    """

    current_employee_id_select = f"""
        CASE
            WHEN ({current_team_select}) = 'Accounts' THEN p.account_executive
            WHEN ({current_team_select}) = 'Operations' THEN o.operation_executive
            ELSE l.marketing_executive
        END
    """

    current_employee_name_select = f"""
        CASE
            WHEN ({current_team_select}) = 'Accounts' THEN acc.name
            WHEN ({current_team_select}) = 'Operations' THEN op.name
            ELSE m.name
        END
    """

    query = f"""
        SELECT
            l.id,
            l.date,
            l.company_name,
            l.email,
            l.auth_person_name,
            l.auth_person_number,
            l.auth_person_email,
            l.marketing_executive,
            l.service,
            l.status,
            l.account_executive,
            l.created_at,
            o.file_status,
            o.client_login,
            o.client_password,
            o.filing_date,
            o.operation_executive,
            p.govt_payment_status,
            p.professional_payment_status,
            p.total_amount,
            p.govt_amount,
            p.professional_amount,
            p.payment_date,
            p.remarks AS account_remark,
            p.account_executive,
            m.name AS marketing_executive_name,
            op.name AS operation_executive_name,
            acc.name AS account_executive_name,
            {LATEST_OPERATION_REMARK_SELECT},
            {LEAD_PENDING_DEPARTMENT_SELECT},
            {LEAD_PAYMENT_SELECT},
            ({current_team_select}) AS current_team,
            ({current_employee_id_select}) AS current_employee_id,
            ({current_employee_name_select}) AS current_employee_name
        FROM leads l
        LEFT JOIN operations o ON l.id = o.lead_id
        LEFT JOIN payments p ON l.id = p.lead_id
        LEFT JOIN employees m ON l.marketing_executive = m.id
        LEFT JOIN employees op ON o.operation_executive = op.id
        LEFT JOIN employees acc ON p.account_executive = acc.id
    """

    conditions = []
    params = []

    if team:
        conditions.append(f"({current_team_select}) = %s")
        params.append(team)

    if employee_id:
        conditions.append(f"({current_employee_id_select}) = %s")
        params.append(employee_id)

    if status:
        conditions.append("l.status = %s")
        params.append(status)

    if lead_date:
        conditions.append("DATE(l.date) = %s")
        params.append(lead_date)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY current_team ASC, current_employee_name ASC, l.created_at DESC"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows
# =========================================================
# DASHBOARDS
# =========================================================

def get_department_dashboard(role: str, employee_id: Optional[int] = None) -> List[Dict]:
    """Return dashboard data for a department role."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if role == "admin":
        cur.execute("""
            SELECT l.*, e.name as marketing_executive_name,
                   """ + LEAD_PENDING_DEPARTMENT_SELECT + """,
                   """ + LEAD_PAYMENT_SELECT + """
            FROM leads l
            LEFT JOIN employees e ON l.marketing_executive = e.id
            LEFT JOIN operations o ON l.id = o.lead_id
            LEFT JOIN payments p ON l.id = p.lead_id
            ORDER BY (l.status = 'New') DESC, l.created_at DESC
        """)
    elif role == "marketing":
        cur.execute("""
            SELECT l.*, e.name as marketing_executive_name,
                   op.name as operation_executive_name,
                   """ + LEAD_PENDING_DEPARTMENT_SELECT + """,
                   """ + LEAD_PAYMENT_SELECT + """
            FROM leads l
            LEFT JOIN employees e ON l.marketing_executive = e.id
            LEFT JOIN operations o ON l.id = o.lead_id
            LEFT JOIN employees op ON o.operation_executive = op.id
            LEFT JOIN payments p ON l.id = p.lead_id
            WHERE l.marketing_executive=%s
            ORDER BY (l.status = 'New') DESC, l.created_at DESC
        """, (employee_id,))
    elif role == "operations":
        cur.execute("""
            SELECT l.*, 
                   o.id as operation_id,
                   o.file_status,
                   o.client_login,
                   o.client_password,
                   o.filing_date,
                   o.operation_executive,
                   o.created_at as operation_created_at,
                   e.name as operation_executive_name,
                   m.name as marketing_executive_name,
                   """ + LATEST_OPERATION_REMARK_SELECT + """,
                   """ + LEAD_PENDING_DEPARTMENT_SELECT + """,
                   """ + LEAD_PAYMENT_SELECT + """
            FROM leads l
            JOIN operations o ON l.id=o.lead_id
            LEFT JOIN employees e ON o.operation_executive = e.id
            LEFT JOIN employees m ON l.marketing_executive = m.id
            LEFT JOIN payments p ON l.id = p.lead_id
            WHERE o.operation_executive=%s
            ORDER BY (l.status = 'New') DESC, l.created_at DESC
        """, (employee_id,))
    elif role == "accounts":
        cur.execute("""
            SELECT l.*, 
                   p.id as payment_id,
                   p.govt_payment_status,
                   p.professional_payment_status,
                   p.total_amount,
                   p.govt_amount,
                   p.professional_amount,
                   p.payment_date,
                   p.remarks,
                   p.remarks as account_remark,
                   p.account_executive,
                   p.created_at as payment_created_at,
                   o.client_login,
                   o.client_password,
                   e.name as account_executive_name,
                   m.name as marketing_executive_name,
                   op.name as operation_executive_name,
                   """ + LATEST_OPERATION_REMARK_SELECT + """,
                   """ + LEAD_PENDING_DEPARTMENT_SELECT + """,
                   """ + LEAD_PAYMENT_SELECT + """
            FROM leads l
            JOIN payments p ON l.id=p.lead_id
            LEFT JOIN operations o ON l.id = o.lead_id
            LEFT JOIN employees e ON p.account_executive = e.id
            LEFT JOIN employees m ON l.marketing_executive = m.id
            LEFT JOIN employees op ON o.operation_executive = op.id
            WHERE p.account_executive=%s
            ORDER BY l.created_at DESC
        """, (employee_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

# =========================================================
# DEFAULT ADMIN
# =========================================================

def create_default_admin():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE username='admin'")
    admin_user = cur.fetchone()

    hashed_password = generate_password_hash("admin123")

    if admin_user:
        existing_password = admin_user.get("password")

        # If existing admin has plain password (legacy), rehash it.
        if existing_password == "admin123":
            cur.execute("UPDATE users SET password=%s WHERE username='admin'", (hashed_password,))
            conn.commit()
            print("✅ Admin password updated to hashed admin123")
        else:
            print("Admin already exists")

        cur.close()
        conn.close()
        return

    cur.execute("""
        INSERT INTO employees (name, email, phone, department, role)
        VALUES (%s, %s, %s, %s, %s)
    """, ("Admin User", "admin@example.com", "9999999999", "admin", "admin"))
    employee_id = cur.lastrowid

    cur.execute("""
        INSERT INTO users (username, password, role, employee_id)
        VALUES (%s, %s, %s, %s)
    """, ("admin", hashed_password, "admin", employee_id))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Admin created: admin / admin123")
# =========================================================
# CUSTOM QUERIES
# =========================================================
def get_leads_for_accounts():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT l.*, 
               p.govt_payment_status,
               p.professional_payment_status,
               p.total_amount,
               p.govt_amount,
               p.professional_amount,
               p.payment_date,
               p.remarks,
               p.remarks as account_remark,
               p.account_executive,
               o.client_login,
               o.client_password,
               e.name as account_executive_name,
               m.name as marketing_executive_name,
               op.name as operation_executive_name,
               """ + LATEST_OPERATION_REMARK_SELECT + """,
               """ + LEAD_PENDING_DEPARTMENT_SELECT + """,
               """ + LEAD_PAYMENT_SELECT + """
        FROM leads l
        LEFT JOIN payments p ON l.id = p.lead_id
        LEFT JOIN operations o ON l.id = o.lead_id
        LEFT JOIN employees e ON p.account_executive = e.id
        LEFT JOIN employees m ON l.marketing_executive = m.id
        LEFT JOIN employees op ON o.operation_executive = op.id
        WHERE l.status IN ('New','Ready for Accounts', 'Assigned to Accounts', 'Pending', 'Completed', 'Failed')
        ORDER BY (l.status = 'New') DESC, l.created_at DESC
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows
# =========================================================
# UPDATE PAYMENT STATUS
# =========================================================
def update_payment_status(
    lead_id,
    govt=None,
    prof=None,
    status=None,
    amount=None,
    remarks=None,
    total_amount=None,
    govt_amount=None,
    professional_amount=None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Ensure payment row exists
    cursor.execute("""
        INSERT INTO payments (lead_id)
        VALUES (%s)
        ON DUPLICATE KEY UPDATE lead_id = lead_id
    """, (lead_id,))

    # Update Govt Fee
    if govt:
        cursor.execute("""
            UPDATE payments 
            SET govt_payment_status=%s 
            WHERE lead_id=%s
        """, (govt, lead_id))

    # Update Professional Fee
    if prof:
        cursor.execute("""
            UPDATE payments 
            SET professional_payment_status=%s 
            WHERE lead_id=%s
        """, (prof, lead_id))

    # Update Status (both govt and prof)
    if status:
        cursor.execute("""
            UPDATE payments 
            SET govt_payment_status=%s, professional_payment_status=%s
            WHERE lead_id=%s
        """, (status, status, lead_id))

    # Update Amount (both govt and prof)
    if amount:
        cursor.execute("""
            UPDATE payments 
            SET govt_amount=%s, professional_amount=%s
            WHERE lead_id=%s
        """, (amount, amount, lead_id))

    if total_amount is not None:
        cursor.execute("""
            UPDATE payments
            SET total_amount=%s
            WHERE lead_id=%s
        """, (total_amount, lead_id))

    if govt_amount is not None:
        cursor.execute("""
            UPDATE payments
            SET govt_amount=%s
            WHERE lead_id=%s
        """, (govt_amount, lead_id))

    if professional_amount is not None:
        cursor.execute("""
            UPDATE payments
            SET professional_amount=%s
            WHERE lead_id=%s
        """, (professional_amount, lead_id))

    # Update Remarks
    if remarks:
        cursor.execute("""
            UPDATE payments 
            SET remarks=%s 
            WHERE lead_id=%s
        """, (remarks, lead_id))

    if any(value is not None for value in (amount, total_amount, govt_amount, professional_amount, govt, prof, status)):
        cursor.execute("""
            UPDATE payments
            SET payment_date=%s
            WHERE lead_id=%s
        """, (datetime.now().strftime('%Y-%m-%d'), lead_id))

    # Get latest values
    cursor.execute("""
        SELECT govt_payment_status, professional_payment_status, total_amount, govt_amount, professional_amount
        FROM payments
        WHERE lead_id=%s
    """, (lead_id,))
    row = cursor.fetchone()

    govt_status, prof_status, saved_total_amount, saved_govt_amount, saved_prof_amount = row

    # Final status logic (store in LEADS for tracking stage)
    collected_total = float(saved_govt_amount or 0) + float(saved_prof_amount or 0)
    target_total = float(saved_total_amount or 0)

    if govt_status == "failed" or prof_status == "failed":
        final_status = "Failed"
    elif target_total > 0 and collected_total >= target_total:
        final_status = "Completed"
    else:
        final_status = "Pending"

    if final_status == "Completed":
        cursor.execute("""
            UPDATE payments
            SET govt_payment_status=%s, professional_payment_status=%s
            WHERE lead_id=%s
        """, ("received", "received", lead_id))
    elif final_status == "Pending" and govt_status != "failed" and prof_status != "failed":
        cursor.execute("""
            UPDATE payments
            SET govt_payment_status=%s, professional_payment_status=%s
            WHERE lead_id=%s
        """, (
            "received" if float(saved_govt_amount or 0) > 0 else "pending",
            "received" if float(saved_prof_amount or 0) > 0 else "pending",
            lead_id
        ))

    cursor.execute("""
        UPDATE leads SET status=%s WHERE id=%s
    """, (final_status, lead_id))

    conn.commit()
    cursor.close()
    conn.close()


def add_operation_remark(lead_id, employee_id, remark):
    """Add a remark for a lead in operations."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO operation_remarks (lead_id, employee_id, remark, created_at)
        VALUES (%s, %s, %s, NOW())
    """, (lead_id, employee_id, remark))
    conn.commit()
    cur.close()
    conn.close()


def get_scoped_lead(role: str, lead_id: int, employee_id: int):
    """Return a lead only if it belongs to the current role scope."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if role == "marketing":
        cur.execute(
            "SELECT id, status FROM leads WHERE id=%s AND marketing_executive=%s",
            (lead_id, employee_id),
        )
    elif role == "operations":
        cur.execute("""
            SELECT l.id, l.status
            FROM leads l
            JOIN operations o ON l.id = o.lead_id
            WHERE l.id=%s AND o.operation_executive=%s
        """, (lead_id, employee_id))
    elif role == "accounts":
        cur.execute("""
            SELECT l.id, l.status
            FROM leads l
            JOIN payments p ON l.id = p.lead_id
            WHERE l.id=%s AND p.account_executive=%s
        """, (lead_id, employee_id))
    else:
        cur.close()
        conn.close()
        return None

    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def return_lead_to_previous_stage(lead_id: int):
    """Move a lead one step back in the workflow."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur2 = conn.cursor()

    try:
        cur.execute("SELECT id, status FROM leads WHERE id=%s", (lead_id,))
        lead = cur.fetchone()
        if not lead:
            raise ValueError("Lead not found.")

        status = lead["status"]
        if status == "Assigned to Operations":
            cur2.execute("DELETE FROM operation_remarks WHERE lead_id=%s", (lead_id,))
            cur2.execute("DELETE FROM operations WHERE lead_id=%s", (lead_id,))
            cur2.execute("UPDATE leads SET status='New' WHERE id=%s", (lead_id,))
        elif status == "Ready for Accounts":
            cur2.execute("UPDATE leads SET status='Assigned to Operations' WHERE id=%s", (lead_id,))
        elif status == "Assigned to Accounts":
            cur2.execute("UPDATE payments SET account_executive=NULL WHERE lead_id=%s", (lead_id,))
            cur2.execute("UPDATE leads SET status='Ready for Accounts' WHERE id=%s", (lead_id,))
        elif status in {"Pending", "Completed", "Failed"}:
            cur2.execute("UPDATE leads SET status='Assigned to Accounts' WHERE id=%s", (lead_id,))
        else:
            raise ValueError("This lead cannot be returned from its current status.")

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur2.close()
        cur.close()
        conn.close()


def get_export_rows(role: str, employee_id: int):
    """Return role-scoped rows ready for CSV export."""
    return get_department_dashboard(role, employee_id)


# =========================================================
# ATTENDANCE MANAGEMENT
# =========================================================

def mark_attendance(employee_id: int, date: str, status: str, check_in_time: str = None,
                   check_out_time: str = None, working_hours: float = None,
                   remarks: str = None, marked_by: int = None):
    """Mark attendance for an employee on a specific date."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO attendance
            (employee_id, date, status, check_in_time, check_out_time, working_hours, remarks, marked_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            check_in_time = VALUES(check_in_time),
            check_out_time = VALUES(check_out_time),
            working_hours = VALUES(working_hours),
            remarks = VALUES(remarks),
            marked_by = VALUES(marked_by),
            updated_at = CURRENT_TIMESTAMP
        """, (employee_id, date, status, check_in_time, check_out_time, working_hours, remarks, marked_by))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def get_attendance_records(date: str = None, employee_id: int = None, month: str = None, year: str = None):
    """Get attendance records with optional filters."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    query = """
        SELECT a.*, e.name as employee_name, e.department, e.role,
               m.name as marked_by_name
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN employees m ON a.marked_by = m.id
    """

    conditions = []
    params = []

    if date:
        conditions.append("a.date = %s")
        params.append(date)

    if employee_id:
        conditions.append("a.employee_id = %s")
        params.append(employee_id)

    if month and year:
        conditions.append("MONTH(a.date) = %s AND YEAR(a.date) = %s")
        params.extend([month, year])
    elif year:
        conditions.append("YEAR(a.date) = %s")
        params.append(year)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY a.date DESC, e.name ASC"

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def ensure_attendance_records_for_date(target_date: str, marked_by: int = None):
    """Ensure every employee has an attendance row for the date, defaulting to absent."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur2 = conn.cursor()

    try:
        cur.execute("SELECT id FROM employees")
        employees = cur.fetchall()
        for employee in employees:
            cur2.execute("""
                INSERT INTO attendance (employee_id, date, status, marked_by)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                status = status
            """, (employee["id"], target_date, "absent", marked_by))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur2.close()
        cur.close()
        conn.close()


def get_employee_attendance_summary(employee_id: int, month: int, year: int):
    """Get attendance summary for an employee for a specific month."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT
            COUNT(*) as total_days,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent_days,
            SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) as late_days,
            SUM(CASE WHEN status = 'half_day' THEN 1 ELSE 0 END) as half_days,
            SUM(working_hours) as total_hours
        FROM attendance
        WHERE employee_id = %s AND MONTH(date) = %s AND YEAR(date) = %s
    """, (employee_id, month, year))

    summary = cur.fetchone()
    cur.close()
    conn.close()
    return summary


# =========================================================
# PAYROLL AND HOLIDAY MANAGEMENT
# =========================================================

def upsert_employee_salary(employee_id: int, monthly_salary: float, effective_from: str, updated_by: int = None):
    """Create or update salary settings for an employee."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO employee_salary_settings (employee_id, monthly_salary, effective_from, updated_by)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                monthly_salary = VALUES(monthly_salary),
                effective_from = VALUES(effective_from),
                updated_by = VALUES(updated_by),
                updated_at = CURRENT_TIMESTAMP
        """, (employee_id, monthly_salary, effective_from, updated_by))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def get_employee_salary_settings(employee_id: int = None):
    """Fetch salary settings with employee metadata."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    query = """
        SELECT s.*, e.name AS employee_name, e.department, e.role
        FROM employee_salary_settings s
        JOIN employees e ON e.id = s.employee_id
    """
    params = []
    if employee_id:
        query += " WHERE s.employee_id = %s"
        params.append(employee_id)
    query += " ORDER BY e.name ASC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def add_holiday(holiday_date: str, title: str, description: str = None, created_by: int = None):
    """Create or update a holiday by date."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO holidays (holiday_date, title, description, created_by)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                description = VALUES(description),
                created_by = VALUES(created_by)
        """, (holiday_date, title, description, created_by))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def get_holidays(start_date: str = None, end_date: str = None):
    """Fetch holidays optionally filtered by date range."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    query = """
        SELECT h.*, e.name AS created_by_name
        FROM holidays h
        LEFT JOIN employees e ON e.id = h.created_by
    """
    conditions = []
    params = []

    if start_date:
        conditions.append("h.holiday_date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("h.holiday_date <= %s")
        params.append(end_date)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY h.holiday_date ASC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def delete_holiday(holiday_id: int):
    """Delete a holiday by ID."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM holidays WHERE id = %s", (holiday_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def get_payroll_report(month: int, year: int, employee_id: int = None):
    """Generate payroll rows based on attendance and configured monthly salary."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    attendance_cur = conn.cursor(dictionary=True)

    try:
        query = """
            SELECT
                e.id AS employee_id,
                e.name AS employee_name,
                e.department,
                e.role,
                s.monthly_salary,
                s.effective_from
            FROM employees e
            LEFT JOIN employee_salary_settings s ON s.employee_id = e.id
        """
        params = []
        if employee_id:
            query += " WHERE e.id = %s"
            params.append(employee_id)
        query += " ORDER BY e.name ASC"

        cur.execute(query, tuple(params))
        employees = cur.fetchall()

        cur.execute(
            "SELECT COUNT(*) AS holiday_count FROM holidays WHERE MONTH(holiday_date) = %s AND YEAR(holiday_date) = %s",
            (month, year),
        )
        holiday_row = cur.fetchone() or {"holiday_count": 0}
        holiday_count = int(holiday_row.get("holiday_count") or 0)

        days_in_month = monthrange(year, month)[1]
        working_days = max(days_in_month - holiday_count, 0)
        report = []

        for employee in employees:
            attendance_cur.execute(
                """
                SELECT
                    SUM(CASE WHEN a.status IN ('present', 'late') THEN 1 WHEN a.status = 'half_day' THEN 0.5 ELSE 0 END) AS paid_days,
                    SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) AS present_days,
                    SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) AS late_days,
                    SUM(CASE WHEN a.status = 'half_day' THEN 1 ELSE 0 END) AS half_days
                FROM attendance a
                WHERE a.employee_id = %s
                  AND MONTH(a.date) = %s
                  AND YEAR(a.date) = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM holidays h
                      WHERE h.holiday_date = a.date
                  )
                """,
                (employee["employee_id"], month, year),
            )
            attendance = attendance_cur.fetchone() or {}

            paid_days = float(attendance.get("paid_days") or 0)
            paid_days = min(paid_days, float(working_days))
            absent_days = max(float(working_days) - paid_days, 0)

            monthly_salary = float(employee.get("monthly_salary") or 0)
            per_day_salary = (monthly_salary / working_days) if working_days > 0 else 0
            net_salary = round(per_day_salary * paid_days, 2)
            deduction = round(monthly_salary - net_salary, 2) if monthly_salary else 0

            report.append(
                {
                    "employee_id": employee["employee_id"],
                    "employee_name": employee["employee_name"],
                    "department": employee["department"],
                    "role": employee["role"],
                    "monthly_salary": monthly_salary,
                    "effective_from": employee.get("effective_from"),
                    "days_in_month": days_in_month,
                    "holiday_count": holiday_count,
                    "working_days": working_days,
                    "present_days": int(attendance.get("present_days") or 0),
                    "late_days": int(attendance.get("late_days") or 0),
                    "half_days": int(attendance.get("half_days") or 0),
                    "paid_days": round(paid_days, 2),
                    "absent_days": round(absent_days, 2),
                    "deduction": deduction,
                    "net_salary": net_salary,
                }
            )

        return report
    finally:
        attendance_cur.close()
        cur.close()
        conn.close()


# =========================================================
# LEAVE MANAGEMENT
# =========================================================

def submit_leave_request(employee_id: int, leave_type: str, start_date: str, end_date: str,
                        reason: str, total_days: int = None):
    """Submit a leave request."""
    if total_days is None:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        total_days = (end - start).days + 1

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO leave_requests
            (employee_id, leave_type, start_date, end_date, total_days, reason)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (employee_id, leave_type, start_date, end_date, total_days, reason))

        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def update_leave_status(leave_id: int, status: str, approved_by: int, remarks: str = None):
    """Update leave request status."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE leave_requests
            SET status = %s, approved_by = %s, approved_on = CURRENT_TIMESTAMP, remarks = %s
            WHERE id = %s
        """, (status, approved_by, remarks, leave_id))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def get_leave_requests(employee_id: int = None, status: str = None):
    """Get leave requests with optional filters."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    query = """
        SELECT lr.*, e.name as employee_name, e.department, e.role,
               a.name as approved_by_name
        FROM leave_requests lr
        JOIN employees e ON lr.employee_id = e.id
        LEFT JOIN employees a ON lr.approved_by = a.id
    """

    conditions = []
    params = []

    if employee_id:
        conditions.append("lr.employee_id = %s")
        params.append(employee_id)

    if status:
        conditions.append("lr.status = %s")
        params.append(status)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY lr.applied_on DESC"

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_pending_leave_requests(employee_id: int = None):
    """Convenience helper for pending leave requests."""
    return get_leave_requests(employee_id=employee_id, status="pending")


def get_employee_leave_balance(employee_id: int):
    """Get leave balance for an employee."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # This is a simplified version - in a real system you'd have a leave_balance table
    # For now, we'll calculate based on approved leaves this year
    current_year = datetime.now().year

    cur.execute("""
        SELECT
            SUM(CASE WHEN leave_type = 'casual' AND status = 'approved' THEN total_days ELSE 0 END) as used_casual,
            SUM(CASE WHEN leave_type = 'sick' AND status = 'approved' THEN total_days ELSE 0 END) as used_sick,
            SUM(CASE WHEN leave_type = 'annual' AND status = 'approved' THEN total_days ELSE 0 END) as used_annual
        FROM leave_requests
        WHERE employee_id = %s AND YEAR(start_date) = %s AND status = 'approved'
    """, (employee_id, current_year))

    used_leaves = cur.fetchone()

    # Default leave balances (you can customize these)
    balances = {
        'casual': 12 - (used_leaves['used_casual'] or 0),
        'sick': 6 - (used_leaves['used_sick'] or 0),
        'annual': 20 - (used_leaves['used_annual'] or 0)
    }

    cur.close()
    conn.close()
    return balances


def get_user_for_login(username: str):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT u.*, COALESCE(u.department, e.department) AS department, e.name AS employee_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        WHERE u.username = %s
        LIMIT 1
    """, (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def get_user_by_identifier(identifier: str):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if identifier.isdigit():
        cur.execute("""
            SELECT u.*, COALESCE(u.department, e.department) AS department, e.name AS employee_name
            FROM users u
            LEFT JOIN employees e ON e.id = u.employee_id
            WHERE u.username = %s OR u.employee_id = %s
            ORDER BY u.id ASC
            LIMIT 1
        """, (identifier, int(identifier)))
    else:
        cur.execute("""
            SELECT u.*, COALESCE(u.department, e.department) AS department, e.name AS employee_name
            FROM users u
            LEFT JOIN employees e ON e.id = u.employee_id
            WHERE u.username = %s
            LIMIT 1
        """, (identifier,))

    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def get_user_credentials(employee_id: int):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            e.id AS employee_id,
            e.name,
            e.email,
            e.department,
            e.role AS employee_role,
            u.id AS user_id,
            u.username,
            u.role AS user_role,
            u.is_active
        FROM employees e
        LEFT JOIN users u ON u.employee_id = e.id
        WHERE e.id = %s
        LIMIT 1
    """, (employee_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def is_username_taken(username: str, exclude_user_id: Optional[int] = None) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()

    if exclude_user_id:
        cur.execute(
            "SELECT id FROM users WHERE username = %s AND id != %s LIMIT 1",
            (username, exclude_user_id)
        )
    else:
        cur.execute(
            "SELECT id FROM users WHERE username = %s LIMIT 1",
            (username,)
        )

    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def update_user_password(user_id: int, password_hash: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password = %s WHERE id = %s",
        (password_hash, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def save_user_credentials(employee_id: int, username: str, role: str, password_hash: Optional[str] = None,
                          is_active: bool = True):
    conn = get_db_connection()
    lookup_cur = conn.cursor(dictionary=True)
    lookup_cur.execute("SELECT id FROM users WHERE employee_id = %s LIMIT 1", (employee_id,))
    existing = lookup_cur.fetchone()
    lookup_cur.close()

    write_cur = conn.cursor()

    if existing:
        user_id = existing["id"]
        if password_hash:
            write_cur.execute("""
                UPDATE users
                SET username = %s, role = %s, password = %s, is_active = %s
                WHERE id = %s
            """, (username, role, password_hash, int(is_active), user_id))
        else:
            write_cur.execute("""
                UPDATE users
                SET username = %s, role = %s, is_active = %s
                WHERE id = %s
            """, (username, role, int(is_active), user_id))
    else:
        if not password_hash:
            write_cur.close()
            conn.close()
            raise ValueError("Password is required to create a login account.")

        write_cur.execute("""
            INSERT INTO users (username, password, role, employee_id, is_active)
            VALUES (%s, %s, %s, %s, %s)
        """, (username, password_hash, role, employee_id, int(is_active)))

    conn.commit()
    write_cur.close()
    conn.close()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    create_tables()
    create_default_admin()
