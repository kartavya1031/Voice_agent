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

# Use sentence-transformers for embeddings (runs locally, fast)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Persist directory for ChromaDB
PERSIST_DIR = Path(__file__).parent.parent / "data" / "chroma_db"

# Knowledge base files directory
KB_FILES_DIR = Path(__file__).parent.parent / "data" / "knowledge_bases"
KB_FILES_DIR.mkdir(parents=True, exist_ok=True)

# Initialize ChromaDB client
client = chromadb.PersistentClient(path=str(PERSIST_DIR))

# Use sentence-transformers embedding function
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL
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


def search_knowledge(query: str, n_results: int = 3) -> list[str]:
    """Search active knowledge base for relevant context"""
    global active_collection
    
    # Use active collection (could be default or custom KB)
    target_collection = active_collection
    
    if target_collection.count() == 0:
        # Try loading default if using default collection
        if active_kb_id is None:
            load_knowledge_base()
    
    if target_collection.count() == 0:
        return []
    
    results = target_collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    if results and results['documents']:
        return results['documents'][0]
    
    return []


def get_context_for_query(query: str) -> str:
    """Get formatted context string for LLM prompt"""
    relevant_chunks = search_knowledge(query, n_results=3)
    
    if not relevant_chunks:
        return ""
    
    context = "\n\n---\n\n".join(relevant_chunks)
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
