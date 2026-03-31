from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# Delete existing admin user
print("Deleting existing admin user...")
cur.execute("DELETE FROM users WHERE username = 'admin'")
print(f"Rows deleted: {cur.rowcount}")

# Also delete the admin employee
cur.execute("DELETE FROM employees WHERE name = 'Admin User'")
print(f"Employees deleted: {cur.rowcount}")

conn.commit()
cur.close()
conn.close()

print("✅ Deleted old admin account. It will be recreated with correct role on app startup.")
