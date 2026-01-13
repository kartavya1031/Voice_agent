"""
Vector Store Service using ChromaDB for RAG (Retrieval Augmented Generation)
Stores and retrieves knowledge base content for the AI voice agent
Supports multiple dynamic knowledge bases
"""

import chromadb
from chromadb.utils import embedding_functions
import os
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import (
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_EMBEDDING_DEPLOYMENT_NAME
)

# Persist directory for ChromaDB
PERSIST_DIR = Path(__file__).parent.parent / "data" / "chroma_db"

# Knowledge base files directory
KB_FILES_DIR = Path(__file__).parent.parent / "data" / "knowledge_bases"
KB_FILES_DIR.mkdir(parents=True, exist_ok=True)

# Initialize ChromaDB client
client = chromadb.PersistentClient(path=str(PERSIST_DIR))

# Extract base endpoint (remove the /deployments/... part if present)
base_endpoint = AZURE_OPENAI_ENDPOINT
if "/openai/deployments/" in base_endpoint:
    base_endpoint = base_endpoint.split("/openai/deployments/")[0]

# Use Azure OpenAI embedding function (much faster than local model)
embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
    api_key=AZURE_OPENAI_KEY,
    api_base=base_endpoint,
    api_type="azure",
    api_version="2023-05-15",
    deployment_id=AZURE_EMBEDDING_DEPLOYMENT_NAME  # Use deployment_id for Azure
)

# Default collection for backward compatibility
DEFAULT_COLLECTION_NAME = "anvenssa_knowledge"

# Get or create default collection
collection = client.get_or_create_collection(
    name=DEFAULT_COLLECTION_NAME,
    embedding_function=embedding_fn,
    metadata={"description": "Anvenssa.AI knowledge base for voice agent"}
)

# Current active collection (can be switched)
active_collection = collection
active_kb_id: Optional[str] = None


def get_collection_for_kb(kb_id: str):
    """Get or create a collection for a specific knowledge base"""
    collection_name = f"kb_{kb_id}"
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"kb_id": kb_id}
    )


def set_active_knowledge_base(kb_id: Optional[str]):
    """Set the active knowledge base to use for queries"""
    global active_collection, active_kb_id
    
    if kb_id is None:
        # Use default collection
        active_collection = collection
        active_kb_id = None
        print("📚 Using default knowledge base")
    else:
        active_collection = get_collection_for_kb(kb_id)
        active_kb_id = kb_id
        print(f"📚 Switched to knowledge base: {kb_id}")


def create_knowledge_base_from_text(kb_id: str, name: str, content: str) -> int:
    """Create a new knowledge base from text content"""
    kb_collection = get_collection_for_kb(kb_id)
    
    # Clear existing if any
    try:
        existing = kb_collection.get()
        if existing['ids']:
            kb_collection.delete(ids=existing['ids'])
    except:
        pass
    
    # Chunk and add content
    chunks = chunk_text(content)
    
    if not chunks:
        return 0
    
    ids = [f"{kb_id}_chunk_{i}" for i in range(len(chunks))]
    
    kb_collection.add(
        documents=chunks,
        ids=ids,
        metadatas=[{"kb_id": kb_id, "name": name, "chunk_index": i} for i in range(len(chunks))]
    )
    
    print(f"✅ Created knowledge base '{name}' with {len(chunks)} chunks")
    return len(chunks)


def delete_knowledge_base(kb_id: str) -> bool:
    """Delete a knowledge base collection"""
    global active_collection, active_kb_id
    
    try:
        collection_name = f"kb_{kb_id}"
        client.delete_collection(name=collection_name)
        
        # If this was active, switch to default
        if active_kb_id == kb_id:
            active_collection = collection
            active_kb_id = None
        
        print(f"🗑️ Deleted knowledge base: {kb_id}")
        return True
    except Exception as e:
        print(f"⚠️ Error deleting knowledge base: {e}")
        return False


def get_kb_file_path(kb_id: str, filename: str) -> Path:
    """Get the file path for a knowledge base file"""
    return KB_FILES_DIR / f"{kb_id}_{filename}"


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for better retrieval"""
    chunks = []
    
    # Split by sections (## headers)
    sections = text.split("\n## ")
    
    for i, section in enumerate(sections):
        if i > 0:
            section = "## " + section
        
        # If section is small enough, keep as is
        if len(section) <= chunk_size:
            chunks.append(section.strip())
        else:
            # Split into smaller chunks with overlap
            words = section.split()
            current_chunk = []
            current_len = 0
            
            for word in words:
                current_chunk.append(word)
                current_len += len(word) + 1
                
                if current_len >= chunk_size:
                    chunks.append(" ".join(current_chunk))
                    # Keep last few words for overlap
                    overlap_words = current_chunk[-overlap//10:] if overlap > 0 else []
                    current_chunk = overlap_words
                    current_len = sum(len(w) + 1 for w in current_chunk)
            
            if current_chunk:
                chunks.append(" ".join(current_chunk))
    
    return [c for c in chunks if c.strip()]


def load_knowledge_base():
    """Load knowledge base from markdown file and index into ChromaDB"""
    kb_path = Path(__file__).parent.parent / "data" / "knowledge_base.md"
    
    if not kb_path.exists():
        print(f"⚠️ Knowledge base not found at {kb_path}")
        return False
    
    # Check if already loaded
    if collection.count() > 0:
        print(f"✅ Knowledge base already loaded ({collection.count()} chunks)")
        return True
    
    print("📚 Loading knowledge base into vector store...")
    
    with open(kb_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Chunk the content
    chunks = chunk_text(content)
    
    # Add to ChromaDB
    ids = [f"chunk_{i}" for i in range(len(chunks))]
    
    collection.add(
        documents=chunks,
        ids=ids,
        metadatas=[{"source": "knowledge_base.md", "chunk_index": i} for i in range(len(chunks))]
    )
    
    print(f"✅ Loaded {len(chunks)} chunks into vector store")
    return True


# LRU Cache for search results (avoids repeated embedding+search for same query)
from functools import lru_cache
import hashlib

# Cache key generator (includes active KB ID for proper cache isolation)
def _get_cache_key(query: str) -> str:
    """Generate cache key including active KB"""
    key = f"{active_kb_id or 'default'}:{query.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()

# Cache for recent queries (50 entries)
_search_cache = {}
_cache_max_size = 50


def search_knowledge(query: str, n_results: int = 2) -> list[str]:
    """Search active knowledge base for relevant context (with caching)"""
    global active_collection, _search_cache
    
    # Check cache first
    cache_key = _get_cache_key(query)
    if cache_key in _search_cache:
        print(f"   💨 RAG cache hit!")
        return _search_cache[cache_key]
    
    # Use active collection (could be default or custom KB)
    target_collection = active_collection
    
    if target_collection.count() == 0:
        # Try loading default if using default collection
        if active_kb_id is None:
            load_knowledge_base()
    
    if target_collection.count() == 0:
        return []
    
    # Reduced n_results from 3 to 2 for speed
    results = target_collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    result_docs = []
    if results and results['documents']:
        result_docs = results['documents'][0]
    
    # Cache the result
    if len(_search_cache) >= _cache_max_size:
        # Remove oldest entry (simple FIFO)
        oldest_key = next(iter(_search_cache))
        del _search_cache[oldest_key]
    _search_cache[cache_key] = result_docs
    
    return result_docs


def get_context_for_query(query: str) -> str:
    """Get formatted context string for LLM prompt"""
    relevant_chunks = search_knowledge(query, n_results=2)
    
    if not relevant_chunks:
        return ""
    
    # Limit context size for speed (max 600 chars total)
    context = "\n---\n".join(relevant_chunks)
    if len(context) > 600:
        context = context[:600] + "..."
    return context


def get_active_kb_info() -> dict:
    """Get info about the currently active knowledge base"""
    global active_collection, active_kb_id
    return {
        "kb_id": active_kb_id,
        "collection_name": active_collection.name if active_collection else None,
        "chunk_count": active_collection.count() if active_collection else 0
    }


# Load knowledge base on module import
load_knowledge_base()
