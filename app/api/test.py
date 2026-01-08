from fastapi import APIRouter
from app.services.llm import ask_ai

router = APIRouter()

@router.get("/test/ai")
def test_ai(text: str = "Hello"):
    return {"reply": ask_ai(text)}
