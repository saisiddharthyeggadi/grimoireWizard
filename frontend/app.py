from __future__ import annotations

import os
from typing import Any

import streamlit as st

from api import BackendClient, BackendError


def _render_citations(
    citations: list[dict[str, Any]], document_names: dict[str, str]
) -> None:
    if not citations:
        return
    with st.expander(f"Sources ({len(citations)})"):
        for index, citation in enumerate(citations, start=1):
            page = citation.get("page", "?")
            document_id = citation.get("document_id")
            filename = document_names.get(document_id, document_id or "Document")
            st.markdown(f"**[{index}] {filename} · page {page}**")
            snippet = citation.get("snippet")
            if snippet:
                st.caption(snippet)


st.set_page_config(page_title="Grimoire Wizard", page_icon="📚", layout="wide")
st.title("Grimoire Wizard")
st.caption("Ask questions about documents attached to your conversation.")

with st.sidebar:
    st.header("Backend")
    api_url = st.text_input(
        "API URL",
        value=os.getenv("GRIMOIRE_API_URL", "http://127.0.0.1:8000"),
        help="The backend base URL; do not include /docs or an endpoint path.",
    ).strip()

if not api_url:
    st.error("Enter a backend API URL in the sidebar.")
    st.stop()

client = BackendClient(api_url)

with st.sidebar:
    try:
        health = client.health()
        if health.get("status") == "ok":
            st.success("Backend connected")
        else:
            st.warning(f"Unexpected health response: {health}")
    except BackendError as error:
        st.error(str(error))

    st.divider()
    st.subheader("Start from a PDF")
    uploaded_pdf = st.file_uploader("Choose a PDF", type=["pdf"])
    pdf_title = st.text_input(
        "Conversation title (optional)", max_chars=200, key="pdf_title"
    )
    if st.button("Upload PDF and start conversation", disabled=uploaded_pdf is None):
        if uploaded_pdf is None:
            st.error("Choose a PDF to upload.")
        else:
            document = None
            conversation = None
            try:
                with st.spinner(
                    "Uploading and indexing the PDF. The first run may take longer "
                    "while the embedding model downloads..."
                ):
                    document = client.upload_pdf(
                        uploaded_pdf.name, uploaded_pdf.getvalue()
                    )
                    conversation = client.create_conversation(pdf_title.strip() or None)
                    client.attach_document(
                        conversation["id"], document["document_id"]
                    )
                st.session_state["active_conversation_id"] = conversation["id"]
                st.session_state["new_conversation_notice"] = (
                    f"Conversation started with {document['filename']} "
                    f"({document['chunks']} indexed chunks)."
                )
                st.rerun()
            except (BackendError, KeyError) as error:
                if document is None:
                    st.error(f"Could not upload and index the PDF: {error}")
                elif conversation is not None:
                    st.error(
                        f"PDF indexed as {document.get('document_id')}. "
                        f"Conversation {conversation.get('id')} was created, but "
                        f"the document could not be attached: {error}"
                    )
                else:
                    st.error(
                        f"PDF indexed as {document.get('document_id')}, but the "
                        f"conversation could not be created: {error}"
                    )

    st.divider()
    st.subheader("New conversation")
    with st.form("new_conversation", clear_on_submit=True):
        title = st.text_input("Title (optional)", max_chars=200)
        create_clicked = st.form_submit_button("Create")
    if create_clicked:
        try:
            conversation = client.create_conversation(title.strip() or None)
            st.session_state["active_conversation_id"] = conversation["id"]
            st.rerun()
        except (BackendError, KeyError) as error:
            st.error(f"Could not create conversation: {error}")

    st.divider()
    st.subheader("Conversations")
    try:
        conversations = client.list_conversations()
    except (BackendError, KeyError, TypeError) as error:
        conversations = []
        st.error(f"Could not load conversations: {error}")

    conversation_labels = {
        f"{item.get('title') or 'Untitled'} · {item['id'][:8]}": item["id"]
        for item in conversations
    }
    active_id = st.session_state.get("active_conversation_id")
    selected_label = next(
        (
            label
            for label, conversation_id in conversation_labels.items()
            if conversation_id == active_id
        ),
        next(iter(conversation_labels), None),
    )
    if conversation_labels:
        selected_label = st.selectbox(
            "Open conversation",
            options=list(conversation_labels),
            index=list(conversation_labels).index(selected_label),
            label_visibility="collapsed",
        )
        st.session_state["active_conversation_id"] = conversation_labels[selected_label]
    else:
        st.caption("No conversations yet. Create one to get started.")

conversation_id = st.session_state.get("active_conversation_id")
notice = st.session_state.pop("new_conversation_notice", None)
if notice:
    st.success(notice)
if not conversation_id or not conversations:
    st.info("Create a conversation, then attach an indexed document to begin.")
    st.stop()

try:
    conversation = client.get_conversation(conversation_id)
    messages = client.get_messages(conversation_id)
except BackendError as error:
    st.error(f"Could not load this conversation: {error}")
    st.stop()

documents = conversation.get("documents") or []
document_names = {
    item.get("id"): item.get("filename") or item.get("id") for item in documents
}

with st.sidebar:
    st.divider()
    st.subheader("Attached documents")
    if documents:
        for document in documents:
            st.caption(
                f"{document.get('filename') or 'Unnamed document'} "
                f"({document.get('status', 'unknown')})"
            )
    else:
        st.caption("No documents attached.")

    with st.form("attach_document", clear_on_submit=True):
        document_id = st.text_input(
            "Indexed document UUID",
            help="Paste the UUID returned by your document-ingestion workflow.",
        ).strip()
        attach_clicked = st.form_submit_button("Attach document")
    if attach_clicked:
        if not document_id:
            st.error("Enter a document UUID.")
        else:
            try:
                attached = client.attach_document(conversation_id, document_id)
                st.success(
                    f"Attached {attached.get('filename') or attached.get('id')}."
                )
                st.rerun()
            except BackendError as error:
                st.error(f"Could not attach document: {error}")

    st.caption("Upload and index a PDF above to start a new conversation.")

for message in messages:
    role = message.get("role", "assistant")
    if role not in {"user", "assistant"}:
        continue
    with st.chat_message(role):
        st.markdown(message.get("content", ""))
        if role == "assistant":
            _render_citations(message.get("citations") or [], document_names)

prompt = st.chat_input("Ask a question about the attached documents", disabled=not documents)
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        status_line = st.empty()
        answer_display = st.empty()
        answer_parts: list[str] = []
        citations: list[dict[str, Any]] = []
        completed = False
        failed = False
        try:
            for event_name, payload in client.stream_message(conversation_id, prompt):
                if event_name == "status":
                    status_line.caption(
                        f"Working: {payload.get('status', 'processing')}..."
                    )
                elif event_name == "token":
                    text = payload.get("text", "")
                    if isinstance(text, str):
                        answer_parts.append(text)
                        answer_display.markdown("".join(answer_parts) + "▌")
                elif event_name == "citations":
                    citations = payload.get("citations") or []
                elif event_name == "error":
                    failed = True
                    status_line.error(
                        f"{payload.get('message', 'The backend could not answer.')} "
                        f"({payload.get('code', 'error')})"
                    )
                    break
                elif event_name == "done":
                    completed = True
                    status_line.empty()
                    answer_display.markdown("".join(answer_parts))
                    _render_citations(citations, document_names)
            if not completed and not failed:
                status_line.error("The answer stream ended before completion.")
        except BackendError as error:
            status_line.error(str(error))
