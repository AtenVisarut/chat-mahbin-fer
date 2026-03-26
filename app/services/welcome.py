"""
Welcome Service
Handles welcome messages and usage guides for new users
"""

import logging
from app.utils.line.text_messages import (
    get_welcome_text,
    get_usage_guide_text,
    get_product_catalog_text,
    get_help_menu_text
)

logger = logging.getLogger(__name__)


def get_welcome_message() -> str:
    """
    Create welcome message for new users (follow event)
    Returns text message string
    """
    return get_welcome_text()


def get_usage_guide() -> str:
    """
    Create comprehensive usage guide message
    Returns text message string
    """
    return get_usage_guide_text()




def get_product_catalog_message() -> str:
    """
    Create product catalog message
    Returns text message string
    """
    return get_product_catalog_text()


def get_help_menu() -> str:
    """
    Create help menu message
    Returns text message string
    """
    return get_help_menu_text()
