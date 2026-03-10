"""
Property-Specific PDF Processor
Processes PDFs from propertyDocuments JSON and adds to property_embeddings table
"""
import logging
from typing import List, Dict, Any
from app.helpers.ingestion_pipeline.shared import PDFProcessor, Chunk

logger = logging.getLogger(__name__)


class PropertyPDFProcessor:
    """
    Processes property-specific PDFs (floor plans, contracts, disclosures)
    Integrates with existing property_embeddings table
    """
    
    def __init__(self, chunk_size: int = 500):
        """
        Initialize property PDF processor.
        
        Args:
            chunk_size: Maximum words per chunk
        """
        self.pdf_processor = PDFProcessor(chunk_size=chunk_size)
    
    def process_property_documents(
        self, 
        listing_id: str, 
        property_documents: List[Dict[str, Any]]
    ) -> List[Chunk]:
        """
        Process all propertyDocuments for a listing.
        
        Args:
            listing_id: Property listing ID
            property_documents: List of document objects from JSON
            
        Returns:
            List of Chunk objects ready for property_embeddings table
        """
        if not property_documents:
            logger.warning("⚠️  No property documents for listing %s", listing_id)
            return []
        
        all_chunks = []
        global_chunk_index = 0
        
        for doc in property_documents:
            try:
                chunks = self._process_single_document(listing_id, doc, global_chunk_index)
                all_chunks.extend(chunks)
                global_chunk_index += len(chunks)
            except Exception as e:
                logger.error("❌ Failed to process document %s: %s", doc.get('id'), e)
        
        logger.info("✓ Processed %d chunks from %d documents", len(all_chunks), len(property_documents))
        return all_chunks
    
    def _process_single_document(
        self, 
        listing_id: str, 
        doc: Dict[str, Any],
        global_chunk_index: int = 0
    ) -> List[Chunk]:
        """
        Process a single property document.
        
        Args:
            listing_id: Property listing ID
            doc: Document object from JSON
            
        Returns:
            List of Chunk objects
        """
        media_metadata = doc.get('mediaMetadata', {})
        file_url = media_metadata.get('fileUrl')
        file_type = media_metadata.get('fileType', '').lower()
        file_name = media_metadata.get('fileName', 'unknown')
        alt_text = media_metadata.get('altText', '')
        doc_id = doc.get('id')
        
        # Extract content based on file type
        content = None
        
        if file_type == 'pdf':
            logger.info("   📄 Extracting PDF: %s", file_name)
            content = self.pdf_processor.extract_from_url(file_url, file_name)
        
        elif file_type in ['jpeg', 'jpg', 'png', 'gif']:
            # For images, use alt text
            if alt_text:
                logger.info("   🖼️  Using alt text for image: %s", file_name)
                content = f"[Image: {file_name}] {alt_text}"
            else:
                logger.warning("   ⚠️  No alt text for image: %s, skipping", file_name)
                return []
        
        else:
            logger.warning("   ⚠️  Unsupported file type '%s' for: %s", file_type, file_name)
            return []
        
        if not content:
            logger.warning(f"   ⚠️  No content extracted from {file_name} - may be scanned/empty PDF")
            return []
        
        # Clean content
        content = self.pdf_processor.clean_text(content)
        logger.info(f"   ✓ Cleaned content: {len(content)} chars")
        
        # Chunk content
        text_chunks = self.pdf_processor.chunk_text(content, overlap=50)
        
        if not text_chunks:
            logger.warning(f"   ⚠️  No chunks generated from {file_name}")
        
        # Create Chunk objects for property_embeddings table
        chunks = []
        for idx, chunk_text in enumerate(text_chunks):
            # Convert UUIDs to strings for JSON serialization
            listing_id_str = str(listing_id) if listing_id else None
            doc_id_str = str(doc_id) if doc_id else None
            
            chunk_metadata = {
                "listing_id": listing_id_str,
                "doc_id": doc_id_str,
                "file_name": file_name,
                "file_type": file_type,
                "file_url": file_url,
                "chunk_index": global_chunk_index + idx,
                "total_chunks": len(text_chunks),
                "source": "property_document"
            }
            
            chunks.append(Chunk(
                content=chunk_text,
                chunk_type="property_document",  # New chunk type
                chunk_index=global_chunk_index + idx,
                listing_id=listing_id_str,  # Use string version
                metadata=chunk_metadata
            ))
        
        return chunks
    
    def get_document_summary(self, property_documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get summary of property documents.
        
        Args:
            property_documents: List of document objects
            
        Returns:
            Summary dict
        """
        if not property_documents:
            return {"total": 0, "by_type": {}}
        
        by_type = {}
        for doc in property_documents:
            file_type = doc.get('mediaMetadata', {}).get('fileType', 'unknown')
            by_type[file_type] = by_type.get(file_type, 0) + 1
        
        return {
            "total": len(property_documents),
            "by_type": by_type
        }

