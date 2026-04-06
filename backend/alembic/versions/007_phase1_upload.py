"""phase1 upload

Revision ID: 007
Revises: 006
Create Date: 2026-04-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    # 1. users table
    op.add_column('users', sa.Column('auth_provider', sa.String(length=50), nullable=True))
    op.execute("UPDATE users SET auth_provider = 'local'")
    op.alter_column('users', 'auth_provider', nullable=False, server_default='local')

    # 2. datasets table
    # rename s3_key -> storage_key
    op.alter_column('datasets', 's3_key', new_column_name='storage_key')
    # rename row_count -> n_rows
    op.alter_column('datasets', 'row_count', new_column_name='n_rows')
    # rename col_count -> n_cols
    op.alter_column('datasets', 'col_count', new_column_name='n_cols')
    # add schema_json
    op.add_column('datasets', sa.Column('schema_json', sa.JSON(), nullable=True))
    # rename profiling_status -> processing_status
    op.alter_column('datasets', 'profiling_status', new_column_name='processing_status')
    op.execute("UPDATE datasets SET processing_status = 'uploaded' WHERE processing_status = 'pending'")
    # drop headers and profile
    op.drop_column('datasets', 'headers')
    op.drop_column('datasets', 'profile')
    # add profiling_log
    op.add_column('datasets', sa.Column('profiling_log', sa.JSON(), nullable=True))

    # 3. Create dataset_profiles table
    op.create_table('dataset_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('profile_json', sa.JSON(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id')
    )
    op.create_index('ix_profiles_dataset_computed', 'dataset_profiles', ['dataset_id', 'computed_at'], unique=False)
    op.create_index(op.f('ix_dataset_profiles_dataset_id'), 'dataset_profiles', ['dataset_id'], unique=False)


def downgrade():
    # 3. Drop dataset_profiles table
    op.drop_index(op.f('ix_dataset_profiles_dataset_id'), table_name='dataset_profiles')
    op.drop_index('ix_profiles_dataset_computed', table_name='dataset_profiles')
    op.drop_table('dataset_profiles')

    # 2. Revert datasets table
    op.drop_column('datasets', 'profiling_log')
    op.add_column('datasets', sa.Column('profile', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('datasets', sa.Column('headers', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.alter_column('datasets', 'processing_status', new_column_name='profiling_status')
    op.execute("UPDATE datasets SET profiling_status = 'pending' WHERE profiling_status = 'uploaded'")
    op.drop_column('datasets', 'schema_json')
    op.alter_column('datasets', 'n_cols', new_column_name='col_count')
    op.alter_column('datasets', 'n_rows', new_column_name='row_count')
    op.alter_column('datasets', 'storage_key', new_column_name='s3_key')

    # 1. Revert users table
    op.drop_column('users', 'auth_provider')
