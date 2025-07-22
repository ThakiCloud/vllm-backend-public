import motor.motor_asyncio
from pymongo.errors import ConnectionFailure
from pymongo import ReadPreference
import logging
from typing import Optional

from config import MONGO_URL, DB_NAME, PROJECTS_COLLECTION, ORIGINAL_FILES_COLLECTION, MODIFIED_FILES_COLLECTION

# -----------------------------------------------------------------------------
# Database Connection
# -----------------------------------------------------------------------------

class Database:
    client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
    db = None

db = Database()

async def connect_to_mongo():
    """Create database connection."""
    try:
        db.client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGO_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000
        )
        db.db = db.client[DB_NAME]
        
        # Test connection
        await db.client.admin.command('ping')
        logging.info("MongoDB connected successfully.")
        
        # Create indexes
        await create_indexes()
        logging.info("Database indexes created successfully.")
        
    except ConnectionFailure as e:
        logging.error(f"Could not connect to MongoDB: {e}")
        raise

async def close_mongo_connection():
    """Close database connection."""
    if db.client:
        db.client.close()
        logging.info("MongoDB connection closed.")

async def create_indexes():
    """Create database indexes for better performance."""
    try:
        # Projects collection indexes
        await db.db[PROJECTS_COLLECTION].create_index([("project_id", 1)], unique=True)
        await db.db[PROJECTS_COLLECTION].create_index([("name", 1)])
        
        # Original files collection indexes
        await db.db[ORIGINAL_FILES_COLLECTION].create_index([("file_id", 1)], unique=True)
        await db.db[ORIGINAL_FILES_COLLECTION].create_index([("project_id", 1)])
        await db.db[ORIGINAL_FILES_COLLECTION].create_index([("file_path", 1)])
        await db.db[ORIGINAL_FILES_COLLECTION].create_index([("file_type", 1)])
        await db.db[ORIGINAL_FILES_COLLECTION].create_index([("project_id", 1), ("file_path", 1)], unique=True)
        
        # Modified files collection indexes
        await db.db[MODIFIED_FILES_COLLECTION].create_index([("file_id", 1)], unique=True, sparse=True)
        await db.db[MODIFIED_FILES_COLLECTION].create_index([("project_id", 1)])
        await db.db[MODIFIED_FILES_COLLECTION].create_index([("file_path", 1)])
        await db.db[MODIFIED_FILES_COLLECTION].create_index([("file_type", 1)])
        await db.db[MODIFIED_FILES_COLLECTION].create_index([("project_id", 1), ("file_path", 1)])
        
        logging.info("All indexes created successfully.")
        
    except Exception as e:
        logging.error(f"Error creating indexes: {e}")
        # Don't raise - indexes are not critical for basic functionality
        # raise

# -----------------------------------------------------------------------------
# Database Access Functions
# -----------------------------------------------------------------------------

def get_projects_collection():
    """Get projects collection."""
    return db.db[PROJECTS_COLLECTION]

def get_original_files_collection():
    """Get original files collection."""
    return db.db[ORIGINAL_FILES_COLLECTION]

def get_modified_files_collection():
    """Get modified files collection."""
    return db.db[MODIFIED_FILES_COLLECTION]

 