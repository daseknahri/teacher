
import sys
import os
from pathlib import Path

# Absolute path to DB
db_abs = r"c:\Users\user\text\storage\app.db"
os.environ["DATABASE_URL"] = f"sqlite:///{db_abs}"

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.database import SessionLocal
from app.models import User, UserRole
from app.services.auth import hash_password
from sqlalchemy import select, delete
from datetime import datetime

def reset():
    db = SessionLocal()
    try:
        # Clear existing owners
        db.execute(delete(User).where(User.role == UserRole.OWNER))
        db.commit()

        email = "owner@school.edu"
        pwd = "password123"
        h = hash_password(pwd)
        
        owner = User(
            email=email,
            full_name="School Owner",
            password_hash=h,
            role=UserRole.OWNER,
            is_active=True,
            failed_login_attempts=0,
            created_at=datetime.utcnow()
        )
        db.add(owner)
        db.commit()
        print(f"Reset OK: {email} / {pwd}")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset()
