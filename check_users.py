from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor()
cur.execute('SELECT username, role FROM users')
users = cur.fetchall()
conn.close()

print('Available users:')
for user in users:
    print(f'  {user["username"]} - {user["role"]}')