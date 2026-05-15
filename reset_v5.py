
import sqlite3
import hashlib
import secrets
import os

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"

def reset():
    db_path = r"c:\Users\user\text\storage\app.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    email = "owner@school.edu"
    pwd = "password123"
    h = hash_password(pwd)
    
    # Check if user exists
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    
    if row:
        cur.execute("UPDATE users SET password_hash=?, role='owner', is_active=1, failed_login_attempts=0, locked_until=NULL WHERE id=?", (h, row[0]))
        print(f"Updated user ID {row[0]}")
    else:
        cur.execute("INSERT INTO users (email, full_name, password_hash, role, is_active, failed_login_attempts, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (email, "School Owner", h, "owner", 1, 0, "2024-01-01T00:00:00"))
        print(f"Created new user")
        
    conn.commit()
    conn.close()
    print("Success")

if __name__ == "__main__":
    reset()
