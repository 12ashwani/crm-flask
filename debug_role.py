from database import get_db_connection
from werkzeug.security import check_password_hash

conn = get_db_connection()
cur = conn.cursor(dictionary=True)

# First, let's see what's in the database exactly 
cur.execute("SELECT id, username, role, password FROM users WHERE username='admin'")
user = cur.fetchone()
print(f"Current admin in DB:")
print(f"  ID: {user['id']}")
print(f"  Username: {user['username']}")
print(f"  Role (raw): '{user['role']}'")
print(f"  Role length: {len(user['role'])}")
print(f"  Role bytes: {user['role'].encode()}")

# Now update to lowercase
cur.execute("UPDATE users SET role='admin' WHERE username='admin'")
conn.commit()

# Verify it worked
cur.execute("SELECT role FROM users WHERE username='admin'")
new_role = cur.fetchone()['role']
print(f"\n✅ After update:")
print(f"  Role (raw): '{new_role}'")
print(f"  Role length: {len(new_role)}")

# Test password
test_pass = "admin123"
password_hash = user['password']
is_valid = check_password_hash(password_hash, test_pass)
print(f"\n✅ Password 'admin123' matches: {is_valid}")

cur.close()
conn.close()
