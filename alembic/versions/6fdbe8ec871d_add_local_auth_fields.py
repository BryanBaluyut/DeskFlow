"""add_local_auth_fields

Revision ID: 6fdbe8ec871d
Revises:
Create Date: 2026-03-29 21:12:01.487044

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fdbe8ec871d'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch mode required for SQLite ALTER TABLE support
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("entra_oid", existing_type=sa.String(255), nullable=True)
        batch_op.add_column(sa.Column("auth_method", sa.String(20), nullable=False, server_default="local"))

    # Backfill: existing users with entra_oid should be marked as oauth
    op.execute(
        "UPDATE users SET auth_method = 'oauth' WHERE entra_oid IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("auth_method")
        batch_op.alter_column("entra_oid", existing_type=sa.String(255), nullable=False)
