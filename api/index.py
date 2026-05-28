"""Vercel serverless entry point — re-exports the Flask app from app.py."""

import os
import sys

# Add project root to path so `import app` works when this file lives in /api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402, F401
