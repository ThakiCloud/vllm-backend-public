"""MongoDB database connection and management."""

import logging
import motor.motor_asyncio
from pymongo.errors import ConnectionFailure
from pymongo import ReadPreference
from config import MONGO_URL, DB_NAME, RAW_COLLECTION_NAME, STANDARDIZED_COLLECTION_NAME

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# MongoDB Client and Collections
# -----------------------------------------------------------------------------

# Create client with direct primary connection
client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URL,
    # Prefer secondary for reads, fallback to primary if no secondary available
    read_preference=ReadPreference.SECONDARY_PREFERRED
    serverSelectionTimeoutMS=60000,
    connectTimeoutMS=60000,
)

db = client[DB_NAME]
raw_collection = db[RAW_COLLECTION_NAME]
standardized_collection = db[STANDARDIZED_COLLECTION_NAME]

# -----------------------------------------------------------------------------
# Connection Management Functions
# -----------------------------------------------------------------------------

async def connect_to_mongo():
    """Initialize MongoDB connection and create indexes."""
    try:
        await client.admin.command('ping')
        logger.info("MongoDB connected successfully.")
        
        # Create a unique index on pk for both collections
        await raw_collection.create_index([("pk", 1)], unique=True)
        await standardized_collection.create_index([("pk", 1)], unique=True)
        logger.info("Index on pk ensured for both collections.")
    except ConnectionFailure as e:
        logger.error(f"Could not connect to MongoDB: {e}")
        # Depending on the use case, you might want to exit the application
        # For now, we'll just log the error.
        pass

async def close_mongo_connection():
    """Close MongoDB connection."""
    client.close()
    logger.info("MongoDB connection closed.")

async def check_mongo_health():
    """Check MongoDB connection health."""
    try:
        await client.admin.command('ping')
        logger.debug("MongoDB health check passed")
        return True
    except ConnectionFailure as e:
        logger.warning(f"MongoDB health check failed: {e}")
        return False

# -----------------------------------------------------------------------------
# Database Access Functions
# -----------------------------------------------------------------------------

def get_raw_collection():
    """Get the raw results collection."""
    return raw_collection

def get_standardized_collection():
    """Get the standardized results collection."""
    return standardized_collection 
