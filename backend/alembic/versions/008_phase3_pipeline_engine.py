"""phase3 pipeline engine

Revision ID: 008
Revises: 007
Create Date: 2026-04-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Update pipelines table
    op.drop_column('pipelines', 'steps')
    op.add_column('pipelines', sa.Column('steps_hash', sa.String(length=64), nullable=True))

    # 2. Update pipeline_executions table
    op.add_column('pipeline_executions', sa.Column('steps_hash', sa.String(length=64), nullable=True))

    # 3. Create pipeline_steps table
    op.create_table('pipeline_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pipeline_id', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('action_name', sa.String(length=100), nullable=False),
        sa.Column('params_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline_id', 'order_index', name='uq_pipeline_step_order')
    )
    op.create_index('ix_pipeline_steps_pipeline_order', 'pipeline_steps', ['pipeline_id', 'order_index'], unique=False)
    op.create_index(op.f('ix_pipeline_steps_pipeline_id'), 'pipeline_steps', ['pipeline_id'], unique=False)


def downgrade():
    # 3. Drop pipeline_steps table
    op.drop_index(op.f('ix_pipeline_steps_pipeline_id'), table_name='pipeline_steps')
    op.drop_index('ix_pipeline_steps_pipeline_order', table_name='pipeline_steps')
    op.drop_table('pipeline_steps')

    # 2. Revert pipeline_executions table
    op.drop_column('pipeline_executions', 'steps_hash')

    # 1. Revert pipelines table
    op.drop_column('pipelines', 'steps_hash')
    op.add_column('pipelines', sa.Column('steps', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True))
