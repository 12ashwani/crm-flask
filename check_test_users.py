from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor()
cur.execute('SELECT username, password FROM users WHERE username LIKE "EMP%"')
users = cur.fetchall()
conn.close()

print('Test users:')
for user in users:
    print(f'  {user["username"]} - password hash: {user["password"][:30]}...')