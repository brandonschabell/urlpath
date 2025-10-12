"""Pytest configuration for URLPath."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is in sys.path for imports
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture(autouse=True)
def mock_http_requests(request):
    """Mock HTTP requests for README tests to avoid network calls."""
    # Only apply to README.md tests
    if "README.md" in str(request.node.fspath):
        # Create a mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Mocked response"
        mock_response.json.return_value = {"mocked": True}

        # Patch all HTTP methods
        with (
            patch("requests.get", return_value=mock_response),
            patch("requests.post", return_value=mock_response),
            patch("requests.put", return_value=mock_response),
            patch("requests.patch", return_value=mock_response),
            patch("requests.delete", return_value=mock_response),
            patch("requests.options", return_value=mock_response),
            patch("requests.head", return_value=mock_response),
        ):
            yield
    else:
        yield
