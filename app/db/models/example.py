"""
Example model file - DELETE THIS when you create your actual models.

This shows the pattern for creating SQLAlchemy models based on your ERD.
"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


# Example model - replace with your actual models from the ERD
class ExampleUser(Base):
    """
    Example user model - DELETE THIS and create your actual models.
    
    Based on your ERD, you should create models for:
    - users
    - properties
    - listings
    - offers
    - inspections
    - etc.
    """
    __tablename__ = "example_users"  # This will be "users" in your actual model
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Example relationship - adjust based on your ERD
    # devices = relationship("UserDevice", back_populates="user")


# Example of a model with foreign key
class ExampleDevice(Base):
    """
    Example device model - DELETE THIS and create your actual models.
    """
    __tablename__ = "example_devices"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("example_users.id"), nullable=False)
    device_token = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Example relationship
    # user = relationship("ExampleUser", back_populates="devices")

