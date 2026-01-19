"""
Sync Generic PDFs to generic_knowledge vector store.

Auto-discovers PDFs from app/knowledge_base/**/*.pdf and infers metadata from folder structure.

Usage:
    python app/helpers/ingestion_pipeline/generic/sync_generic_pdfs.py
    python app/helpers/ingestion_pipeline/generic/sync_generic_pdfs.py --re-index  # Clear and re-index all
    python app/helpers/ingestion_pipeline/generic/sync_generic_pdfs.py --append     # Only add new/updated documents

Requirements:
    - DATABASE_URL set in .env
    - OPENAI_API_KEY set in .env
"""
import sys
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add project root to path before any app imports
# File location: app/helpers/ingestion_pipeline/generic/sync_generic_pdfs.py
# Project root is 5 levels up (generic -> ingestion_pipeline -> helpers -> app -> project_root)
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root.resolve()))

import app.config  # noqa: F401

from app.helpers.ingestion_pipeline.shared.pdf_processor import PDFProcessor
from app.helpers.ingestion_pipeline.generic.generic_knowledge_store import GenericKnowledgeStore, GenericChunk

# Constants
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
# knowledge_base is at app/knowledge_base/ (under the app directory)
KNOWLEDGE_BASE_DIR = project_root / "app" / "knowledge_base"


def discover_pdfs(base_dir: Path = KNOWLEDGE_BASE_DIR) -> List[Path]:
    """
    Auto-discover all PDF files in the knowledge base directory.
    
    Args:
        base_dir: Base directory to search (default: app/knowledge_base)
        
    Returns:
        List of PDF file paths
    """
    if not base_dir.exists():
        print(f"⚠️  Knowledge base directory not found: {base_dir}")
        return []
    
    pdf_files = list(base_dir.rglob("*.pdf"))
    print(f"📁 Discovered {len(pdf_files)} PDF file(s) in {base_dir}")
    return pdf_files


def infer_metadata_from_path(pdf_path: Path, base_dir: Path = KNOWLEDGE_BASE_DIR) -> Dict[str, Any]:
    """
    Infer metadata from file path and folder structure.
    
    Folder structure examples:
    - app/knowledge_base/legislation/file.pdf → category="legislation"
    - app/knowledge_base/guides/buyer/file.pdf → category="guides", subcategory="buyer"
    - app/knowledge_base/file.pdf → category="general"
    
    Args:
        pdf_path: Path to PDF file
        base_dir: Base knowledge base directory
        
    Returns:
        Dictionary with inferred metadata
    """
    
    try:
        relative_path = pdf_path.relative_to(base_dir)
    except ValueError:
        relative_path = pdf_path
    
    # Extract folder structure
    parts = relative_path.parts[:-1]  # Exclude filename
    filename = pdf_path.stem  # Without .pdf extension
    
    # Infer category from first folder (if exists)
    if parts:
        category = parts[0].lower()
        # Clean category name (remove special chars, normalize)
        category = category.replace("_", " ").replace("-", " ").strip()
    else:
        category = "general"
    
    # Infer subcategory from second folder (if exists)
    subcategory = parts[1].lower() if len(parts) > 1 else None
    
    # Extract title from filename
    title = filename.replace("_", " ").replace("-", " ").strip()
    
    # Get file modification time as version indicator
    try:
        mtime = pdf_path.stat().st_mtime
        file_version = datetime.fromtimestamp(mtime).isoformat()
    except OSError:
        file_version = None
    
    metadata = {
        "title": title,
        "file_name": pdf_path.name,
        "file_path": str(relative_path),
        "category": category,
        "type": "generic_knowledge",
        "version": file_version,
            "discovered_at": datetime.now(timezone.utc).isoformat()
    }
    
    if subcategory:
        metadata["subcategory"] = subcategory
    
    return metadata


def compute_content_hash(content: str) -> str:
    """
    Compute SHA256 hash of content for duplicate detection.
    
    Args:
        content: Text content to hash
        
    Returns:
        Hexadecimal hash string
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()




def sync_generic_pdfs(re_index: bool = False, append: bool = True):
    """
    Sync all generic PDFs to generic_knowledge vector store.
    Auto-discovers PDFs and infers metadata from folder structure.
    
    Args:
        re_index: If True, clear existing chunks for documents before re-indexing
        append: If True, only add new/updated documents (default: True)
    """
    print("=" * 70)
    print("Generic PDF Sync to generic_knowledge Vector Store")
    print("=" * 70)
    
    if re_index:
        print("🔄 Mode: RE-INDEX (will update existing documents)")
    elif append:
        print("➕ Mode: APPEND (will only add new/updated documents)")
    
    knowledge_store = None
    try:
        pdf_processor = PDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)
        knowledge_store = GenericKnowledgeStore()
        
        print("\n📊 Initializing generic_knowledge table...")
        knowledge_store.initialize_table()
        
        # Auto-discover PDFs
        pdf_files = discover_pdfs()
        
        if not pdf_files:
            print("⚠️  No PDF files found in knowledge base directory")
            return
        
        total_chunks = 0
        processed_docs = 0
        skipped_docs = 0
        
        for pdf_path in pdf_files:
            try:
                # Infer metadata from path
                metadata = infer_metadata_from_path(pdf_path)
                category = metadata["category"]
                file_path = metadata["file_path"]
                
                print(f"\n📄 Processing: {pdf_path.name}")
                print(f"   Path: {file_path}")
                print(f"   Category: {category}")
                
                # Extract text
                print(f"   🔍 Extracting text...")
                text = pdf_processor.extract_from_file(str(pdf_path))
                
                if not text:
                    print(f"   ⚠️  No text extracted, skipping")
                    skipped_docs += 1
                    continue
                
                # Compute content hash for duplicate detection
                content_hash = compute_content_hash(text)
                metadata["content_hash"] = content_hash
                
                # Check if document already exists and hasn't changed (append mode)
                if append and not re_index:
                    from sqlalchemy import text as sql_text
                    # Check if chunks exist for this file_path with matching hash
                    check_query = sql_text("""
                        SELECT COUNT(*) FROM generic_knowledge
                        WHERE metadata->>'file_path' = :file_path
                        AND metadata->>'content_hash' = :content_hash
                    """)
                    result = knowledge_store.db_session.execute(
                        check_query,
                        {"file_path": file_path, "content_hash": content_hash}
                    )
                    existing_count = result.scalar() or 0
                    
                    if existing_count > 0:
                        print(f"   ✓ Document unchanged (hash matches), skipping")
                        skipped_docs += 1
                        continue
                    else:
                        # Document changed or new - remove old chunks if they exist
                        delete_query = sql_text("""
                            DELETE FROM generic_knowledge
                            WHERE metadata->>'file_path' = :file_path
                        """)
                        result = knowledge_store.db_session.execute(delete_query, {"file_path": file_path})
                        deleted_count = result.rowcount if hasattr(result, 'rowcount') else 0
                        knowledge_store.db_session.commit()
                        if deleted_count > 0:
                            print(f"   🔄 Document changed (removed {deleted_count} old chunks)")
                        else:
                            print(f"   ➕ New document detected")
                
                # Clean and chunk text
                text = pdf_processor.clean_text(text)
                
                print(f"   ✂️  Chunking text...")
                text_chunks = pdf_processor.chunk_text(text, overlap=DEFAULT_CHUNK_OVERLAP)
                
                # Create chunks
                chunks = []
                for idx, chunk_text in enumerate(text_chunks):
                    chunk_metadata = {
                        **metadata,
                        "chunk_index": idx,
                        "total_chunks": len(text_chunks)
                    }
                    
                    chunks.append(GenericChunk(
                        content=chunk_text,
                        doc_category=category,
                        chunk_index=idx,
                        metadata=chunk_metadata
                    ))
                
                # Add chunks to store
                print(f"   💾 Adding {len(chunks)} chunks to vector store...")
                added_count = knowledge_store.add_chunks(chunks)
                total_chunks += added_count
                processed_docs += 1
                
                print(f"   ✓ Successfully added {added_count} chunks")
                
            except Exception as e:
                print(f"   ❌ Error processing document: {e}")
                skipped_docs += 1
                continue
        
        print("\n" + "=" * 70)
        print("📊 Sync Statistics")
        print("=" * 70)
        
        stats = knowledge_store.get_stats()
        print(f"\n Total chunks in store: {stats['total_chunks']}")
        print(f" Documents processed: {processed_docs}")
        print(f" Documents skipped: {skipped_docs}")
        print(f" Chunks added this run: {total_chunks}")
        print(f"\n Categories:")
        for cat, count in stats['categories'].items():
            print(f"   - {cat}: {count} chunks")
        
        print("\n✓ Generic PDF sync complete!")
        
    except Exception as e:
        print(f"\n❌ Error during sync: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if knowledge_store:
            knowledge_store.close()


def test_search():
    """
    Test search functionality on generic knowledge.
    """
    print("\n" + "=" * 70)
    print("Testing Generic Knowledge Search")
    print("=" * 70)
    
    knowledge_store = GenericKnowledgeStore()
    
    try:
        test_queries = [
            "What are the legal requirements for property sales?",
            "Tell me about cooling off period",
            "What disclosures are required?"
        ]
        
        for query in test_queries:
            print(f"\n🔍 Query: {query}")
            results = knowledge_store.search(query, n_results=3)
            
            if results:
                print(f"   Found {len(results)} results:")
                for i, result in enumerate(results, 1):
                    print(f"\n   {i}. Category: {result['doc_category']}")
                    print(f"      Similarity: {result['similarity']:.4f}")
                    print(f"      Content preview: {result['content'][:150]}...")
            else:
                print("   No results found")
    except Exception as e:
        print(f"\n❌ Error during search test: {e}")
        raise
    finally:
        knowledge_store.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync generic PDFs to vector store")
    parser.add_argument(
        '--re-index',
        action='store_true',
        help="Re-index all documents (clear and re-add, even if unchanged)"
    )
    parser.add_argument(
        '--append',
        action='store_true',
        default=True,
        help="Only add new/updated documents (default: True, ignored if --re-index is set)"
    )
    parser.add_argument('--test', action='store_true', help="Run search tests after sync")
    args = parser.parse_args()
    
    # If re-index is set, ignore append mode
    append_mode = not args.re_index and args.append
    
    sync_generic_pdfs(re_index=args.re_index, append=append_mode)
    
    if args.test:
        test_search()

