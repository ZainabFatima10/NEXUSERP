import sqlite3
import pandas as pd
import os

def setup_database(csv_path, db_path):
    print(f"Reading data from {csv_path}...")
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return
        
    df = pd.read_csv(csv_path)
    
    print(f"Connecting to SQLite database at {db_path}...")
    # This will create the file if it doesn't exist
    conn = sqlite3.connect(db_path)
    
    # Write the dataframe to an SQL table called 'sales'
    # if_exists='replace' will overwrite the table if it already exists
    print("Writing data to database table 'sales'...")
    df.to_sql('sales', conn, if_exists='replace', index=False)
    
    # Verify the insertion
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sales")
    count = cursor.fetchone()[0]
    print(f"Successfully inserted {count} rows into the 'sales' table.")
    
    conn.close()
    print("Database setup complete!")

if __name__ == "__main__":
    sales_csv = 'd:/fyp/sales_data.csv'
    sales_db = 'd:/fyp/sales_data.db'
    setup_database(sales_csv, sales_db)
