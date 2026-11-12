from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from grimoire_api.store import SupabaseConversationStore


class InsertQuery:
    def __init__(self):
        self.row = None
        self.selections = []

    def insert(self, row):
        self.row = row
        return self

    def update(self, _row):
        return self

    def eq(self, *_args):
        return self

    def select(self, columns):
        self.selections.append(columns)
        return self

    def execute(self):
        return SimpleNamespace(data=[self.row])


class FakeClient:
    def __init__(self):
        self.query = InsertQuery()

    def table(self, _name):
        return self.query


def test_insert_operations_request_rows_for_persistence_responses():
    client = FakeClient()
    store = SupabaseConversationStore(client)

    conversation = store.create_conversation("Notes")
    message = store.save_message(
        uuid4(),
        "user",
        "Question",
    )

    assert conversation["title"] == "Notes"
    assert message["content"] == "Question"
    assert client.query.selections == [
        "id,title,created_at,updated_at",
        "id,role,content,citations,created_at",
    ]
