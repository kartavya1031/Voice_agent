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
    from app.db.models import Call, CallTranscript, CallFile, CallMetric, User
    from sqlalchemy import text
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables initialized")
    
    # Ensure default admin user exists
    from app.db.service import user_service
    user_service.ensure_admin_exists()
    
    # Simple migration for existing tables (add missing columns)
    try:
        with engine.connect() as conn:
            # Check/Add user_id to calls
            try:
                conn.execute(text("SELECT user_id FROM calls LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding user_id to calls table")
                try:
                    conn.execute(text("ALTER TABLE calls ADD COLUMN user_id VARCHAR(36)"))
                    # Try to add FK, might fail if some users don't exist, so we skip FK constraint for now or be careful
                    # conn.execute(text("ALTER TABLE calls ADD CONSTRAINT fk_calls_user FOREIGN KEY (user_id) REFERENCES users(id)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add user_id column: {e}")
            
            # Check/Add contact_name to calls
            try:
                conn.execute(text("SELECT contact_name FROM calls LIMIT 1"))
            except Exception:
                print("🔄 Migrating: Adding contact_name to calls table")
                try:
                    conn.execute(text("ALTER TABLE calls ADD COLUMN contact_name VARCHAR(100)"))
                except Exception as e:
                    print(f"   ⚠️ Could not add contact_name column: {e}")
                    
    except Exception as e:
        print(f"⚠️ Migration warning: {e}")


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
