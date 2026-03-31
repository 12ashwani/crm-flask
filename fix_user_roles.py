from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

print("Fixing users table role column...")
print("Current ENUM values: 'Admin', 'HR', 'Employee'")
print("Needed values: 'admin', 'marketing', 'operations', 'accounts'")

# Change role column from ENUM to VARCHAR
cur.execute("""
    ALTER TABLE users 
    MODIFY COLUMN role VARCHAR(50)
""")
conn.commit()
print("✅ Changed role column from ENUM to VARCHAR(50)")

# Now set the correct admin role
cur.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
conn.commit()
print("✅ Updated admin user role to 'admin'")

# Verify
cur.execute("SELECT username, role FROM users")
print("\nUpdated users:")
for row in cur.fetchall():
    print(f"  - {row[0]}: {row[1]}")

cur.close()
conn.close()
