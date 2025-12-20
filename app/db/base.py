from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import all models here so Alembic can detect them
# This import must come after Base is defined
try:
    from app.db.models import *  # noqa: E402, F401
except ImportError:
    pass  # models.py may not exist yet

# Import conversation models
try:
    from app.db.conversation_models import ConversationMessage, ConversationSession  # noqa: E402, F401
except ImportError:
    pass  # conversation_models.py may not exist yet

