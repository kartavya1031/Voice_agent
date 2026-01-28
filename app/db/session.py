"""
Database session configuration for MySQL connection
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

load_dotenv()

# Database configuration from environment variables
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "ai_voice_calls")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")

# Create MySQL connection URL
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Check connection health before using
    pool_recycle=3600,   # Recycle connections after 1 hour
    echo=False           # Set to True for SQL query logging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Session:
    """
    Dependency to get database session.
    Use in FastAPI endpoints with Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    from app.db.models import (
        Organization, Agent, KnowledgeBase,  # New multi-tenant models
        Call, CallTranscript, CallFile, CallMetric, User
    )
    from sqlalchemy import text
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables initialized (including multi-tenant tables)")
    
    # Simple migration for existing tables (add missing columns)
    # NOTE: This MUST run BEFORE ensure_admin_exists() to add organization_id column
    try:
        with engine.connect() as conn:
            # Check/Add user_id to calls
            try:
                conn.execute(text("SELECT user_id FROM calls LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding user_id to calls table")
                try:
                    conn.execute(text("ALTER TABLE calls ADD COLUMN user_id VARCHAR(36)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add user_id column: {e}")
            
            # Check/Add agent_id to calls (NEW)
            try:
                conn.execute(text("SELECT agent_id FROM calls LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding agent_id to calls table")
                try:
                    conn.execute(text("ALTER TABLE calls ADD COLUMN agent_id VARCHAR(36)"))
                    conn.execute(text("CREATE INDEX ix_calls_agent_id ON calls(agent_id)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add agent_id column: {e}")
            
            # Check/Add contact_name to calls
            try:
                conn.execute(text("SELECT contact_name FROM calls LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding contact_name to calls table")
                try:
                    conn.execute(text("ALTER TABLE calls ADD COLUMN contact_name VARCHAR(100)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add contact_name column: {e}")
            
            # Check/Add organization_id to users (NEW)
            try:
                conn.execute(text("SELECT organization_id FROM users LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding organization_id to users table")
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN organization_id VARCHAR(36)"))
                    conn.execute(text("CREATE INDEX ix_users_organization_id ON users(organization_id)"))
                except Exception as e:
                    conn.execute(text("CREATE INDEX ix_users_organization_id ON users(organization_id)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add organization_id column: {e}")
            
            # Check/Add agent_id to knowledge_bases (NEW)
            try:
                conn.execute(text("SELECT agent_id FROM knowledge_bases LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding agent_id to knowledge_bases table")
                try:
                    conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN agent_id VARCHAR(36)"))
                    conn.execute(text("CREATE INDEX ix_knowledge_bases_agent_id ON knowledge_bases(agent_id)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add agent_id column to knowledge_bases: {e}")
            
            conn.commit()
                    
    except Exception as e:
        print(f"⚠️ Migration warning: {e}")
    
    # Ensure default admin user exists (AFTER migrations complete)
    from app.db.service import user_service
    user_service.ensure_admin_exists()


def test_connection():
    """Test database connection"""
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print("✅ Database connection successful")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
