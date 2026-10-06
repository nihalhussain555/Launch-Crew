"""MongoDB (Motor) connection. `MONGO_URI=mock://` uses an in-memory mongomock DB (dev/tests)."""
from app.config import Settings


def create_client(settings: Settings):
    if settings.mongo_uri.startswith("mock://"):
        from mongomock_motor import AsyncMongoMockClient

        return AsyncMongoMockClient()
    from motor.motor_asyncio import AsyncIOMotorClient

    return AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=8000)


async def ensure_indexes(db) -> None:
    await db.users.create_index("email", unique=True)
    await db.projects.create_index([("user_id", 1), ("created_at", -1)])
    await db.runs.create_index([("project_id", 1), ("created_at", -1)])
    await db.runs.create_index([("user_id", 1), ("created_at", -1)])
    await db.run_events.create_index([("run_id", 1), ("seq", 1)], unique=True)
