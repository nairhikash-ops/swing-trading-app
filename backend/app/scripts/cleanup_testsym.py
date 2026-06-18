import sqlite3
import sys

def main():
    db_path = '/app/data/dhan_auth.sqlite3'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        count = c.execute("SELECT count(*) FROM ml_samples WHERE symbol = 'TESTSYM'").fetchone()[0]
        print(f"TESTSYM count: {count}")
        
        c.execute("DELETE FROM ml_samples WHERE symbol = 'TESTSYM'")
        conn.commit()
        print("Successfully deleted TESTSYM records.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
