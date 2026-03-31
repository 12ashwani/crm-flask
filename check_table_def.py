from database import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# Check the table structure
cur.execute("SHOW CREATE TABLE users")
table_def = cur.fetchone()
print("Users table definition:")
print(table_def[1])
print("\n" + "="*60 + "\n")

# Check column details
cur.execute("SHOW FULL COLUMNS FROM users")
columns = cur.fetchall()
print("Column details:")
for col in columns:
    print(f"  {col}")

cur.close()
conn.close()
