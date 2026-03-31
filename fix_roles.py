"""
Fix the users table role column from ENUM to VARCHAR
so it can accept lowercase role names
"""
import mysql.connector

config = {
    "host": "localhost",
    "user": "root",
    "password": "Ecs@1234",
    "database": "crm_db"
}

try:
    conn = mysql.connector.connect(**config)
    cur = conn.cursor()
    
    print("Converting role column from ENUM to VARCHAR...")
    cur.execute("ALTER TABLE users MODIFY COLUMN role VARCHAR(50)")
    conn.commit()
    print("✅ Step 1: Changed role column to VARCHAR(50)")
    
    print("\nUpdating admin role to lowercase...")
    cur.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
    conn.commit()
    print("✅ Step 2: Updated admin role")
    
    print("\nVerifying changes...")
    cur.execute("SELECT username, role FROM users")
    for row in cur.fetchall():
        print(f"  - {row[0]}: {row[1]}")
    
    print("\n✅ All fixes applied! Admin can now login.")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    raise
