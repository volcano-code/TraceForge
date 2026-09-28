"""Add durable external-operation intent and fencing, preserving M0 records.

Revision ID: b82f4b61d2a0
Revises: a922eb20b205
"""
from alembic import op
import sqlalchemy as sa

revision = 'b82f4b61d2a0'
down_revision = 'a922eb20b205'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('approvals', sa.Column('delivery_kind', sa.String(40), nullable=False, server_default='LOCAL_RECEIPT'))
    # Nullable metadata keeps old LOCAL_RECEIPT rows valid. artifact_id continues
    # pointing to an immutable intent before completion, then to the receipt.
    for name, type_ in [('approval_id', sa.String(36)), ('request_hash', sa.String(64)),
                        ('request_payload', sa.JSON()), ('lease_token', sa.String(36)),
                        ('last_error', sa.String(80))]:
        op.add_column('operations', sa.Column(name, type_, nullable=True))
    for name in ('lease_until', 'generation', 'attempts'):
        op.add_column('operations', sa.Column(name, sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    # Removing an unresolved intent would erase recovery information. Fail closed.
    conn = op.get_bind()
    pending = conn.scalar(sa.text("SELECT count(*) FROM operations WHERE kind='SIMULATED_PR'"))
    if pending:
        raise RuntimeError('Cannot downgrade while simulator operation history exists; archive it before removing its schema')
    with op.batch_alter_table('approvals') as batch:
        batch.drop_column('delivery_kind')
    with op.batch_alter_table('operations') as batch:
        for name in ('approval_id', 'request_hash', 'request_payload', 'lease_token',
                     'last_error', 'lease_until', 'generation', 'attempts'):
            batch.drop_column(name)
