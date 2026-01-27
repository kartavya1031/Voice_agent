"""
Database migration script to add new columns for call tracking
"""
from app.db.session import engine
from sqlalchemy import text

def run_migration():
    with engine.connect() as conn:
        # Add new columns to the calls table if they don't exist
        try:
            conn.execute(text("ALTER TABLE calls ADD COLUMN status VARCHAR(30) DEFAULT 'initiated'"))
            print('✅ Added status column')
        except Exception as e:
            if "Duplicate column" in str(e):
                print('⏭️ status column already exists')
            else:
                print(f'❌ status column: {e}')
        
        try:
            conn.execute(text("ALTER TABLE calls ADD COLUMN recording_url TEXT"))
            print('✅ Added recording_url column')
        except Exception as e:
            if "Duplicate column" in str(e):
                print('⏭️ recording_url column already exists')
            else:
                print(f'❌ recording_url column: {e}')
        
        try:
            conn.execute(text("ALTER TABLE calls ADD COLUMN recording_id VARCHAR(100)"))
            print('✅ Added recording_id column')
        except Exception as e:
            if "Duplicate column" in str(e):
                print('⏭️ recording_id column already exists')
            else:
                print(f'❌ recording_id column: {e}')
        
        try:
            conn.execute(text("ALTER TABLE calls ADD COLUMN stream_id VARCHAR(100)"))
            print('✅ Added stream_id column')
        except Exception as e:
            if "Duplicate column" in str(e):
                print('⏭️ stream_id column already exists')
            else:
                print(f'❌ stream_id column: {e}')
        
        conn.commit()
        print('🎉 Migration complete!')

if __name__ == "__main__":
    run_migration()
