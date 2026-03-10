"""
PDF Processing Module - Shared by both property and generic pipelines
"""
import re
import requests
from typing import List, Dict, Optional
from io import BytesIO
from pathlib import Path
import PyPDF2
from dataclasses import dataclass

# Constants
DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 50
DEFAULT_REQUEST_TIMEOUT = 120  # seconds – large PDFs need more time to download
PAGE_SEPARATOR_FORMAT = "\n--- Page {page_num} ---\n"


@dataclass
class PDFDocument:
    """Represents a processed PDF document"""
    file_name: str
    content: str
    metadata: Dict
    source_type: str  # 'property' or 'generic'


class PDFProcessor:
    """
    Core PDF processing functionality.
    Handles text extraction, chunking, and metadata management.
    """
    
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE):
        """
        Initialize PDF processor.
        
        Args:
            chunk_size: Maximum words per chunk
        """
        self.chunk_size = chunk_size
    
    def extract_from_url(self, url: str, file_name: Optional[str] = None) -> Optional[str]:
        """
        Extract text from PDF URL.
        
        Args:
            url: PDF file URL
            file_name: Optional file name for logging
            
        Returns:
            Extracted text or None if failed
        """
        if not url or not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            print(f"⚠️  Invalid URL format: {url}")
            return None
        
        try:
            response = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            
            pdf_file = BytesIO(response.content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            return self._extract_text_from_reader(pdf_reader, file_name or url)
        
        except requests.exceptions.Timeout:
            print(f"⚠️  Timeout while fetching PDF from {file_name or url}")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"⚠️  HTTP error while fetching PDF {file_name or url}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Request error while fetching PDF {file_name or url}: {e}")
            return None
        except (AttributeError, PyPDF2.errors.PdfReadError) as e:
            print(f"⚠️  PDF read error for {file_name or url}: {e}")
            return None
        except Exception as e:
            print(f"⚠️  Failed to extract PDF {file_name or url}: {e}")
            return None
    
    def extract_from_file(self, file_path: str) -> Optional[str]:
        """
        Extract text from local PDF file.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Extracted text or None if failed
        """
        file_path_obj = Path(file_path)
        
        if not file_path_obj.exists():
            print(f"⚠️  File not found: {file_path}")
            return None
        
        if not file_path_obj.is_file():
            print(f"⚠️  Path is not a file: {file_path}")
            return None
        
        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                return self._extract_text_from_reader(pdf_reader, file_path)
        
        except PermissionError as e:
            print(f"⚠️  Permission denied reading file {file_path}: {e}")
            return None
        except (AttributeError, PyPDF2.errors.PdfReadError) as e:
            print(f"⚠️  PDF read error for {file_path}: {e}")
            return None
        except Exception as e:
            print(f"⚠️  Failed to extract PDF {file_path}: {e}")
            return None
    
    def chunk_text(self, text: str, overlap: int = DEFAULT_OVERLAP) -> List[str]:
        """
        Split text into chunks with word-based splitting.
        
        Args:
            text: Text to chunk
            overlap: Number of words to overlap between chunks (must be < chunk_size)
            
        Returns:
            List of text chunks
        """
        if not text or not isinstance(text, str):
            return []
        
        if overlap < 0 or overlap >= self.chunk_size:
            raise ValueError(f"Overlap ({overlap}) must be >= 0 and < chunk_size ({self.chunk_size})")
        
        words = text.split()
        if not words:
            return []
        
        chunks = []
        i = 0
        
        while i < len(words):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            chunks.append(chunk_text)
            i += self.chunk_size - overlap
        
        print(f"✓ Created {len(chunks)} chunks from {len(words)} words")
        return chunks
    
    def clean_text(self, text: str) -> str:
        """
        Clean extracted text (remove extra whitespace, NUL bytes, etc.)
        
        Args:
            text: Raw extracted text
            
        Returns:
            Cleaned text
        """
        if not text or not isinstance(text, str):
            return ""

        # Strip NUL bytes – PostgreSQL TEXT fields do not accept \x00
        text = text.replace('\x00', '')

        # Remove multiple newlines
        text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())
        
        # Remove multiple spaces
        text = re.sub(r' +', ' ', text)
        
        return text
    
    # ------------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------------
    def _extract_text_from_reader(
        self,
        pdf_reader: PyPDF2.PdfReader,
        source_name: str
    ) -> Optional[str]:
        """
        Extract text from a PyPDF2 PdfReader object.
        
        Args:
            pdf_reader: PyPDF2 PdfReader instance
            source_name: Name of source (for logging)
            
        Returns:
            Extracted text or None if failed
        """
        try:
            text = ""
            total_pages = len(pdf_reader.pages)
            
            for page_num, page in enumerate(pdf_reader.pages, start=1):
                page_text = page.extract_text() or ""
                page_text = page_text.replace('\x00', '')
                
                if page_text.strip():
                    text += PAGE_SEPARATOR_FORMAT.format(page_num=page_num) + page_text
            
            if not text.strip():
                print(f"⚠️  No text extracted from {source_name}")
                return None
            
            cleaned = self.clean_text(text)
            print(f"✓ Extracted {len(cleaned)} characters from {source_name} ({total_pages} pages)")
            return cleaned
        
        except (AttributeError, PyPDF2.errors.PdfReadError) as e:
            print(f"⚠️  PDF read error for {source_name}: {e}")
            return None

