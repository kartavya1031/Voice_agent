"""
Agent Configuration Service
Manages dynamic knowledge bases and speech settings
"""

import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# Config file path
CONFIG_DIR = Path(__file__).parent.parent / "data"
CONFIG_FILE = CONFIG_DIR / "agent_config.json"

# Default system prompt
DEFAULT_SYSTEM_PROMPT = """You are an AI voice assistant for Anvenssa.AI, a company specializing in AI solutions for businesses.

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


@dataclass
class SpeechSettings:
    recognition_language: str = "en-IN"
    synthesis_voice_name: str = "en-IN-NeerjaNeural"

@dataclass
class KnowledgeBase:
    id: str
    name: str
    filename: str
    created_at: str
    chunk_count: int = 0

@dataclass
class AgentConfig:
    speech_settings: SpeechSettings
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    active_knowledge_base_id: Optional[str] = None
    knowledge_bases: list = None
    
    def __post_init__(self):
        if self.knowledge_bases is None:
            self.knowledge_bases = []
        if not self.system_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT


class AgentConfigService:
    def __init__(self):
        self.config: AgentConfig = self._load_config()
    
    def _load_config(self) -> AgentConfig:
        """Load config from file or create default"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                speech_settings = SpeechSettings(**data.get('speech_settings', {}))
                knowledge_bases = [
                    KnowledgeBase(**kb) for kb in data.get('knowledge_bases', [])
                ]
                
                return AgentConfig(
                    speech_settings=speech_settings,
                    system_prompt=data.get('system_prompt', DEFAULT_SYSTEM_PROMPT),
                    active_knowledge_base_id=data.get('active_knowledge_base_id'),
                    knowledge_bases=knowledge_bases
                )
            except Exception as e:
                print(f"⚠️ Error loading agent config: {e}")
        
        # Return default config
        return AgentConfig(
            speech_settings=SpeechSettings(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            knowledge_bases=[]
        )
    
    def _save_config(self):
        """Save config to file"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        data = {
            'speech_settings': asdict(self.config.speech_settings),
            'system_prompt': self.config.system_prompt,
            'active_knowledge_base_id': self.config.active_knowledge_base_id,
            'knowledge_bases': [asdict(kb) for kb in self.config.knowledge_bases]
        }
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def get_speech_settings(self) -> SpeechSettings:
        """Get current speech settings"""
        return self.config.speech_settings
    
    def update_speech_settings(self, recognition_language: Optional[str] = None, 
                               synthesis_voice_name: Optional[str] = None) -> SpeechSettings:
        """Update speech settings"""
        if recognition_language:
            self.config.speech_settings.recognition_language = recognition_language
        if synthesis_voice_name:
            self.config.speech_settings.synthesis_voice_name = synthesis_voice_name
        
        self._save_config()
        return self.config.speech_settings
    
    def get_knowledge_bases(self) -> list[KnowledgeBase]:
        """Get all knowledge bases"""
        return self.config.knowledge_bases
    
    def get_active_knowledge_base(self) -> Optional[KnowledgeBase]:
        """Get the currently active knowledge base"""
        if not self.config.active_knowledge_base_id:
            return None
        
        for kb in self.config.knowledge_bases:
            if kb.id == self.config.active_knowledge_base_id:
                return kb
        return None
    
    def add_knowledge_base(self, kb_id: str, name: str, filename: str, chunk_count: int = 0) -> KnowledgeBase:
        """Add a new knowledge base"""
        kb = KnowledgeBase(
            id=kb_id,
            name=name,
            filename=filename,
            created_at=datetime.now().isoformat(),
            chunk_count=chunk_count
        )
        self.config.knowledge_bases.append(kb)
        
        # If this is the first KB, make it active
        if len(self.config.knowledge_bases) == 1:
            self.config.active_knowledge_base_id = kb_id
        
        self._save_config()
        return kb
    
    def set_active_knowledge_base(self, kb_id: Optional[str]) -> bool:
        """Set the active knowledge base"""
        if kb_id is None:
            self.config.active_knowledge_base_id = None
            self._save_config()
            return True
        
        for kb in self.config.knowledge_bases:
            if kb.id == kb_id:
                self.config.active_knowledge_base_id = kb_id
                self._save_config()
                return True
        return False
    
    def delete_knowledge_base(self, kb_id: str) -> bool:
        """Delete a knowledge base"""
        for i, kb in enumerate(self.config.knowledge_bases):
            if kb.id == kb_id:
                self.config.knowledge_bases.pop(i)
                
                # If deleting active KB, clear active
                if self.config.active_knowledge_base_id == kb_id:
                    self.config.active_knowledge_base_id = None
                
                self._save_config()
                return True
        return False
    
    def update_knowledge_base_chunks(self, kb_id: str, chunk_count: int):
        """Update the chunk count for a knowledge base"""
        for kb in self.config.knowledge_bases:
            if kb.id == kb_id:
                kb.chunk_count = chunk_count
                self._save_config()
                return
    
    def get_system_prompt(self) -> str:
        """Get current system prompt"""
        return self.config.system_prompt
    
    def update_system_prompt(self, prompt: str) -> str:
        """Update system prompt"""
        if prompt and prompt.strip():
            self.config.system_prompt = prompt.strip()
        else:
            self.config.system_prompt = DEFAULT_SYSTEM_PROMPT
        
        self._save_config()
        return self.config.system_prompt
    
    def reset_system_prompt(self) -> str:
        """Reset system prompt to default"""
        self.config.system_prompt = DEFAULT_SYSTEM_PROMPT
        self._save_config()
        return self.config.system_prompt


# Global instance
agent_config_service = AgentConfigService()
