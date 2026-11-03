"""
Smartt Linux Service

Main package for Smartt (Smart Attendance Record Tracking Tajuddin), the
school-owned attendance service that reports taps to Datang.my.
"""

__version__ = "1.0.0"
__author__ = "Smartt"

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
