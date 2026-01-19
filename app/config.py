"""
Application configuration and environment variable setup.

This module must be imported early to set environment variables before
libraries (like transformers/tokenizers) are imported.
"""
import os


def setup_environment():
    """
    Set up environment variables that must be configured before importing
    libraries that use them (e.g., transformers, tokenizers).
    
    This should be called at the very beginning of the application startup.
    """
    # Disable telemetry for various libraries
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    
    # Disable tokenizers parallelism warnings
    # Set to "false" to prevent warnings when using tokenizers in multiple processes
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# Automatically set up environment when this module is imported
setup_environment()

