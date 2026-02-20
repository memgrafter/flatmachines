"""
Firestore backend for FlatMachines persistence and results.

Implements both PersistenceBackend and ResultBackend using Firestore.
Compatible with Cloud Functions, Firebase, and local emulator.

Document structure:
    Collection: flatmachines (configurable)
    Document ID: {execution_id}
    Subcollections:
        - checkpoints/{step}_{event}
        - results/{path}
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency
_firestore = None
_async_client = None


def _get_firestore():
    global _firestore
    if _firestore is None:
        try:
            from google.cloud import firestore
            _firestore = firestore
        except ImportError:
            raise ImportError(
                "google-cloud-firestore is required for GCP backends. "
                "Install with: pip install flatmachines[gcp]"
            )
    return _firestore


def _get_async_client():
    """Get or create an async Firestore client."""
    global _async_client
    if _async_client is None:
        firestore = _get_firestore()
        _async_client = firestore.AsyncClient()
    return _async_client


class FirestoreBackend:
    """
    Combined Persistence and Result backend using Firestore.
    
    Implements both PersistenceBackend and ResultBackend interfaces.
    Uses a single collection with subcollections for organization.
    
    Args:
        collection: Root collection name (default: "flatmachines")
        project: GCP project ID (optional, uses default)
    
    Document Layout:
        flatmachines/{execution_id}/checkpoints/{step_event} = checkpoint data
        flatmachines/{execution_id}/results/{path} = result data
        flatmachines/{execution_id}/_meta = metadata (created_at, etc.)
    """
    
    def __init__(
        self,
        collection: str = "flatmachines",
        project: Optional[str] = None
    ):
        self.collection = collection
        self.project = project
        self._db = None
    
    @property
    def db(self):
        """Lazy-load Firestore client."""
        if self._db is None:
            firestore = _get_firestore()
            if self.project:
                self._db = firestore.AsyncClient(project=self.project)
            else:
                self._db = firestore.AsyncClient()
        return self._db
    
    def _doc_ref(self, execution_id: str, subcollection: str, doc_id: str):
        """Get document reference."""
        return (
            self.db.collection(self.collection)
            .document(execution_id)
            .collection(subcollection)
            .document(doc_id)
        )
    
    # =========================================================================
    # PersistenceBackend Interface
    # =========================================================================
    
    async def save(self, key: str, value: bytes) -> None:
        """Save checkpoint data.
        
        Args:
            key: Format "{execution_id}/step_{step}_{event}"
            value: JSON-encoded checkpoint bytes
        """
        parts = key.split("/", 1)
        execution_id = parts[0]
        doc_id = parts[1] if len(parts) > 1 else "latest"
        
        doc_ref = self._doc_ref(execution_id, "checkpoints", doc_id)
        
        await doc_ref.set({
            "data": value.decode("utf-8"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        
        logger.debug(f"Firestore: saved checkpoint {execution_id}/{doc_id}")
    
    async def load(self, key: str) -> Optional[bytes]:
        """Load checkpoint data."""
        parts = key.split("/", 1)
        execution_id = parts[0]
        doc_id = parts[1] if len(parts) > 1 else "latest"
        
        doc_ref = self._doc_ref(execution_id, "checkpoints", doc_id)
        doc = await doc_ref.get()
        
        if not doc.exists:
            return None
        
        return doc.to_dict()["data"].encode("utf-8")
    
    async def delete(self, key: str) -> None:
        """Delete checkpoint data."""
        parts = key.split("/", 1)
        execution_id = parts[0]
        doc_id = parts[1] if len(parts) > 1 else "latest"
        
        doc_ref = self._doc_ref(execution_id, "checkpoints", doc_id)
        await doc_ref.delete()
    
    async def list(self, prefix: str) -> List[str]:
        """List all keys matching prefix."""
        execution_id = prefix.rstrip("/")
        
        collection_ref = (
            self.db.collection(self.collection)
            .document(execution_id)
            .collection("checkpoints")
        )
        
        docs = collection_ref.stream()
        keys = []
        async for doc in docs:
            keys.append(f"{execution_id}/{doc.id}")
        
        return sorted(keys)
    
    async def list_execution_ids(self) -> list[str]:
        docs = self.db.collection(self.collection).stream()
        ids = []
        async for doc in docs:
            ids.append(doc.id)
        return sorted(ids)

    async def delete_execution(self, execution_id: str) -> None:
        doc_ref = self.db.collection(self.collection).document(execution_id)
        for subcoll_name in ("checkpoints", "results"):
            subcoll = doc_ref.collection(subcoll_name)
            async for doc in subcoll.stream():
                await doc.reference.delete()
        await doc_ref.delete()

    # =========================================================================
    # ResultBackend Interface
    # =========================================================================
    
    async def write(self, uri: str, data: Any) -> None:
        """Write result to a URI."""
        from ..backends import parse_uri
        
        execution_id, path = parse_uri(uri)
        doc_ref = self._doc_ref(execution_id, "results", path)
        
        await doc_ref.set({
            "data": json.dumps(data),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        
        logger.debug(f"Firestore: wrote result {execution_id}/{path}")
    
    async def read(
        self,
        uri: str,
        block: bool = True,
        timeout: Optional[float] = None
    ) -> Any:
        """Read result from a URI, optionally blocking until available."""
        from ..backends import parse_uri
        
        execution_id, path = parse_uri(uri)
        doc_ref = self._doc_ref(execution_id, "results", path)
        
        start_time = datetime.now(timezone.utc).timestamp()
        poll_interval = 0.5
        
        while True:
            doc = await doc_ref.get()
            
            if doc.exists:
                return json.loads(doc.to_dict()["data"])
            
            if not block:
                return None
            
            if timeout:
                elapsed = datetime.now(timezone.utc).timestamp() - start_time
                if elapsed >= timeout:
                    raise TimeoutError(f"Timeout waiting for result at {uri}")
            
            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 5.0)
    
    async def exists(self, uri: str) -> bool:
        """Check if result exists at URI."""
        from ..backends import parse_uri
        
        execution_id, path = parse_uri(uri)
        doc_ref = self._doc_ref(execution_id, "results", path)
        doc = await doc_ref.get()
        
        return doc.exists
    
    async def delete_result(self, uri: str) -> None:
        """Delete result at URI."""
        from ..backends import parse_uri
        
        execution_id, path = parse_uri(uri)
        doc_ref = self._doc_ref(execution_id, "results", path)
        await doc_ref.delete()
