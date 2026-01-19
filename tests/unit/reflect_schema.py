"""
Script to reflect the existing database schema and generate SQLAlchemy models.
This is useful if you have an existing database and want to generate models from it.

Usage:
    python tests/unit/reflect_schema.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, inspect
from sqlalchemy.schema import MetaData
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    
    class Config:
        env_file = ".env"
        case_sensitive = False


def reflect_schema():
    """Reflect the database schema and print table information"""
    settings = Settings()
    engine = create_engine(settings.database_url)
    
    inspector = inspect(engine)
    
    print("=" * 80)
    print("DATABASE SCHEMA REFLECTION")
    print("=" * 80)
    print(f"\nDatabase: {engine.url.database}")
    print(f"Tables found: {len(inspector.get_table_names())}\n")
    
    for table_name in inspector.get_table_names():
        print(f"\n{'=' * 80}")
        print(f"TABLE: {table_name}")
        print(f"{'=' * 80}")
        
        # Get columns
        columns = inspector.get_columns(table_name)
        print("\nColumns:")
        for col in columns:
            pk = " (PK)" if col.get('primary_key') else ""
            nullable = " (nullable)" if col.get('nullable') else " (NOT NULL)"
            default = f" DEFAULT {col.get('default')}" if col.get('default') else ""
            print(f"  - {col['name']}: {col['type']}{pk}{nullable}{default}")
        
        # Get primary keys
        pk_constraint = inspector.get_pk_constraint(table_name)
        if pk_constraint['constrained_columns']:
            print(f"\nPrimary Key: {', '.join(pk_constraint['constrained_columns'])}")
        
        # Get foreign keys
        fks = inspector.get_foreign_keys(table_name)
        if fks:
            print("\nForeign Keys:")
            for fk in fks:
                print(f"  - {', '.join(fk['constrained_columns'])} -> {fk['referred_table']}.{', '.join(fk['referred_columns'])}")
        
        # Get indexes
        indexes = inspector.get_indexes(table_name)
        if indexes:
            print("\nIndexes:")
            for idx in indexes:
                unique = " (UNIQUE)" if idx.get('unique') else ""
                print(f"  - {idx['name']}: {', '.join(idx['column_names'])}{unique}")
    
    print("\n" + "=" * 80)
    print("Reflection complete!")
    print("=" * 80)
    print("\nYou can use this information to create your SQLAlchemy models.")
    print("Or, if you want to auto-generate models, you can use sqlacodegen:")
    print("  pip install sqlacodegen")
    print(f"  sqlacodegen {settings.database_url} > app/db/models/reflected_models.py")


if __name__ == "__main__":
    try:
        reflect_schema()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

