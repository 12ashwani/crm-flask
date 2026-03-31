from database import get_db_connection
from werkzeug.security import check_password_hash

conn = get_db_connection()
cur = conn.cursor()
cur.execute('SELECT username, password FROM users WHERE username="admin"')
user = cur.fetchone()
conn.close()

if user:
    print(f'Username: {user["username"]}')
    print(f'Password hash: {user["password"]}')
    # Test password
    test_password = 'admin123'
    if check_password_hash(user['password'], test_password):
        print('✅ Password verification works')
    else:
        print('❌ Password verification failed')
else:
    print('Admin user not found')