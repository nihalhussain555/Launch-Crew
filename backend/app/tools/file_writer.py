"""Artifact storage behind an interface. Swap LocalStorage for an S3/R2 implementation without touching callers."""
import asyncio
import re
from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    @abstractmethod
    async def save(self, run_id: str, name: str, data: bytes) -> str:
        """Persist bytes; returns an opaque key."""

    @abstractmethod
    async def load(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Best-effort removal (default: no-op)."""


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)

    @staticmethod
    def _safe(part: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "_", part)

    async def save(self, run_id: str, name: str, data: bytes) -> str:
        key = f"{self._safe(run_id)}/{self._safe(name)}"
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return key

    async def load(self, key: str) -> bytes:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise FileNotFoundError(key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = (self.root / key).resolve()
        if self.root.resolve() in path.parents:
            await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

class MongoStorage(Storage):
    """Stores blobs in MongoDB (<16MB each). Default: survives Render's ephemeral disk across redeploys."""

    def __init__(self, db):
        self.col = db.blobs

    async def save(self, run_id: str, name: str, data: bytes) -> str:
        key = f"{run_id}/{name}"
        await self.col.replace_one({"_id": key}, {"_id": key, "data": data}, upsert=True)
        return key

    async def delete(self, key: str) -> None:
        await self.col.delete_one({"_id": key})

    async def load(self, key: str) -> bytes:
        doc = await self.col.find_one({"_id": key})
        if not doc:
            raise FileNotFoundError(key)
        return bytes(doc["data"])


# S3/R2: implement `Storage` with boto3 (put_object / get_object, key = f"{run_id}/{name}") and return it
# from build_storage(). Callers only depend on save()/load(), so nothing else changes.
def build_storage(settings, db) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_dir)
    return MongoStorage(db)
