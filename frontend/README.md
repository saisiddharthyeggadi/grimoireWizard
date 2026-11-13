# Grimoire Wizard frontend

A lightweight Streamlit chat client for the backend. It supports uploading and
indexing a PDF to start a conversation, reopening conversations, attaching
previously indexed documents by ID, streaming answers, and viewing citations.

## Run locally

Start the backend in one terminal by following the setup instructions in
[`../backend/README.md`](../backend/README.md). In a second PowerShell terminal:

```powershell
cd frontend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:GRIMOIRE_API_URL = "http://127.0.0.1:8000"
streamlit run app.py
```

The app opens in your browser. The API URL defaults to
`http://127.0.0.1:8000` and can be changed with `GRIMOIRE_API_URL`.

## Upload a PDF

Use **Start from a PDF** in the sidebar. The backend processes the PDF with
the existing ingestion pipeline, then creates a conversation and attaches the
indexed document. Uploads are limited to 50 MB. Processing is synchronous, so
large PDFs and the first run (which may download the embedding model) can take
several minutes. The backend must have its Supabase credentials configured.
Never put Supabase or LLM credentials in the frontend.
