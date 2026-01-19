"""
Property-Specific PDF Processor
Processes PDFs from propertyDocuments JSON and adds to property_embeddings table
"""
from typing import List, Dict, Any
from app.helpers.ingestion_pipeline.shared import PDFProcessor, Chunk


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
            print(f"⚠️  No property documents for listing {listing_id}")
            return []
        
        all_chunks = []
        
        for doc in property_documents:
            try:
                chunks = self._process_single_document(listing_id, doc)
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"❌ Failed to process document {doc.get('id')}: {e}")
        
        print(f"✓ Processed {len(all_chunks)} chunks from {len(property_documents)} documents")
        return all_chunks
    
    def _process_single_document(
        self, 
        listing_id: str, 
        doc: Dict[str, Any]
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
            print(f"   📄 Extracting PDF: {file_name}")
            content = self.pdf_processor.extract_from_url(file_url, file_name)
        
        elif file_type in ['jpeg', 'jpg', 'png', 'gif']:
            # For images, use alt text
            if alt_text:
                print(f"   🖼️  Using alt text for image: {file_name}")
                content = f"[Image: {file_name}] {alt_text}"
            else:
                print(f"   ⚠️  No alt text for image: {file_name}, skipping")
                return []
        
        else:
            print(f"   ⚠️  Unsupported file type '{file_type}' for: {file_name}")
            return []
        
        if not content:
            return []
        
        # Clean content
        content = self.pdf_processor.clean_text(content)
        
        # Chunk content
        text_chunks = self.pdf_processor.chunk_text(content, overlap=50)
        
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
                "chunk_index": idx,
                "total_chunks": len(text_chunks),
                "source": "property_document"
            }
            
            chunks.append(Chunk(
                content=chunk_text,
                chunk_type="property_document",  # New chunk type
                chunk_index=idx,
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

