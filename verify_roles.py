from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute('SELECT username, role FROM users')
print('Current users:')
for row in cur.fetchall():
    print(f'  - {row["username"]}: {row["role"]}')
cur.close()
conn.close()
