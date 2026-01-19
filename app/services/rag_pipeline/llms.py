"""
LLM client configuration for property listing enquiry system.
Uses OpenAI API exclusively.
"""
import os
from typing import Optional, Any, List, Dict
from pydantic_settings import BaseSettings


try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


class LLMSettings(BaseSettings):
    """Settings for LLM configuration."""
   
    # OpenAI settings
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    
    temperature: float = 0.3  
    max_tokens: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables


llm_settings = LLMSettings()

# Module-level state
llm_client: Optional[Any] = None
current_provider: Optional[str] = None
model_name: Optional[str] = None


def _initialize_openai_client() -> None:
    """
    Initialize OpenAI client at module level.
    Sets global variables: llm_client, current_provider, model_name
    """
    global llm_client, current_provider, model_name
    
    if not OPENAI_AVAILABLE:
        print("⚠️  WARNING: OpenAI package is not installed.")
        print("   Please install it: pip install openai")
        print("   The API will start but chat endpoints will fail until configured.")
        return
    
    api_key = os.getenv("OPENAI_API_KEY") or llm_settings.openai_api_key
    # Also check environment variable for model (allows override via OPENAI_MODEL env var)
    model = os.getenv("OPENAI_MODEL") or llm_settings.openai_model
    
    if not api_key:
        print("⚠️  WARNING: OPENAI_API_KEY is not set.")
        print("   Please set OPENAI_API_KEY in your .env file or environment variables.")
        print("   The API will start but chat endpoints will fail until configured.")
        return
    
    try:
        llm_client = OpenAI(api_key=api_key)
        current_provider = "openai"
        model_name = model
        print(f"✓ OpenAI client initialized with model: {model_name}")
    except Exception as e:
        print(f"⚠️  Warning: Failed to initialize OpenAI client: {e}")
        print("   The API will start but chat endpoints will fail until configured.")


# Initialize client at module load
_initialize_openai_client()

if llm_client is None:
    print("⚠️  WARNING: No LLM client could be initialized.")
    print("   The API will start but chat endpoints will fail until LLM credentials are configured.")


def get_llm_client():
    """
    Get the OpenAI LLM client instance.
    
    Returns:
        OpenAI client
        
    Raises:
        ValueError: If no LLM client is initialized
    """
    if llm_client is None:
        raise ValueError(
            "No LLM client available. Please set OPENAI_API_KEY "
            "in your environment variables."
        )
    return llm_client


def get_model_name() -> str:
    """
    Get the configured model name.
    
    Returns:
        Model name string
    """
    if model_name is None:
        return "no-model-configured"
    return model_name


def get_provider() -> str:
    """
    Get the current LLM provider.
    
    Returns:
        "openai"
    """
    return current_provider or "openai"


def get_model_config() -> Dict[str, Any]:
    """
    Get model configuration.
    
    Returns:
        Dictionary with model configuration (model, temperature, max_tokens)
    """
    return {
        "model": model_name,
        "temperature": llm_settings.temperature,
        "max_tokens": llm_settings.max_tokens,
    }


def create_chat_completion(
    messages: List[Dict[str, str]], 
    **kwargs
) -> Any:
    """
    Create a chat completion using OpenAI API.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content'
        **kwargs: Additional parameters (model, temperature, max_tokens, etc.)
        
    Returns:
        Chat completion response from OpenAI API
        
    Raises:
        ValueError: If LLM client is not initialized
    """
    if llm_client is None:
        raise ValueError(
            "LLM client is not initialized. Please set OPENAI_API_KEY "
            "in your environment variables."
        )
    
    config = get_model_config()
    config.update(kwargs)
    
    return llm_client.chat.completions.create(
        messages=messages,
        **config
    )
