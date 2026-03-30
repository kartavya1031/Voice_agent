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
# Changed to v4 after multi-tenant refactoring to avoid sqlite schema conflicts
PERSIST_DIR = Path(__file__).parent.parent / "data" / "chroma_db_v4"

# Knowledge base files directory
KB_FILES_DIR = Path(__file__).parent.parent / "data" / "knowledge_bases"
KB_FILES_DIR.mkdir(parents=True, exist_ok=True)

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
DEFAULT_COLLECTION_NAME = "company_knowledge"


def _check_and_clean_chromadb():
    """Check ChromaDB schema compatibility and clean if needed BEFORE creating client
    
    NOTE: Checks database accessibility and schema compatibility.
    If the schema is incompatible (e.g., missing 'topic' column), clean the database.
    """
    import shutil
    import sqlite3
    
    db_path = PERSIST_DIR / "chroma.sqlite3"
    
    if not db_path.exists():
        # No existing database, nothing to check
        return
    
    try:
        # Directly connect to SQLite to verify database is accessible
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if collections table exists and has required columns
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='collections'")
            result = cursor.fetchone()
            if result is None:
                print(f"⚠️ ChromaDB database exists but has no collections table")
                print(f"🔄 Cleaning database for fresh start...")
                conn.close()
                if PERSIST_DIR.exists():
                    shutil.rmtree(PERSIST_DIR)
                print(f"✅ Old database cleaned. Fresh database will be created.")
                return
            
            # Check for 'topic' column which is required in newer chromadb versions
            cursor.execute("PRAGMA table_info(collections)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'topic' not in columns:
                print(f"⚠️ ChromaDB database schema mismatch (missing 'topic' column)")
                print(f"🔄 Cleaning database for fresh start...")
                conn.close()
                if PERSIST_DIR.exists():
                    shutil.rmtree(PERSIST_DIR)
                print(f"✅ Old database cleaned. Fresh database will be created.")
                return
                
        except sqlite3.OperationalError as e:
            print(f"⚠️ ChromaDB database check failed: {e}")
            conn.close()
            if PERSIST_DIR.exists():
                shutil.rmtree(PERSIST_DIR)
            print(f"✅ Database cleaned.")
            return
        
        conn.close()
    except sqlite3.OperationalError as e:
        # Database might be corrupt or have other issues
        print(f"⚠️ ChromaDB database check failed: {e}")
        print(f"🔄 Cleaning potentially corrupt database...")
        try:
            if PERSIST_DIR.exists():
                shutil.rmtree(PERSIST_DIR)
            print(f"✅ Database cleaned.")
        except Exception as cleanup_error:
            print(f"❌ Could not clean database: {cleanup_error}")
    except Exception as e:
        print(f"⚠️ Unexpected error checking ChromaDB: {e}")


def _init_chromadb_client():
    """Initialize ChromaDB client with automatic schema mismatch recovery"""
    # First, check and clean any incompatible database BEFORE creating client
    _check_and_clean_chromadb()
    
    persist_path = str(PERSIST_DIR)
    
    # Now safely create the client
    client = chromadb.PersistentClient(path=persist_path)
    return client


# Initialize ChromaDB client with automatic recovery
client = _init_chromadb_client()

# Get or create default collection
collection = client.get_or_create_collection(
    name=DEFAULT_COLLECTION_NAME,
    embedding_function=embedding_fn,
    metadata={"description": "Company voice agent knowledge base"}
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
    global active_collection, active_kb_id, _search_cache
    
    # Clear the search cache when switching knowledge bases
    _search_cache = {}
    
    if kb_id is None:
        # Use default collection
        active_collection = collection
        active_kb_id = None
        print("📚 Using default knowledge base")
    else:
        active_collection = get_collection_for_kb(kb_id)
        active_kb_id = kb_id
        print(f"📚 Switched to knowledge base: {kb_id}")
        print(f"   📊 Collection: {active_collection.name}, Chunks: {active_collection.count()}")
        
        # Check if collection is empty and reload from file if needed
        if active_collection.count() == 0:
            print(f"   ⚠️ Collection is empty, attempting to reload from file...")
            _reload_kb_from_file(kb_id)
            _reload_kb_from_file(kb_id)


def _reload_kb_from_file(kb_id: str):
    """Reload a knowledge base from saved PDF file if collection is empty"""
    global active_collection
    
    try:
        # Find the PDF file for this KB
        import fitz  # PyMuPDF
        from app.services.agent_config import agent_config_service
        
        # Get KB info from config
        kb_info = None
        for kb in agent_config_service.get_knowledge_bases():
            if kb.id == kb_id:
                kb_info = kb
                break
        
        if not kb_info:
            print(f"   ❌ KB {kb_id} not found in config")
            return
        
        # Find the file
        file_path = KB_FILES_DIR / f"{kb_id}_{kb_info.filename}"
        if not file_path.exists():
            print(f"   ❌ KB file not found: {file_path}")
            return
        
        print(f"   📄 Reloading from: {file_path}")
        
        # Extract text from PDF
        text_content = ""
        with open(file_path, 'rb') as f:
            content = f.read()
        
        if kb_info.filename.lower().endswith('.pdf'):
            pdf_doc = fitz.open(stream=content, filetype="pdf")
            for page in pdf_doc:
                text_content += page.get_text()
            pdf_doc.close()
        elif kb_info.filename.lower().endswith(('.txt', '.md')):
            text_content = content.decode('utf-8', errors='ignore')
        
        if not text_content.strip():
            print(f"   ❌ No text content extracted from file")
            return
        
        # Chunk and add to collection
        chunks = chunk_text(text_content)
        if not chunks:
            print(f"   ❌ No chunks generated from text")
            return
        
        ids = [f"{kb_id}_chunk_{i}" for i in range(len(chunks))]
        
        active_collection.add(
            documents=chunks,
            ids=ids,
            metadatas=[{"kb_id": kb_id, "name": kb_info.name, "chunk_index": i} for i in range(len(chunks))]
        )
        
        print(f"   ✅ Reloaded KB with {len(chunks)} chunks")
        
        # Update config with correct chunk count
        agent_config_service.update_knowledge_base_chunks(kb_id, len(chunks))
        
    except ImportError:
        print(f"   ❌ PyMuPDF not installed - cannot reload PDF")
    except Exception as e:
        print(f"   ❌ Error reloading KB: {e}")


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


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into chunks optimized for Q&A retrieval
    
    Strategy:
    1. First try to split by numbered questions (1., 2., etc.)
    2. Then by section headers (##)
    3. Finally by paragraph if chunks are too large
    """
    chunks = []
    
    # Try to split by numbered Q&A format first (common in knowledge bases)
    # Pattern: "1." or "1)" at start of line
    qa_pattern = re.compile(r'\n(?=\d+[\.\)]\s)')
    qa_sections = qa_pattern.split(text)
    
    if len(qa_sections) > 1:
        # Q&A format detected
        for i, section in enumerate(qa_sections):
            section = section.strip()
            if not section:
                continue
                
            # Add question number back if it was split
            if i > 0 and not re.match(r'^\d+[\.\)]', section):
                # Find what number this should be
                pass  # The split keeps content after the number
            
            if len(section) <= chunk_size:
                chunks.append(section)
            else:
                # Split large Q&A into smaller parts but keep Q with first part of A
                words = section.split()
                current_chunk = []
                current_len = 0
                
                for word in words:
                    current_chunk.append(word)
                    current_len += len(word) + 1
                    
                    if current_len >= chunk_size:
                        chunks.append(" ".join(current_chunk))
                        # Keep last few words for overlap
                        overlap_words = current_chunk[-(overlap//5):] if overlap > 0 else []
                        current_chunk = overlap_words
                        current_len = sum(len(w) + 1 for w in current_chunk)
                
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
    else:
        # Fallback: Split by sections (## headers)
        sections = text.split("\n## ")
        
        for i, section in enumerate(sections):
            if i > 0:
                section = "## " + section
            
            section = section.strip()
            if not section:
                continue
            
            # If section is small enough, keep as is
            if len(section) <= chunk_size:
                chunks.append(section)
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
                        overlap_words = current_chunk[-(overlap//5):] if overlap > 0 else []
                        current_chunk = overlap_words
                        current_len = sum(len(w) + 1 for w in current_chunk)
                
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
    
    # Final cleanup: remove empty chunks and deduplicate
    seen = set()
    unique_chunks = []
    for c in chunks:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            unique_chunks.append(c)
    
    return unique_chunks


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
import re

# Cache key generator (includes active KB ID for proper cache isolation)
def _get_cache_key(query: str) -> str:
    """Generate cache key including active KB"""
    key = f"{active_kb_id or 'default'}:{query.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()

# Cache for recent queries (50 entries)
_search_cache = {}
_cache_max_size = 50

# Hindi-English keyword mapping for better retrieval
KEYWORD_MAP = {
    # Interest rate related
    'ब्याज': ['byaj', 'interest', 'rate', 'dar'],
    'interest': ['byaj', 'interest', 'rate', 'dar'],
    'rate': ['byaj', 'interest', 'rate', 'dar'],
    'रेट': ['byaj', 'interest', 'rate', 'dar'],
    # Loan related
    'लोन': ['loan', 'top-up', 'refinance'],
    'loan': ['loan', 'top-up', 'refinance'],
    'टॉप अप': ['top-up', 'topup', 'top up'],
    'top up': ['top-up', 'topup', 'top up'],
    # Documents
    'डॉक्यूमेंट': ['document', 'documents', 'dastavez', 'papers'],
    'document': ['document', 'documents', 'dastavez', 'papers'],
    'कागज': ['document', 'documents', 'dastavez', 'papers'],
    # Bank related
    'बैंक': ['bank', 'banks', 'nbfc', 'hdfc', 'icici', 'axis'],
    'bank': ['bank', 'banks', 'nbfc', 'hdfc', 'icici', 'axis'],
    # Tenure/duration
    'साल': ['saal', 'year', 'tenure', 'duration', 'mahine'],
    'tenure': ['saal', 'year', 'tenure', 'duration', 'mahine'],
    'अवधि': ['saal', 'year', 'tenure', 'duration', 'mahine'],
    # CIBIL/Credit
    'सिबिल': ['cibil', 'credit', 'score', 'civil'],
    'cibil': ['cibil', 'credit', 'score', 'civil'],
    'क्रेडिट': ['cibil', 'credit', 'score'],
    # Foreclosure
    'फोरक्लोज़': ['foreclose', 'foreclosure', 'close', 'jaldi', 'band'],
    'क्लोज़': ['foreclose', 'foreclosure', 'close', 'jaldi', 'band'],
    'close': ['foreclose', 'foreclosure', 'close', 'jaldi', 'band'],
    # Flat/Reducing
    'फ्लैट': ['flat', 'reducing', 'byaj'],
    'flat': ['flat', 'reducing', 'byaj'],
    'रिड्यूसिंग': ['flat', 'reducing', 'byaj'],
}


def _extract_keywords(query: str) -> list[str]:
    """Extract and expand keywords from query"""
    query_lower = query.lower()
    keywords = set()
    
    # Check for known keywords and their mappings
    for key, expansions in KEYWORD_MAP.items():
        if key.lower() in query_lower:
            keywords.update(expansions)
    
    # Also add individual words from query
    words = re.findall(r'\w+', query_lower)
    keywords.update(words)
    
    return list(keywords)


def _calculate_keyword_score(doc: str, keywords: list[str]) -> float:
    """Calculate keyword match score for a document"""
    if not keywords:
        return 0.0
    
    doc_lower = doc.lower()
    matches = sum(1 for kw in keywords if kw in doc_lower)
    return matches / len(keywords)


def _rerank_results(query: str, documents: list[str], distances: list[float]) -> list[tuple[str, float]]:
    """Rerank results using hybrid scoring (semantic + keyword)"""
    if not documents:
        return []
    
    keywords = _extract_keywords(query)
    results = []
    
    for doc, distance in zip(documents, distances):
        # Semantic score (convert distance to similarity, lower distance = higher similarity)
        # ChromaDB returns L2 distance, so we invert it
        semantic_score = 1.0 / (1.0 + distance)
        
        # Keyword score
        keyword_score = _calculate_keyword_score(doc, keywords)
        
        # Combined score: 60% semantic + 40% keyword
        combined_score = (0.6 * semantic_score) + (0.4 * keyword_score)
        
        results.append((doc, combined_score))
    
    # Sort by combined score (highest first)
    results.sort(key=lambda x: x[1], reverse=True)
    
    return results


def search_knowledge(query: str, n_results: int = 2) -> list[str]:
    """Search active knowledge base for relevant context (with caching and reranking)"""
    global active_collection, _search_cache
    
    # Log which KB is being searched
    print(f"   🔍 Searching KB: {active_kb_id or 'default'} (collection: {active_collection.name})")
    
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
    
    print(f"   📊 Collection has {target_collection.count()} chunks")
    
    if target_collection.count() == 0:
        return []
    
    # Fetch more candidates for reranking (3x requested)
    fetch_count = min(n_results * 3, target_collection.count())
    
    results = target_collection.query(
        query_texts=[query],
        n_results=fetch_count,
        include=["documents", "distances"]
    )
    
    result_docs = []
    if results and results['documents'] and results['documents'][0]:
        docs = results['documents'][0]
        distances = results.get('distances', [[0] * len(docs)])[0]
        
        # Rerank using hybrid scoring
        reranked = _rerank_results(query, docs, distances)
        
        # Take top n_results
        result_docs = [doc for doc, score in reranked[:n_results]]
        
        # Log reranking info
        if reranked:
            print(f"   🎯 Reranked: top score={reranked[0][1]:.3f}")
    
    print(f"   📝 Found {len(result_docs)} relevant chunks")
    
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


# =============================================================================
# MULTI-TENANT SEARCH FUNCTIONS
# These functions accept explicit KB ID instead of using global active_collection
# =============================================================================

def search_knowledge_by_id(query: str, kb_id: str, n_results: int = 2) -> list[str]:
    """Search a specific knowledge base for relevant context.
    
    MULTI-TENANT VERSION: Queries a specific KB by ID, not the global active one.
    
    Args:
        query: Search query
        kb_id: Knowledge base ID (ChromaDB collection: kb_{kb_id})
        n_results: Number of results to return
    
    Returns:
        List of relevant document chunks
    """
    try:
        # Get the collection for this specific KB
        collection_name = f"kb_{kb_id}"
        target_collection = client.get_collection(
            name=collection_name,
            embedding_function=embedding_fn
        )
        
        print(f"   🔍 Searching KB by ID: {kb_id} (collection: {collection_name})")
        print(f"   📊 Collection has {target_collection.count()} chunks")
        
        if target_collection.count() == 0:
            print(f"   ⚠️ KB collection is empty")
            return []
        
        # Fetch more candidates for reranking (3x requested)
        fetch_count = min(n_results * 3, target_collection.count())
        
        results = target_collection.query(
            query_texts=[query],
            n_results=fetch_count,
            include=["documents", "distances"]
        )
        
        result_docs = []
        if results and results['documents'] and results['documents'][0]:
            docs = results['documents'][0]
            distances = results.get('distances', [[0] * len(docs)])[0]
            
            # Rerank using hybrid scoring
            reranked = _rerank_results(query, docs, distances)
            
            # Take top n_results
            result_docs = [doc for doc, score in reranked[:n_results]]
            
            if reranked:
                print(f"   🎯 Reranked: top score={reranked[0][1]:.3f}")
        
        print(f"   📝 Found {len(result_docs)} relevant chunks")
        return result_docs
        
    except Exception as e:
        print(f"   ❌ Error searching KB {kb_id}: {e}")
        return []


def get_kb_info_by_id(kb_id: str) -> dict:
    """Get info about a specific knowledge base by ID.
    
    Args:
        kb_id: Knowledge base ID
    
    Returns:
        Dict with collection info or empty dict if not found
    """
    try:
        collection_name = f"kb_{kb_id}"
        target_collection = client.get_collection(
            name=collection_name,
            embedding_function=embedding_fn
        )
        return {
            "kb_id": kb_id,
            "collection_name": collection_name,
            "chunk_count": target_collection.count()
        }
    except Exception as e:
        print(f"   ⚠️ KB {kb_id} not found: {e}")
        return {}


# Load knowledge base on module import
try:
    load_knowledge_base()
except Exception as e:
    print(f"⚠️ Knowledge base loading failed (will retry on first query): {e}")
