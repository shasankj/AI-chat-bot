"""Database engines. Two engines, two privilege levels."""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import settings

# Read-only engine used by the chatbot, RAG retriever and MCP server.
# Three independent layers stop writes / runaway queries (any ONE is enough):
#   1. the DB role itself has only SELECT (set up in the migrations)
#   2. default_transaction_read_only=on  -> every transaction on this connection is read-only
#   3. statement_timeout=10s             -> a slow/abusive query is killed by Postgres
# pool_pre_ping: test a connection before use, so connections dropped by AWS idle
# timeouts are replaced instead of raising errors in the middle of a chat.
read_engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=10000"},
)

# Write-capable engine: ONLY setup/ingestion scripts import this, never the chat path.
owner_engine: Engine = create_engine(settings.owner_database_url, pool_pre_ping=True)

# Audit engine: the ONE place the chat path may write. The role only has INSERT/SELECT on hc_audit_log
# (migration 006), so even though this connection is not read-only, it can write nothing else.
audit_engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"options": "-c statement_timeout=5000"},
)
