from bson import ObjectId
from App.domain.interfaces import IDocumentRepository

class MongoDocumentRepository(IDocumentRepository):
    def __init__(self, db_client):
        self.collection = db_client["documents"]

    async def get_by_checksum(self, checksum: str):
        return await self.collection.find_one({"checksum": checksum})

    async def save(self, doc_data: dict):
        await self.collection.insert_one(doc_data)

    async def list_all(self):
        """Return document metadata without the potentially large page content."""
        cursor = self.collection.find({}, {"_id": 1, "filename": 1, "total_pages": 1})
        return [{"id": str(doc["_id"]), "filename": doc["filename"], "total_pages": doc.get("total_pages", 0)} async for doc in cursor]

    async def get_by_id(self, document_id: str):
        """Busca un documento específico por su ID"""
        try:
            doc = await self.collection.find_one({"_id": ObjectId(document_id)})
            if doc:
                doc["id"] = str(doc["_id"])
                del doc["_id"]
            return doc
        except Exception:
            return None

    async def update(self, document_id: str, update_data: dict):
        """Actualiza un documento (ej. cambiarle el nombre)"""
        try:
            result = await self.collection.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": update_data}
            )
            if result.modified_count:
                return await self.get_by_id(document_id)
            return None
        except Exception:
            return None

    async def delete(self, document_id: str):
        """Borra un documento de la base de datos"""
        try:
            result = await self.collection.delete_one({"_id": ObjectId(document_id)})
            return result.deleted_count > 0
        except Exception:
            return False
