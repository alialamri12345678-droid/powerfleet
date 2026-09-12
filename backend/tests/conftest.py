"""Test-only settings applied before application modules are imported."""

import os


os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-that-is-long-enough"
