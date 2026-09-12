"""excel aligned schema

Revision ID: 59deee17c4c7
Revises:
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59deee17c4c7'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index(op.f('ix_companies_id'), 'companies', ['id'], unique=False)
    op.create_index(op.f('ix_companies_code'), 'companies', ['code'], unique=True)

    op.create_table(
        'foods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index(op.f('ix_foods_id'), 'foods', ['id'], unique=False)
    op.create_index(op.f('ix_foods_code'), 'foods', ['code'], unique=True)

    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=200), nullable=False),
        sa.Column('value_type', sa.String(length=50), nullable=True),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_settings_id'), 'settings', ['id'], unique=False)
    op.create_index(op.f('ix_settings_key'), 'settings', ['key'], unique=True)

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('user', sa.String(length=200), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('before_value', sa.String(length=500), nullable=True),
        sa.Column('after_value', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'], unique=False)

    op.create_table(
        'sites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('address', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sites_id'), 'sites', ['id'], unique=False)
    op.create_index(op.f('ix_sites_company_id'), 'sites', ['company_id'], unique=False)
    op.create_index(op.f('ix_sites_code'), 'sites', ['code'], unique=False)

    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('personnel_code', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('mobile', sa.String(length=20), nullable=True),
        sa.Column('bale_chat_id', sa.String(length=50), nullable=True),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('site_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('personnel_code'),
        sa.UniqueConstraint('mobile'),
        sa.UniqueConstraint('bale_chat_id'),
    )
    op.create_index(op.f('ix_employees_id'), 'employees', ['id'], unique=False)
    op.create_index(op.f('ix_employees_personnel_code'), 'employees', ['personnel_code'], unique=True)
    op.create_index(op.f('ix_employees_mobile'), 'employees', ['mobile'], unique=True)
    op.create_index(op.f('ix_employees_bale_chat_id'), 'employees', ['bale_chat_id'], unique=True)
    op.create_index(op.f('ix_employees_company_id'), 'employees', ['company_id'], unique=False)
    op.create_index(op.f('ix_employees_site_id'), 'employees', ['site_id'], unique=False)

    op.create_table(
        'welfare_manager_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('site_id', sa.Integer(), nullable=False),
        sa.Column('assignment_type', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_welfare_manager_assignments_id'), 'welfare_manager_assignments', ['id'], unique=False)
    op.create_index(op.f('ix_welfare_manager_assignments_employee_id'), 'welfare_manager_assignments', ['employee_id'], unique=False)
    op.create_index(op.f('ix_welfare_manager_assignments_site_id'), 'welfare_manager_assignments', ['site_id'], unique=False)

    op.create_table(
        'menu_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('site_id', sa.Integer(), nullable=False),
        sa.Column('food_id', sa.Integer(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('is_selectable', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id']),
        sa.ForeignKeyConstraint(['food_id'], ['foods.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_menu_entries_id'), 'menu_entries', ['id'], unique=False)
    op.create_index(op.f('ix_menu_entries_date'), 'menu_entries', ['date'], unique=False)
    op.create_index(op.f('ix_menu_entries_site_id'), 'menu_entries', ['site_id'], unique=False)
    op.create_index(op.f('ix_menu_entries_food_id'), 'menu_entries', ['food_id'], unique=False)

    op.create_table(
        'personal_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tracking_code', sa.String(length=50), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('food_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('created_by', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['food_id'], ['foods.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tracking_code'),
    )
    op.create_index(op.f('ix_personal_orders_id'), 'personal_orders', ['id'], unique=False)
    op.create_index(op.f('ix_personal_orders_tracking_code'), 'personal_orders', ['tracking_code'], unique=True)
    op.create_index(op.f('ix_personal_orders_date'), 'personal_orders', ['date'], unique=False)
    op.create_index(op.f('ix_personal_orders_employee_id'), 'personal_orders', ['employee_id'], unique=False)
    op.create_index(op.f('ix_personal_orders_food_id'), 'personal_orders', ['food_id'], unique=False)

    op.create_table(
        'welfare_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tracking_code', sa.String(length=50), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('site_id', sa.Integer(), nullable=False),
        sa.Column('food_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('created_by', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id']),
        sa.ForeignKeyConstraint(['food_id'], ['foods.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tracking_code'),
    )
    op.create_index(op.f('ix_welfare_orders_id'), 'welfare_orders', ['id'], unique=False)
    op.create_index(op.f('ix_welfare_orders_tracking_code'), 'welfare_orders', ['tracking_code'], unique=True)
    op.create_index(op.f('ix_welfare_orders_date'), 'welfare_orders', ['date'], unique=False)
    op.create_index(op.f('ix_welfare_orders_site_id'), 'welfare_orders', ['site_id'], unique=False)
    op.create_index(op.f('ix_welfare_orders_food_id'), 'welfare_orders', ['food_id'], unique=False)


def downgrade() -> None:
    op.drop_table('welfare_orders')
    op.drop_table('personal_orders')
    op.drop_table('menu_entries')
    op.drop_table('welfare_manager_assignments')
    op.drop_table('employees')
    op.drop_table('sites')
    op.drop_table('audit_logs')
    op.drop_table('settings')
    op.drop_table('foods')
    op.drop_table('companies')
