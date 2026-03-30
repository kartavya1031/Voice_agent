"""
Script to create a test organization and user for multi-tenant testing
"""
import sys
sys.path.insert(0, '.')

from app.db.session import SessionLocal
from app.db.models import Organization, User
from app.db.service import UserService
import uuid
from datetime import datetime

def create_test_org_and_user():
    db = SessionLocal()
    try:
        # 1. Create Organization
        org_id = str(uuid.uuid4())
        org = Organization(
            id=org_id,
            name="Test Organization 2",
            slug="test-org-2",
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(org)
        db.commit()
        print(f"✅ Created Organization: {org.name} (ID: {org_id})")
        
        # 2. Update user2 with organization_id
        user = db.query(User).filter(User.username == "user2").first()
        if user:
            user.organization_id = org_id
            db.commit()
            print(f"✅ Updated user2 with organization_id: {org_id}")
        else:
            # Create user2 if doesn't exist
            password_hash = UserService.hash_password("Admin@123")
            user = User(
                username="user2",
                password_hash=password_hash,
                role="org_admin",
                display_name="Test User 2",
                email="user2@test.com",
                organization_id=org_id,
                is_active=True
            )
            db.add(user)
            db.commit()
            print(f"✅ Created user2 with organization_id: {org_id}")
        
        print(f"\n📋 Summary:")
        print(f"   Organization: {org.name}")
        print(f"   Organization ID: {org_id}")
        print(f"   Username: user2")
        print(f"   Password: Admin@123")
        print(f"\n🔒 This user will only see agents/calls for 'Test Organization 2'")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    create_test_org_and_user()
