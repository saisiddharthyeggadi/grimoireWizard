from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

DOCUMENTS_BUCKET = "documents"
SIGNED_URL_TTL_SECONDS = 300


class SupabaseConversationStore:
    def __init__(self, client: Any, user_id: str) -> None:
        self.client = client
        self.user_id = user_id

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        return response.data or []

    def create_conversation(self, title: str | None) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "user_id": self.user_id,
            "title": title or "New conversation",
        }
        response = (
            self.client.table("conversations")
            .insert(row)
            .select("id,title,created_at,updated_at")
            .execute()
        )
        return self._rows(response)[0]

    def list_conversations(self, limit: int, offset: int) -> list[dict[str, Any]]:
        response = (
            self.client.table("conversations")
            .select("id,title,created_at,updated_at")
            .order("updated_at", desc=True)
            .eq("user_id", self.user_id)
            .range(offset, offset + limit)
            .execute()
        )
        return self._rows(response)

    def get_conversation(self, conversation_id: UUID) -> dict[str, Any] | None:
        response = (
            self.client.table("conversations")
            .select("id,title,created_at,updated_at")
            .eq("id", str(conversation_id))
            .eq("user_id", self.user_id)
            .limit(1)
            .execute()
        )
        rows = self._rows(response)
        if not rows:
            return None

        conversation = rows[0]
        conversation["documents"] = self.get_attached_documents(conversation_id)
        return conversation

    def get_attached_documents(self, conversation_id: UUID) -> list[dict[str, Any]]:
        response = (
            self.client.table("conversation_documents")
            .select("document_id,created_at")
            .eq("conversation_id", str(conversation_id))
            .eq("user_id", self.user_id)
            .order("created_at")
            .execute()
        )
        documents = []
        for attachment in self._rows(response):
            details = self.get_document(UUID(attachment["document_id"]))
            if details is not None:
                details["attached_at"] = attachment["created_at"]
                documents.append(details)
        return documents

    def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        response = (
            self.client.table("documents")
            .select("id,filename,status,page_count,chunk_count,created_at")
            .eq("id", str(document_id))
            .eq("user_id", self.user_id)
            .limit(1)
            .execute()
        )
        rows = self._rows(response)
        if not rows:
            return None
        return self._document_info(rows[0])

    def list_documents(self, limit: int, offset: int) -> dict[str, Any]:
        response = (
            self.client.table("documents")
            .select(
                "id,filename,status,page_count,chunk_count,created_at",
                count="exact",
            )
            .order("created_at", desc=True)
            .eq("user_id", self.user_id)
            .range(offset, offset + limit - 1)
            .execute()
        )
        rows = self._rows(response)
        total = response.count or 0
        return {
            "items": [self._document_info(row) for row in rows],
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(rows) < total,
        }

    def save_document(
        self,
        document_id: str,
        filename: str,
        content: bytes,
        page_count: int,
        chunk_count: int,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        storage_path = f"{user_id}/{document_id}/document.pdf"
        bucket = self.client.storage.from_(DOCUMENTS_BUCKET)
        bucket.upload(
            storage_path,
            content,
            {"content-type": "application/pdf", "upsert": "true"},
        )
        checksum = hashlib.sha256(content).hexdigest()
        response = (
            self.client.table("documents")
            .upsert(
                {
                    "id": document_id,
                    "user_id": user_id,
                    "sha256": checksum,
                    "filename": filename,
                    "storage_path": storage_path,
                    "status": "ready",
                    "page_count": page_count,
                    "chunk_count": chunk_count,
                    "error": None,
                },
                on_conflict="id",
            )
            .select("id,filename,status,page_count,chunk_count,created_at")
            .execute()
        )
        rows = self._rows(response)
        if not rows:
            raise RuntimeError("Supabase did not return the saved document.")
        return self._document_info(rows[0])

    def get_document_file_url(self, document_id: UUID) -> str | None:
        response = (
            self.client.table("documents")
            .select("storage_path")
            .eq("id", str(document_id))
            .eq("user_id", self.user_id)
            .limit(1)
            .execute()
        )
        rows = self._rows(response)
        if not rows or not rows[0].get("storage_path"):
            return None

        result = self.client.storage.from_(DOCUMENTS_BUCKET).create_signed_url(
            rows[0]["storage_path"],
            SIGNED_URL_TTL_SECONDS,
        )
        signed_url = result.get("signedURL") or result.get("signedUrl")
        if not signed_url:
            raise RuntimeError("Supabase did not return a signed document URL.")
        return signed_url

    @staticmethod
    def _document_info(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "filename": row["filename"],
            "status": row["status"],
            "pages": row.get("page_count"),
            "chunks": row.get("chunk_count"),
            "created_at": row.get("created_at"),
        }

    def attach_document(self, conversation_id: UUID, document_id: UUID) -> None:
        self.client.table("conversation_documents").upsert(
            {
                "conversation_id": str(conversation_id),
                "document_id": str(document_id),
                "user_id": self.user_id,
            },
            on_conflict="conversation_id,document_id",
            ignore_duplicates=True,
        ).execute()
        self._touch_conversation(conversation_id)

    def get_messages(self, conversation_id: UUID) -> list[dict[str, Any]]:
        response = (
            self.client.table("messages")
            .select("id,role,content,citations,created_at")
            .eq("conversation_id", str(conversation_id))
            .eq("user_id", self.user_id)
            .order("created_at")
            .execute()
        )
        return self._rows(response)

    def save_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        response = (
            self.client.table("messages")
            .insert(
                {
                    "id": str(uuid4()),
                    "conversation_id": str(conversation_id),
                    "user_id": self.user_id,
                    "role": role,
                    "content": content,
                    "citations": citations or [],
                }
            )
            .select("id,role,content,citations,created_at")
            .execute()
        )
        self._touch_conversation(conversation_id)
        return self._rows(response)[0]

    def search_chunks(
        self,
        query_embedding: list[float],
        query_text: str,
        document_ids: list[UUID],
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        response = self.client.rpc(
            "search_document_chunks",
            {
                "query_embedding": query_embedding,
                "query_text": query_text,
                "document_ids": [str(document_id) for document_id in document_ids],
                "result_limit": limit,
            },
        ).execute()
        return self._rows(response)

    def _touch_conversation(self, conversation_id: UUID) -> None:
        self.client.table("conversations").update(
            {"updated_at": datetime.now(UTC).isoformat()}
        ).eq("id", str(conversation_id)).eq("user_id", self.user_id).execute()
