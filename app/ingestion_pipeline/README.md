# Property Listing Ingestion Pipeline

This pipeline processes property listing JSON data into vector embeddings for RAG (Retrieval-Augmented Generation).

## Components

### 1. Loader (`loader.py`)
- Loads property listings from JSON files
- Formats listings into structured dictionaries
- Extracts key information for chunking

### 2. Chunker (`chunker.py`)
- Splits property listings into semantic chunks
- Creates specialized chunks for:
  - **Overview**: Complete property summary
  - **Pricing**: Price, sale method, auction details
  - **Specifications**: Bedrooms, bathrooms, areas, features
  - **Location**: Address, inspections, agents
  - **Bidding**: Auction details, bid history

### 3. Vector Store (`vector_store.py`)
- Uses ChromaDB for persistent vector storage
- Uses Sentence Transformers for embeddings (default: `all-MiniLM-L6-v2`)
- Stores chunks with metadata for filtering

## Usage

### Initial Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Initialize the vector store:**
   ```bash
   python scripts/initialize_vector_store.py
   ```

   This will:
   - Load `app/knowledge_base/sample_data.json`
   - Chunk all property listings
   - Generate embeddings
   - Store in `./chroma_db/`

### Using the Vector Store

```python
from app.ingestion_pipeline.vector_store import PropertyVectorStore

# Initialize (will load existing if available)
vector_store = PropertyVectorStore(
    collection_name="property_listings",
    persist_directory="./chroma_db"
)

# Search for relevant chunks
results = vector_store.search(
    query="What is the price of 3 bedroom houses?",
    n_results=5
)

# Get all chunks for a specific listing
listing_chunks = vector_store.get_by_listing_id("listing-id-here")
```

### Using the Retriever

```python
from app.rag_pipeline.retrieval import PropertyRetriever

# Initialize retriever
retriever = PropertyRetriever()

# General retrieval
results = retriever.retrieve(
    query="Show me auction properties",
    n_results=5
)

# Retrieve pricing-specific info
pricing_info = retriever.retrieve_pricing_info(
    query="What is the asking price?",
    listing_id="optional-listing-id"
)

# Retrieve specifications
specs = retriever.retrieve_specifications(
    query="How many bedrooms?",
    n_results=3
)

# Format results for LLM
formatted = retriever.format_retrieval_results(results)
```

## Chunk Types

- **overview**: Complete property summary
- **pricing**: Price, sale method, auction details
- **specifications**: Property features and specs
- **location**: Address and inspection information
- **bidding**: Auction and bidding details

## Metadata Filtering

You can filter by metadata when searching:

```python
results = vector_store.search(
    query="property query",
    n_results=5,
    filter_metadata={
        'chunk_type': 'pricing',
        'listing_id': 'specific-listing-id'
    }
)
```

## Storage

- Vector embeddings are stored in `./chroma_db/` (configurable)
- The collection persists between sessions
- To rebuild from scratch, use `clear_existing=True` in `initialize_vector_store()`

## Example Workflow

1. Load listings from JSON
2. Format listings for chunking
3. Chunk listings into semantic pieces
4. Generate embeddings
5. Store in ChromaDB
6. Query using semantic search
7. Use retrieved chunks in RAG pipeline

