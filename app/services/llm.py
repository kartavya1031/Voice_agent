"""
LLM Service with RAG (Retrieval Augmented Generation)
Uses Azure OpenAI with knowledge base context from vector store
"""

from openai import AzureOpenAI
from app.core.config import (
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_ENDPOINT,
    DEPLOYMENT_NAME
)
from app.services.vector_store import get_context_for_query

client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version="2024-02-15-preview"
)

# System prompt for Anvenssa AI voice agent
SYSTEM_PROMPT = """You are an AI voice assistant for Anvenssa.AI, a company specializing in AI solutions for businesses.

Your role:
- Answer questions about Anvenssa.AI, its products, services, and leadership
- Help potential customers understand how AI can benefit their business
- Be friendly, professional, and conversational
- Keep responses concise and suitable for voice (2-3 sentences typically)
- If you don't know something, offer to connect them with the sales team

Contact Information:
- Phone: +91 8956512955 (Mon-Fri, 10:00-7:00)
- Email: sales@anvenssa.com

Use the provided context to answer questions accurately. If the context doesn't contain relevant information, use your general knowledge but mention that the customer can contact sales for detailed information."""


def build_prompt_with_context(user_query: str) -> list[dict]:
    """Build messages with RAG context"""
    # Get relevant context from knowledge base
    context = get_context_for_query(user_query)
    
    # Build system message with context
    if context:
        system_content = f"""{SYSTEM_PROMPT}

RELEVANT CONTEXT FROM KNOWLEDGE BASE:
{context}

Remember to keep your response brief and conversational for voice interaction."""
    else:
        system_content = SYSTEM_PROMPT
    
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_query}
    ]


def ask_ai(text: str) -> str:
    """Get AI response with RAG context"""
    messages = build_prompt_with_context(text)
    
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=200,  # Keep responses concise for voice
        temperature=0.7
    )
    return response.choices[0].message.content


def ask_ai_streaming(text: str):
    """Stream LLM response token by token with RAG context"""
    messages = build_prompt_with_context(text)
    
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=200,
        temperature=0.7,
        stream=True
    )
    
    for chunk in response:
        # Guard against empty chunks
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
