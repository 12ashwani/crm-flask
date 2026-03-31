"""Debug script to check admin account and password verification."""

from database import get_db_connection
from werkzeug.security import check_password_hash
import mysql.connector

conn = get_db_connection()
cur = conn.cursor(dictionary=True)

print("=== Checking Users Table ===")
cur.execute("SELECT * FROM users")
users = cur.fetchall()
print(f"Total users: {len(users)}")

for user in users:
    print(f"\nUser: {user['username']} ({user['id']})")
    print(f"  Role: {user['role']}")
    print(f"  Employee ID: {user.get('employee_id', 'N/A')}")
    print(f"  Password Hash: {user['password'][:30]}...")
    
    # Test password
    test_password = "admin123"
    is_valid = check_password_hash(user['password'], test_password)
    print(f"  Password 'admin123' matches: {is_valid}")

print("\n=== Checking Employees Table Structure ===")
cur.execute("DESCRIBE employees")
rows = cur.fetchall()
print("Employees table columns:")
for row in rows:
    col_name = row.get('Field') or row[0]
    col_type = row.get('Type') or row[1]
    nullable = row.get('Null') or (row[2] if len(row) > 2 else 'YES')
    print(f"  - {col_name}: {col_type} ({nullable})")

print("\n=== Checking Employee Data ===")
cur.execute("SELECT * FROM employees")
employees = cur.fetchall()
print(f"Total employees: {len(employees)}")
for emp in employees:
    print(f"  - ID {emp['id']}: {emp['name']} (role: {emp.get('role', 'N/A')})")

cur.close()
conn.close()
print("\n✅ Debug complete!")
