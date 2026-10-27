"""Typed client, MCP tools and HTTP routes for USDA ESMIS.

Distribution ``xippios-usda-esmis``. Public API: ``__version__`` and the task
functions re-exported here. Endpoint wrappers under ``api/`` and the configured client
in ``_client`` are internal.
"""

from xippios.usda.esmis._version import __version__

__all__ = ["__version__"]
