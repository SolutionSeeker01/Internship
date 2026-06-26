import os
import sys
import getpass

# Add parent directory of 'scratch' to sys.path to allow absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database.db import SessionLocal
from models.user import User, UserRole
from security.password import hash_password

def bootstrap_master():
    """
    Interactively registers the initial MASTER user for the R2R platform if none exists.
    """
    session = SessionLocal()
    try:
        # Check if a MASTER user is already present in the database
        existing_master = session.query(User).filter(User.role == UserRole.MASTER).first()
        if existing_master:
            print("MASTER user already exists.\nBootstrap aborted.")
            return

        print("--- R2R Platform Master User Bootstrap ---")
        username = input("Enter username: ").strip().lower()
        email = input("Enter email: ").strip()
        
        if not username or not email:
            print("Error: Username and email cannot be empty.")
            return
            
        password = getpass.getpass("Enter password: ")
        if not password:
            print("Error: Password cannot be empty.")
            return

        # Hash credentials securely using bcrypt
        password_hash = hash_password(password)

        # Create master user
        master_user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            role=UserRole.MASTER,
            is_active=True
        )

        session.add(master_user)
        session.commit()

        print("\nMASTER user created successfully.")
        print(f"Username: {username}")
        print(f"Role: {UserRole.MASTER.value}")

    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    bootstrap_master()
