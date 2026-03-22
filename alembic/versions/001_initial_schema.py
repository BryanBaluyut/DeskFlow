"""Initial schema - all tables from models.py.

Revision ID: 001
Revises:
Create Date: 2026-03-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For the initial migration, we use metadata.create_all via raw SQL
    # generated from our models. This ensures the schema matches models.py exactly.
    # Future migrations will use incremental op.add_column / op.create_table calls.
    from app.models import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.models import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
