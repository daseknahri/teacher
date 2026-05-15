
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"

def reset():
    db_path = r"c:\Users\user\text\storage\app.db"
    if not os.path.exists(db_path):
        print(f"Error: {db_path} not found")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    pwd_hash = hash_password("password123")
    email = "owner@school.edu"
    now_str = datetime.utcnow().isoformat()
    
    # Check if user exists
    cur.execute("SELECT id FROM users WHERE role='owner'")
    row = cur.fetchone()
    
    if row:
        cur.execute("UPDATE users SET email=?, password_hash=?, is_active=1, failed_login_attempts=0 WHERE id=?", (email, pwd_hash, row[0]))
        print(f"Updated existing owner (ID: {row[0]}) to {email}")
    else:
        # Include all NOT NULL fields
        cur.execute("""INSERT INTO users 
            (email, full_name, password_hash, role, is_active, failed_login_attempts, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (email, "School Owner", pwd_hash, "owner", 1, 0, now_str))
        print(f"Created new owner: {email}")
        
    conn.commit()
    conn.close()
    print("Reset complete.")

if __name__ == "__main__":
    reset()
