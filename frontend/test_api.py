from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from api import BackendClient, BackendError


class BackendClientTests(unittest.TestCase):
    @patch("api.requests.post")
    def test_upload_pdf_posts_multipart_and_returns_document(self, post):
        response = Mock(ok=True)
        response.json.return_value = {"document_id": "doc-id", "chunks": 2}
        post.return_value = response

        result = BackendClient("http://localhost:8000").upload_pdf(
            "guide.pdf", b"%PDF-1.7"
        )

        self.assertEqual(result, {"document_id": "doc-id", "chunks": 2})
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "http://localhost:8000/documents")
        self.assertEqual(
            post.call_args.kwargs["files"]["file"],
            ("guide.pdf", b"%PDF-1.7", "application/pdf"),
        )

    @patch("api.requests.post")
    def test_stream_message_parses_events_and_closes_response(self, post):
        response = requests.Response()
        response.status_code = 200
        response.iter_lines = lambda decode_unicode=True: iter(
            [
                b"event: status",
                b'data: {"status": "retrieving"}',
                b"",
                b"event: token",
                b'data: {"text": "Hello"}',
                b"",
            ]
        )
        response.close = Mock()
        post.return_value = response

        events = list(BackendClient("http://localhost:8000").stream_message("id", "Q"))

        self.assertEqual(
            events,
            [
                ("status", {"status": "retrieving"}),
                ("token", {"text": "Hello"}),
            ],
        )
        response.close.assert_called_once()

    @patch("api.requests.post")
    def test_stream_message_rejects_malformed_event_data(self, post):
        response = requests.Response()
        response.status_code = 200
        response.iter_lines = lambda decode_unicode=True: iter(
            [b"event: token", b"data: not-json", b""]
        )
        response.close = Mock()
        post.return_value = response

        with self.assertRaisesRegex(BackendError, "invalid SSE event"):
            list(BackendClient("http://localhost:8000").stream_message("id", "Q"))

        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
