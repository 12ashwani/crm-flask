"""
Comprehensive database migration to fix schema inconsistencies.
"""

from database import get_db_connection, Error

def get_table_structure(cur, table_name):
    """Get the current column structure of a table."""
    cur.execute(f"DESCRIBE {table_name}")
    columns = {}
    for row in cur.fetchall():
        col_name = row[0]
        col_type = row[1]
        columns[col_name] = col_type
    return columns

def migrate():
    """Migrate database schema to match application requirements."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        print("Checking employees table structure...")
        employees_cols = get_table_structure(cur, 'employees')
        print(f"Current employees columns: {list(employees_cols.keys())}")
        
        # Define expected columns for employees
        expected_employees = {
            'id': 'INT AUTO_INCREMENT PRIMARY KEY',
            'name': 'VARCHAR(255)',
            'email': 'VARCHAR(255)',
            'phone': 'VARCHAR(50)',
            'department': 'VARCHAR(100)',
            'role': 'VARCHAR(50)'
        }
        
        # Add missing columns to employees
        for col_name, col_type in expected_employees.items():
            if col_name not in employees_cols:
                print(f"Adding column '{col_name}' to employees table...")
                if col_name == 'id':
                    continue  # Skip primary key
                cur.execute(f"ALTER TABLE employees ADD COLUMN {col_name} {col_type}")
                conn.commit()
                print(f"✅ Added '{col_name}' to employees")
            else:
                print(f"✅ Column '{col_name}' already exists in employees")
        
        print("\nChecking users table structure...")
        users_cols = get_table_structure(cur, 'users')
        print(f"Current users columns: {list(users_cols.keys())}")
        
        # Add employee_id to users if missing
        if 'employee_id' not in users_cols:
            print(f"Adding column 'employee_id' to users table...")
            cur.execute("ALTER TABLE users ADD COLUMN employee_id INT")
            conn.commit()
            print(f"✅ Added 'employee_id' to users")
            
            # Add foreign key constraint
            try:
                cur.execute("""ALTER TABLE users ADD CONSTRAINT fk_user_employee 
                    FOREIGN KEY (employee_id) REFERENCES employees(id)""")
                conn.commit()
                print("✅ Added foreign key constraint")
            except Exception as fk_error:
                print(f"Note: Foreign key may already exist: {fk_error}")
        else:
            print(f"✅ Column 'employee_id' already exists in users")
        
        print("\n✅ Migration complete!")
            
    except Error as e:
        print(f"❌ Migration error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    print("Starting comprehensive database migration...\n")
    migrate()
