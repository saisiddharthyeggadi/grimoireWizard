from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


class SupabaseConversationStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        return response.data or []

    def create_conversation(self, title: str | None) -> dict[str, Any]:
        row = {"id": str(uuid4()), "title": title or "New conversation"}
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
            .range(offset, offset + limit)
            .execute()
        )
        return self._rows(response)

    def get_conversation(self, conversation_id: UUID) -> dict[str, Any] | None:
        response = (
            self.client.table("conversations")
            .select("id,title,created_at,updated_at")
            .eq("id", str(conversation_id))
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
            self.client.table("document_chunks")
            .select("document_id,metadata")
            .eq("document_id", str(document_id))
            .limit(1)
            .execute()
        )
        rows = self._rows(response)
        if not rows:
            return None
        metadata = rows[0].get("metadata") or {}
        return {
            "id": str(document_id),
            "filename": metadata.get("source_file"),
            "status": "ready",
        }

    def attach_document(self, conversation_id: UUID, document_id: UUID) -> None:
        self.client.table("conversation_documents").upsert(
            {
                "conversation_id": str(conversation_id),
                "document_id": str(document_id),
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
        ).eq("id", str(conversation_id)).execute()
