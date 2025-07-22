import motor.motor_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import logging
from config import MONGO_URL, DATABASE_NAME

logger = logging.getLogger(__name__)

class Database:
    client: AsyncIOMotorClient = None
    database: AsyncIOMotorDatabase = None

database = Database()

async def connect_to_mongo():
    """Create database connection"""
    try:
        logger.info("Connecting to MongoDB...")
        database.client = AsyncIOMotorClient(MONGO_URL)
        
        # Test connection
        await database.client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
        
        database.database = database.client[DATABASE_NAME]
        logger.info(f"Connected to database: {DATABASE_NAME}")
        
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise

async def close_mongo_connection():
    """Close database connection"""
    try:
        if database.client:
            database.client.close()
            logger.info("Disconnected from MongoDB")
    except Exception as e:
        logger.error(f"Error closing MongoDB connection: {e}")

def get_database() -> AsyncIOMotorDatabase:
    """Get database instance"""
    return database.database