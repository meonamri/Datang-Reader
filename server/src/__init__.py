"""
Datang Reader Linux Service

Main package for the Datang attendance reader Linux service.
"""

__version__ = "1.0.0"
__author__ = "Datang Linux Port"

from .config import Config
from .rfid_reader import RFIDReader
from .api_client import DatangAPIClient, MockAPIClient
from .auth_manager import AuthManager

__all__ = [
    'Config',
    'RFIDReader',
    'DatangAPIClient',
    'MockAPIClient',
    'AuthManager',
]
