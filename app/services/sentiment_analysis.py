"""
Sentiment Analysis Service

Analyzes call transcripts using LLM to determine user sentiment and intent
based on agent-specific conditions defined in sentiment_analysis_prompt.
"""

import json
import os
from typing import Optional, Dict, Any
from openai import AzureOpenAI

# Azure OpenAI configuration - use existing project config
from app.core.config import AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME

_ao_client: Optional[AzureOpenAI] = None


def get_azure_client() -> AzureOpenAI:
    """Get or create Azure OpenAI client"""
    global _ao_client
    if _ao_client is None:
        # Parse the endpoint - remove deployment path if present
        endpoint = AZURE_OPENAI_ENDPOINT
        if "/openai/deployments" in endpoint:
            # Extract base endpoint
            endpoint = endpoint.split("/openai/deployments")[0]
        
        _ao_client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version="2024-02-15-preview",
            azure_endpoint=endpoint
        )
    return _ao_client


def analyze_call_sentiment(
    transcript: str,
    sentiment_prompt: Optional[str] = None,
    agent_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze call transcript sentiment using LLM.
    
    Args:
        transcript: The full call transcript text
        sentiment_prompt: Agent-specific conditions for sentiment analysis
        agent_name: Name of the agent for context
    
    Returns:
        Dictionary with:
        - sentiment: Brief status (e.g., "Interested", "Not Interested", "Callback Requested")
        - details: Full analysis results
        - conditions_matched: List of conditions that were matched
    """
    
    # Default prompt if agent doesn't have custom conditions
    if not sentiment_prompt or not sentiment_prompt.strip():
        sentiment_prompt = """
Analyze the call and determine:
1. Is the user interested in the product/service? (Yes/No/Maybe)
2. Does the user want a callback? (Yes/No)
3. What is the overall user mood? (Positive/Neutral/Negative)
4. Any key concerns mentioned by the user?
"""
    
    # Build the system prompt for sentiment analysis
    system_prompt = f"""You are a call sentiment analyzer. Your job is to analyze call transcripts and determine the outcome based on specific conditions.

Agent Context: {agent_name or 'AI Voice Agent'}

ANALYSIS CRITERIA:
{sentiment_prompt}

RESPONSE FORMAT:
You must respond with a valid JSON object containing:
{{
    "sentiment": "<primary_sentiment>",
    "interested": <true/false>,
    "wants_callback": <true/false>,
    "mood": "<positive/neutral/negative>",
    "conditions_matched": ["<condition1>", "<condition2>"],
    "key_points": ["<point1>", "<point2>"],
    "summary": "<one_line_summary>"
}}

For "sentiment", use one of these values based on your analysis:
- "Interested" - User showed clear interest
- "Not Interested" - User explicitly declined or showed no interest
- "Callback Requested" - User wants to be contacted again
- "Already Customer" - User is already a customer
- "Needs Info" - User needs more information before deciding
- "Busy/Maybe Later" - User was busy but didn't decline
- "Wrong Number" - Wrong contact or spam
- "Unclear" - Could not determine sentiment

Analyze the following call transcript and respond ONLY with the JSON object, no other text:"""

    try:
        client = get_azure_client()
        
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"CALL TRANSCRIPT:\n\n{transcript}"}
            ],
            temperature=0.3,  # Lower temperature for more consistent analysis
            max_tokens=500
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        # Handle potential markdown code blocks
        if result_text.startswith("```"):
            # Extract JSON from code block
            lines = result_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json"):
                    in_json = True
                    continue
                elif line.startswith("```"):
                    in_json = False
                    continue
                if in_json:
                    json_lines.append(line)
            result_text = "\n".join(json_lines)
        
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, return a structured response with the raw text
            result = {
                "sentiment": "Unclear",
                "interested": False,
                "wants_callback": False,
                "mood": "neutral",
                "conditions_matched": [],
                "key_points": [],
                "summary": "Could not parse sentiment analysis result",
                "raw_response": result_text
            }
        
        # Ensure required fields exist
        result.setdefault("sentiment", "Unclear")
        result.setdefault("interested", False)
        result.setdefault("wants_callback", False)
        result.setdefault("mood", "neutral")
        result.setdefault("conditions_matched", [])
        result.setdefault("key_points", [])
        result.setdefault("summary", "")
        
        print(f"🎯 Sentiment Analysis Complete: {result.get('sentiment', 'Unknown')}")
        return result
        
    except Exception as e:
        print(f"❌ Sentiment analysis error: {e}")
        return {
            "sentiment": "Error",
            "interested": False,
            "wants_callback": False,
            "mood": "neutral",
            "conditions_matched": [],
            "key_points": [],
            "summary": f"Analysis failed: {str(e)}",
            "error": str(e)
        }


def save_call_sentiment(call_id: str, sentiment: str, details: Dict[str, Any]) -> bool:
    """
    Save sentiment analysis results to the call record.
    
    Args:
        call_id: The call ID to update
        sentiment: Brief sentiment status
        details: Full analysis dictionary (will be JSON encoded)
    
    Returns:
        True if saved successfully, False otherwise
    """
    from app.db.session import SessionLocal
    from app.db.models import Call
    
    db = SessionLocal()
    try:
        call = db.query(Call).filter(Call.id == call_id).first()
        if call:
            call.sentiment = sentiment[:50] if sentiment else None  # Truncate to field limit
            call.sentiment_details = json.dumps(details) if details else None
            db.commit()
            print(f"💾 Sentiment saved for call {call_id}: {sentiment}")
            return True
        else:
            print(f"⚠️ Call not found for sentiment update: {call_id}")
            return False
    except Exception as e:
        db.rollback()
        print(f"❌ Error saving sentiment: {e}")
        return False
    finally:
        db.close()


def analyze_and_save_sentiment(call_id: str, transcript: str, agent_id: str = None) -> Dict[str, Any]:
    """
    Convenience function to analyze sentiment and save results in one call.
    
    Args:
        call_id: The call ID
        transcript: Call transcript text
        agent_id: Optional agent ID to get custom sentiment prompt
    
    Returns:
        The sentiment analysis result dictionary
    """
    sentiment_prompt = None
    agent_name = None
    
    # Get agent's sentiment analysis prompt if available
    if agent_id:
        from app.db.session import SessionLocal
        from app.db.models import Agent
        
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                sentiment_prompt = agent.sentiment_analysis_prompt
                agent_name = agent.name
        finally:
            db.close()
    
    # Analyze sentiment
    result = analyze_call_sentiment(transcript, sentiment_prompt, agent_name)
    
    # Save results
    save_call_sentiment(call_id, result.get("sentiment", "Unknown"), result)
    
    return result
