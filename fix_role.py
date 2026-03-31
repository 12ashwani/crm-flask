from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# Update the admin user role to lowercase
cur.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
conn.commit()

# Verify the change
cur.execute("SELECT username, role FROM users WHERE username = 'admin'")
user = cur.fetchone()
print(f"✅ Updated admin user: {user[0]} - {user[1]}")

cur.close()
conn.close()
