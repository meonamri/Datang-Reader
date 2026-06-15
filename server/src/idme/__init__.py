"""
IDME Module for Datang-Reader

Automated IDME portal attendance submission.
Detects absent students from RFID scans and submits to MOEIS.

Usage:
    from src.idme import init_idme_module
    from src.idme.api_routes import idme_bp

    # In Flask app:
    orchestrator = init_idme_module(service_manager)
    app.register_blueprint(idme_bp)
"""

from .idme_config import IDMEConfig
from .api_routes import idme_bp, init_idme_module

__all__ = [
    'IDMEConfig',
    'idme_bp',
    'init_idme_module',
]
