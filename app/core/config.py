import os
from dotenv import load_dotenv

load_dotenv()  # loads .env automatically

SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME")

# Azure OpenAI Embeddings
AZURE_EMBEDDING_DEPLOYMENT_NAME = os.getenv("AZURE_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-ada-002")

if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
    raise RuntimeError("Azure OpenAI environment variables not set")
