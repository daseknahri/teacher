
import sqlite3
import hashlib
import hmac
import os

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", maxsplit=1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(candidate, digest)

def check():
    db_path = r"c:\Users\user\text\storage\app.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT email, password_hash, is_active FROM users WHERE email='owner@school.edu'")
    row = cur.fetchone()
    if row:
        email, stored_hash, active = row
        print(f"User: {email}, Active: {active}")
        print(f"Hash: {stored_hash}")
        matches = verify_password("password123", stored_hash)
        print(f"Password 'password123' matches: {matches}")
    else:
        print("User not found")
    conn.close()

if __name__ == "__main__":
    check()
