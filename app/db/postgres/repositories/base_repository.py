"""
Base repository pattern for database operations.
Provides common CRUD operations and async database session management.
"""
from contextlib import asynccontextmanager
from typing import Generic, TypeVar, Type, Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError


ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """
    Base repository class providing common database operations.
    
    Implements the Repository Pattern to abstract database access logic.
    All methods automatically handle transaction rollback on errors.
    """
    
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        """
        Initialize repository with model and session.
        
        Args:
            model: SQLAlchemy model class
            session: Async database session
        """
        self.model = model
        self.session = session
    
    @asynccontextmanager
    async def _handle_errors(self, auto_commit_read: bool = True):
        """
        Async context manager for automatic error handling and transaction cleanup.
        
        Args:
            auto_commit_read: If True, commits read-only operations to prevent idle transactions
        
        Usage:
            async with self._handle_errors():
                # database operations
        """
        try:
            yield
            # Always commit to close the transaction
            # This prevents "idle in transaction" state even for read-only queries
            if auto_commit_read and not self.session.in_transaction():
                pass
            elif auto_commit_read:
                await self.session.commit()
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise e
        except Exception as e:
            await self.session.rollback()
            raise e
    
    async def get_by_id(self, id: Any) -> Optional[ModelType]:
        """
        Get a single record by ID.
        
        Args:
            id: Record ID
            
        Returns:
            Model instance or None
        """
        async with self._handle_errors():
            return await self.session.get(self.model, id)
    
    async def get_all(self, limit: Optional[int] = None, offset: Optional[int] = None) -> List[ModelType]:
        """
        Get all records with optional pagination.
        
        Args:
            limit: Maximum number of records
            offset: Number of records to skip
            
        Returns:
            List of model instances
        """
        async with self._handle_errors():
            query = select(self.model)
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            result = await self.session.execute(query)
            return list(result.scalars().all())
    
    async def get_by_filter(self, filters: Dict[str, Any], limit: Optional[int] = None) -> List[ModelType]:
        """
        Get records matching filters.
        
        Args:
            filters: Dictionary of column: value pairs
            limit: Maximum number of records
            
        Returns:
            List of model instances
            
        Raises:
            AttributeError: If filter key doesn't exist on model
        """
        async with self._handle_errors():
            query = select(self.model)
            for key, value in filters.items():
                if not hasattr(self.model, key):
                    raise AttributeError(f"Model {self.model.__name__} has no attribute '{key}'")
                query = query.where(getattr(self.model, key) == value)
            if limit:
                query = query.limit(limit)
            result = await self.session.execute(query)
            return list(result.scalars().all())
    
    async def create(self, **kwargs) -> ModelType:
        """
        Create a new record.
        
        Args:
            **kwargs: Column values (will be passed directly to model constructor)
            
        Returns:
            Created model instance
            
        Note:
            Model-specific type conversions (e.g., UUID strings to UUID objects)
            should be handled by the model's __init__ method or in specialized
            repository subclasses, not in this base class.
        """
        async with self._handle_errors():
            instance = self.model(**kwargs)
            self.session.add(instance)
            await self.session.commit()
            await self.session.refresh(instance)
            return instance
    
    async def update(self, id: Any, **kwargs) -> Optional[ModelType]:
        """
        Update a record by ID.
        
        Args:
            id: Record ID
            **kwargs: Column values to update
            
        Returns:
            Updated model instance or None if not found
        """
        async with self._handle_errors():
            instance = await self.get_by_id(id)
            if not instance:
                return None
            
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
                else:
                    raise AttributeError(f"Model {self.model.__name__} has no attribute '{key}'")
            
            await self.session.commit()
            await self.session.refresh(instance)
            return instance
    
    async def delete(self, id: Any) -> bool:
        """
        Delete a record by ID.
        
        Args:
            id: Record ID
            
        Returns:
            True if deleted, False if not found
        """
        async with self._handle_errors():
            instance = await self.get_by_id(id)
            if not instance:
                return False
            
            await self.session.delete(instance)
            await self.session.commit()
            return True
    
    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count records matching filters.
        
        Args:
            filters: Optional dictionary of column: value pairs
            
        Returns:
            Number of matching records
        """
        async with self._handle_errors():
            query = select(func.count()).select_from(self.model)
            
            if filters:
                for key, value in filters.items():
                    if not hasattr(self.model, key):
                        raise AttributeError(f"Model {self.model.__name__} has no attribute '{key}'")
                    query = query.where(getattr(self.model, key) == value)
            
            result = await self.session.execute(query)
            return result.scalar() or 0
    
    async def exists(self, filters: Dict[str, Any]) -> bool:
        """
        Check if a record exists matching filters.
        
        Args:
            filters: Dictionary of column: value pairs
            
        Returns:
            True if exists, False otherwise
        """
        return await self.count(filters) > 0
