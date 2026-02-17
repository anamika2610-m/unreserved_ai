"""
Central configuration for RAG pipeline defaults.

These values centralize "magic numbers" used across generation/retrieval
while keeping the existing behavior and defaults unchanged.
"""

# Similarity threshold used when deciding whether generic knowledge is relevant
GENERIC_SIMILARITY_THRESHOLD: float = 0.3

# Nearby-properties defaults (shared between retrieval, augmentation, and generation)
DEFAULT_MAX_DISTANCE_KM: float = 15.0
DEFAULT_MAX_NEARBY_PROPERTIES: int = 5

