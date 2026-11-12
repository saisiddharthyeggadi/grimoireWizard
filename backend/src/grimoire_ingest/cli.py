from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import create_client

from .pipeline import ingest_pdf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse an English PDF, semantically chunk it, and upload embeddings to Supabase."
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF file to ingest")
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.45,
        help="Split adjacent paragraphs below this cosine similarity (default: 0.45)",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=300,
        help="Maximum words per chunk (default: 300)",
    )
    parser.add_argument(
        "--overlap-words",
        type=int,
        default=0,
        help="Words repeated from the previous chunk, included in --max-words (default: 0)",
    )
    args = parser.parse_args()

    if not args.pdf.is_file():
        parser.error(f"PDF file does not exist: {args.pdf}")
    if args.pdf.suffix.lower() != ".pdf":
        parser.error(f"Expected a .pdf file: {args.pdf}")
    if not -1.0 <= args.similarity_threshold <= 1.0:
        parser.error("--similarity-threshold must be between -1 and 1")
    if args.max_words < 1:
        parser.error("--max-words must be at least 1")
    if not 0 <= args.overlap_words < args.max_words:
        parser.error("--overlap-words must be between 0 and max-words - 1")

    load_dotenv()
    supabase_url = os.environ.get("SUPABASE_URL")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        parser.error(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment or .env file."
        )
    if service_role_key.startswith("sb_publishable_"):
        parser.error(
            "SUPABASE_SERVICE_ROLE_KEY contains a publishable key. Replace it with "
            "the server-side secret key or legacy service_role key from this "
            "Supabase project. Do not use a publishable/anon key for ingestion."
        )

    client = create_client(supabase_url, service_role_key)
    try:
        result = ingest_pdf(
            args.pdf,
            client,
            similarity_threshold=args.similarity_threshold,
            max_words=args.max_words,
            overlap_words=args.overlap_words,
        )
    except APIError as error:
        if error.code == "42501":
            parser.error(
                "Supabase denied the write because of row-level security. "
                "Check that SUPABASE_SERVICE_ROLE_KEY is the server-side secret "
                "or legacy service_role key for the project in SUPABASE_URL. "
                "Do not fix this by adding a public write policy."
            )
        raise
    print(
        "Ingestion complete: "
        f"{result['chunks']} chunks from {result['pages']} pages "
        f"({result['paragraphs']} paragraphs). Document ID: {result['document_id']}"
    )


if __name__ == "__main__":
    main()
