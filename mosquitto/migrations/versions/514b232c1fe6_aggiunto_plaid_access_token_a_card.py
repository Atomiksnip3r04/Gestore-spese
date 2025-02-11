"""Aggiunto plaid_access_token a Card

Revision ID: 514b232c1fe6
Revises: bfc7bcafc479
Create Date: 2025-02-11 18:07:33.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '514b232c1fe6'
down_revision = 'bfc7bcafc479'
branch_labels = None
depends_on = None


def upgrade():
    # Usa PRAGMA per controllare le colonne (SQLite)
    conn = op.get_bind()
    # Controlla la tabella 'card'
    card_info = conn.execute("PRAGMA table_info(card)").fetchall()
    card_columns = [row[1] for row in card_info]  # il nome della colonna è nel secondo elemento di ogni riga
    if 'plaid_access_token' not in card_columns:
        with op.batch_alter_table('card', schema=None) as batch_op:
            batch_op.add_column(sa.Column('plaid_access_token', sa.String(length=500), nullable=True))
    else:
        print("La colonna 'plaid_access_token' esiste già in 'card'. Salto questa operazione.")
    
    # Controlla la tabella 'transaction'
    transaction_info = conn.execute("PRAGMA table_info(transaction)").fetchall()
    transaction_columns = [row[1] for row in transaction_info]
    if 'external_id' not in transaction_columns:
        with op.batch_alter_table('transaction', schema=None) as batch_op:
            batch_op.add_column(sa.Column('external_id', sa.String(length=100), nullable=True))
            batch_op.create_unique_constraint("uq_transaction_external_id", ["external_id"])
    else:
        print("La colonna 'external_id' esiste già in 'transaction'.")


def downgrade():
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_constraint("uq_transaction_external_id", type_="unique")
        batch_op.drop_column('external_id')
    with op.batch_alter_table('card', schema=None) as batch_op:
        batch_op.drop_column('plaid_access_token') 