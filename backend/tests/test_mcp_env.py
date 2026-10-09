"""The MCP child process must receive our settings. Unit tests: no database needed.
Run:  python -m pytest -q tests/test_mcp_env.py

Why this exists: the MCP stdio client gives a child only a tiny allow-list of environment variables.
Locally the child still worked (it read backend/.env from disk); in a container there is no .env file,
so it could not load Settings and exited at startup ("Connection closed").
"""
from app.mcp_client import stdio_server_params


def test_child_receives_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app:pw@db:5432/x")
    monkeypatch.setenv("OWNER_DATABASE_URL", "postgresql+psycopg://owner:pw@db:5432/x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    env = stdio_server_params().env
    assert env["DATABASE_URL"].startswith("postgresql+psycopg://app:")
    assert env["OWNER_DATABASE_URL"].startswith("postgresql+psycopg://owner:")
    assert env["ANTHROPIC_API_KEY"] == "sk-test"


def test_child_does_not_receive_unrelated_variables(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_SECRET", "x")
    assert "SOME_UNRELATED_SECRET" not in stdio_server_params().env


def test_unset_settings_are_not_forwarded_as_empty_strings(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    assert "SESSION_SECRET" not in stdio_server_params().env
