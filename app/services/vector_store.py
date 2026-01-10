"""
Vector Store Service using ChromaDB for RAG (Retrieval Augmented Generation)
Stores and retrieves knowledge base content for the AI voice agent
"""

import chromadb
from chromadb.utils import embedding_functions
import os
from pathlib import Path

# Use sentence-transformers for embeddings (runs locally, fast)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Persist directory for ChromaDB
PERSIST_DIR = Path(__file__).parent.parent / "data" / "chroma_db"

# Initialize ChromaDB client
client = chromadb.PersistentClient(path=str(PERSIST_DIR))

# Use sentence-transformers embedding function
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL
)

# Get or create collection
collection = client.get_or_create_collection(
    name="anvenssa_knowledge",
    embedding_function=embedding_fn,
    metadata={"description": "Anvenssa.AI knowledge base for voice agent"}
)


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
    """Search knowledge base for relevant context"""
    if collection.count() == 0:
        load_knowledge_base()
    
    results = collection.query(
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


# Load knowledge base on module import
load_knowledge_base()
