"""
Migration script to add account_executive column to leads table
"""
import mysql.connector
from mysql.connector import Error

config = {
    "host": "localhost",
    "user": "root",
    "password": "Ecs@1234",
    "database": "crm_db"
}

def migrate():
    conn = mysql.connector.connect(**config)
    cur = conn.cursor()
    
    try:
        # Check if account_executive column exists
        cur.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME='leads' AND COLUMN_NAME='account_executive'
        """)
        
        if not cur.fetchone():
            print("Adding 'account_executive' column to leads table...")
            cur.execute("""
                ALTER TABLE leads 
                ADD COLUMN account_executive INT,
                ADD FOREIGN KEY (account_executive) REFERENCES employees(id)
            """)
            conn.commit()
            print("✅ Added account_executive column to leads table")
        else:
            print("✅ account_executive column already exists in leads table")
            
    except Error as e:
        print(f"❌ Migration error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    print("Starting database migration...")
    migrate()
    print("Migration complete!")
