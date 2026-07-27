"""
loader.py
---------
Loads PDF documents from data/sample_reports/ folder.
Handles encrypted/password-protected PDFs gracefully by skipping them.
"""

import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.utils.config import CHUNK_SIZE, CHUNK_OVERLAP


def load_documents(data_path: str = "./data/sample_reports") -> list:
    if not os.path.exists(data_path):
        print(f"Data folder not found: {data_path}")
        os.makedirs(data_path, exist_ok=True)
        return []

    pdf_files = [f for f in os.listdir(data_path) if f.endswith(".pdf")]

    if not pdf_files:
        print("No PDF files found in data/sample_reports/")
        return []

    print(f"Found {len(pdf_files)} PDF files")

    all_documents = []
    skipped = 0

    for pdf_file in pdf_files:
        pdf_path = os.path.join(data_path, pdf_file)
        try:
            loader = PyPDFLoader(pdf_path)
            docs = loader.load()
            all_documents.extend(docs)
            print(f"Loaded: {pdf_file} ({len(docs)} pages)")
        except Exception as e:
            print(f"Skipped: {pdf_file} — {str(e)[:50]}")
            skipped += 1

    print(f"\nTotal pages loaded: {len(all_documents)}")
    print(f"Files skipped (encrypted/corrupt): {skipped}")
    return all_documents


def split_documents(documents: list) -> list:
    if not documents:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", ",", " "],
        length_function=len
    )

    chunks = splitter.split_documents(documents)
    print(f"Split into {len(chunks)} chunks")
    return chunks


def load_and_split(data_path: str = "./data/sample_reports") -> list:
    documents = load_documents(data_path)
    if not documents:
        return []
    return split_documents(documents)