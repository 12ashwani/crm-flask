"""Test script to verify admin login can work"""
from database import get_db_connection
from werkzeug.security import check_password_hash

conn = get_db_connection()
cur = conn.cursor(dictionary=True)

# Get admin user
cur.execute("SELECT * FROM users WHERE username='admin'")
user = cur.fetchone()

print("="*60)
print("LOGIN TEST VERIFICATION")
print("="*60)
print(f"\nAdmin User Found: {user is not None}")

if user:
    print(f"Username: {user['username']}")
    print(f"Role: {user['role']}")
    print(f"Password field: (hashed)")
    
    # Simulate login check
    test_password = "admin123"
    password_valid = check_password_hash(user['password'], test_password)
    print(f"\nPassword 'admin123' matches: {password_valid}")
    
    # Simulate role check (from login route)
    role = user['role']
    print(f"\nRole Check:")
    print(f"  user['role'] == 'admin': {role == 'admin'}")
    
    if role == "admin":
        print(f"  ✅ Login will redirect to ADMIN DASHBOARD")
    elif role == "marketing":
        print(f"  ✅ Login will redirect to MARKETING DASHBOARD")
    elif role == "operations":
        print(f"  ✅ Login will redirect to OPERATIONS DASHBOARD")
    elif role == "accounts":
        print(f"  ✅ Login will redirect to ACCOUNTS DASHBOARD")
    else:
        print(f"  ❌ Will trigger: Unknown role. Contact admin.")

cur.close()
conn.close()

print("\n" + "="*60)
print("You can now login with:")
print("  Username: admin")
print("  Password: admin123")
print("="*60)
