"""
LLM client configuration for property listing enquiry system.
Supports Groq API (primary) and OpenAI (fallback).
"""
import os
from typing import Optional, Union
from pydantic_settings import BaseSettings


try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    Groq = None

# Try to import OpenAI (fallback)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


class LLMSettings(BaseSettings):
    """Settings for LLM configuration."""
    # Groq settings (primary)
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"  # Updated to currently available model
    llm_provider: str = "groq"  # "groq" or "openai"
    
    # OpenAI settings (fallback)
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    
    # Common settings
    temperature: float = 0.3  # Lower temperature for factual responses
    max_tokens: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Initialize settings
llm_settings = LLMSettings()

# Determine which provider to use
provider = llm_settings.llm_provider.lower()

# Initialize client based on provider
llm_client = None
current_provider = None
model_name = None

if provider == "groq" and GROQ_AVAILABLE:
    # Try Groq first
    api_key = os.getenv("GROQ_API_KEY") or llm_settings.groq_api_key
    if api_key:
        try:
            llm_client = Groq(api_key=api_key)
            current_provider = "groq"
            model_name = llm_settings.groq_model
        except Exception as e:
            print(f"Warning: Failed to initialize Groq client: {e}")
    
    # Fallback to OpenAI if Groq fails
    if llm_client is None and OPENAI_AVAILABLE:
        api_key = os.getenv("OPENAI_API_KEY") or llm_settings.openai_api_key
        if api_key:
            llm_client = OpenAI(api_key=api_key)
            current_provider = "openai"
            model_name = llm_settings.openai_model
            print("Warning: Using OpenAI as fallback (Groq not available or failed)")

elif provider == "openai" and OPENAI_AVAILABLE:
    # Use OpenAI
    api_key = os.getenv("OPENAI_API_KEY") or llm_settings.openai_api_key
    if api_key:
        llm_client = OpenAI(api_key=api_key)
        current_provider = "openai"
        model_name = llm_settings.openai_model

# Error if no client could be initialized
if llm_client is None:
    error_msg = "No LLM client could be initialized. "
    if provider == "groq":
        error_msg += "Please set GROQ_API_KEY in your .env file or environment variables."
        if not GROQ_AVAILABLE:
            error_msg += " (groq package not installed - run: pip install groq)"
    else:
        error_msg += "Please set OPENAI_API_KEY in your .env file or environment variables."
        if not OPENAI_AVAILABLE:
            error_msg += " (openai package not installed - run: pip install openai)"
    raise ValueError(error_msg)


def get_llm_client():
    """
    Get the LLM client instance (Groq or OpenAI).
    
    Returns:
        Groq or OpenAI client
    """
    return llm_client


def get_model_name() -> str:
    """
    Get the configured model name.
    
    Returns:
        Model name string
    """
    return model_name


def get_provider() -> str:
    """
    Get the current LLM provider.
    
    Returns:
        "groq" or "openai"
    """
    return current_provider


def get_model_config() -> dict:
    """
    Get model configuration.
    
    Returns:
        Dictionary with model configuration
    """
    return {
        "model": model_name,
        "temperature": llm_settings.temperature,
        "max_tokens": llm_settings.max_tokens,
    }


def create_chat_completion(messages: list, **kwargs) -> any:
    """
    Create a chat completion using the configured LLM provider.
    This provides a unified interface for both Groq and OpenAI.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content'
        **kwargs: Additional parameters (model, temperature, max_tokens, etc.)
        
    Returns:
        Chat completion response
    """
    config = get_model_config()
    config.update(kwargs)
    
    if current_provider == "groq":
        return llm_client.chat.completions.create(
            messages=messages,
            **config
        )
    else:  # OpenAI
        return llm_client.chat.completions.create(
            messages=messages,
            **config
        )
