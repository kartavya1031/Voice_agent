
import sys
sys.path.insert(0, '.')

from app.db.session import SessionLocal
from app.db.models import User

def list_users():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        if not users:
            print("No users found in the database.")
            return

        print(f"Found {len(users)} users:")
        print("-" * 50)
        for u in users:
            print(f"ID: {u.id}")
            print(f"Username: {u.username}")
            print(f"Display Name: {u.display_name}")
            print(f"Role: {u.role}")
            print(f"Email: {u.email}")
            print(f"Organization ID: {u.organization_id}")
            # we can't show password because it is hashed
            print("-" * 50)
    except Exception as e:
        print(f"Error querying users: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    list_users()
