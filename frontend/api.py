from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import requests


class BackendError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, base_url: str, timeout: tuple[float, float] = (10, 180)):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as error:
            raise BackendError(
                f"Could not reach the backend at {self.base_url}: {error}"
            ) from error

        if not response.ok:
            try:
                details = response.json()
            except ValueError:
                details = response.text
            if isinstance(details, dict):
                details = details.get("detail", details)
            raise BackendError(f"Backend returned HTTP {response.status_code}: {details}")

        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise BackendError("Backend returned an invalid JSON response.") from error

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def list_conversations(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._request(
                "GET",
                "/conversations",
                params={"limit": 100, "offset": offset},
            )
            items.extend(page["items"])
            if not page["has_more"]:
                return items
            offset += page["limit"]

    def create_conversation(self, title: str | None) -> dict[str, Any]:
        body = {"title": title} if title else {}
        return self._request("POST", "/conversations", json=body)

    def upload_pdf(self, filename: str, content: bytes) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{self.base_url}/documents",
                files={"file": (filename, content, "application/pdf")},
                timeout=(10, 1800),
            )
        except requests.RequestException as error:
            raise BackendError(
                f"Could not upload the PDF to {self.base_url}: {error}"
            ) from error

        if not response.ok:
            try:
                details = response.json()
            except ValueError:
                details = response.text
            if isinstance(details, dict):
                details = details.get("detail", details)
            raise BackendError(f"Backend returned HTTP {response.status_code}: {details}")

        try:
            return response.json()
        except ValueError as error:
            raise BackendError("Backend returned an invalid upload response.") from error

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/conversations/{conversation_id}")

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/conversations/{conversation_id}/messages")

    def attach_document(
        self, conversation_id: str, document_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/conversations/{conversation_id}/documents",
            json={"document_id": document_id},
        )

    def stream_message(
        self, conversation_id: str, content: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        try:
            response = requests.post(
                f"{self.base_url}/conversations/{conversation_id}/messages",
                json={"content": content},
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise BackendError(
                f"Could not reach the backend at {self.base_url}: {error}"
            ) from error

        try:
            if not response.ok:
                try:
                    details = response.json()
                except ValueError:
                    details = response.text
                if isinstance(details, dict):
                    details = details.get("detail", details)
                raise BackendError(
                    f"Backend returned HTTP {response.status_code}: {details}"
                )

            event_name = "message"
            data_lines: list[str] = []
            for raw_line in response.iter_lines(decode_unicode=True):
                if raw_line is None:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line:
                    if data_lines:
                        yield event_name, self._decode_event(data_lines)
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                field, separator, value = line.partition(":")
                if separator and value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    event_name = value
                elif field == "data":
                    data_lines.append(value)
            if data_lines:
                yield event_name, self._decode_event(data_lines)
        except requests.RequestException as error:
            raise BackendError(f"The answer stream was interrupted: {error}") from error
        finally:
            response.close()

    @staticmethod
    def _decode_event(data_lines: list[str]) -> dict[str, Any]:
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as error:
            raise BackendError("Backend sent an invalid SSE event.") from error
        if not isinstance(payload, dict):
            raise BackendError("Backend sent an unexpected SSE event payload.")
        return payload
