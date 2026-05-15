
import sys
import os
from pathlib import Path

# Add backend to path to import models and services
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.database import SessionLocal, engine, Base
from app.models import User, UserRole
from app.services.auth import hash_password
from sqlalchemy import select, delete

def reset_owner():
    db = SessionLocal()
    try:
        # Clear existing owner(s)
        db.execute(delete(User).where(User.role == UserRole.OWNER))
        db.commit()

        # Create new owner
        owner = User(
            email="owner@school.edu",
            full_name="School Owner",
            password_hash=hash_password("password123"),
            role=UserRole.OWNER,
            is_active=True
        )
        db.add(owner)
        db.commit()
        print("Owner reset successful: owner@school.edu / password123")
    except Exception as e:
        print(f"Error resetting owner: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_owner()
