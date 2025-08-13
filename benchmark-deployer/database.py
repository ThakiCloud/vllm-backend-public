"""MongoDB database connection and management for benchmark-deployer."""

import logging
import motor.motor_asyncio
from pymongo.errors import ConnectionFailure
from pymongo import ReadPreference
from typing import Optional

from config import MONGO_URL, DB_NAME, DEPLOYMENTS_COLLECTION

logger = logging.getLogger(__name__)

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
            read_preference=ReadPreference.SECONDARY_PREFERRED,
            serverSelectionTimeoutMS=60000,
            connectTimeoutMS=60000
        )
        db.db = db.client[DB_NAME]
        
        # Test connection
        await db.client.admin.command('ping')
        logger.info("MongoDB connected successfully.")
        
        # Create indexes
        await create_indexes()
        logger.info("Database indexes created successfully.")
        
    except ConnectionFailure as e:
        logger.error(f"Could not connect to MongoDB: {e}")
        raise

async def close_mongo_connection():
    """Close database connection."""
    if db.client:
        db.client.close()
        logger.info("MongoDB connection closed.")

async def create_indexes():
    """Create database indexes for better performance."""
    try:
        # Deployments collection indexes
        await db.db[DEPLOYMENTS_COLLECTION].create_index([("deployment_id", 1)], unique=True)
        await db.db[DEPLOYMENTS_COLLECTION].create_index([("resource_name", 1)])
        await db.db[DEPLOYMENTS_COLLECTION].create_index([("resource_type", 1)])
        await db.db[DEPLOYMENTS_COLLECTION].create_index([("namespace", 1)])
        await db.db[DEPLOYMENTS_COLLECTION].create_index([("status", 1)])
        await db.db[DEPLOYMENTS_COLLECTION].create_index([("created_at", -1)])
        
        logger.info("All indexes created successfully.")
        
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")
        # Don't raise - indexes are not critical for basic functionality
        # raise

async def check_mongo_health():
    """Check MongoDB connection health."""
    try:
        await db.client.admin.command('ping')
        logger.debug("MongoDB health check passed")
        return True
    except Exception as e:
        logger.warning(f"MongoDB health check failed: {e}")
        return False

# -----------------------------------------------------------------------------
# Database Access Functions
# -----------------------------------------------------------------------------

def get_database():
    """Get database instance."""
    return db.db

def get_deployments_collection():
    """Get deployments collection."""
    return db.db[DEPLOYMENTS_COLLECTION] 
