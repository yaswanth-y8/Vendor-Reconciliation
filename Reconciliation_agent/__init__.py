"""
Vendor Reconciliation Agent

A Google ADK agent for automated vendor document reconciliation.
Extracts data from invoices and receipts and performs automated 
matching to approve or flag discrepancies.
"""

from .agent import root_agent



# Export the main agent
__all__ = ["root_agent"]


SUPPORTED_DOCUMENT_TYPES = ["invoice", "purchase_order"]

SUPPORTED_FILE_FORMATS = [
    "application/pdf",
    "image/jpeg", 
    "image/png",
    "image/tiff"
]

RECONCILIATION_STATUSES = ["APPROVED", "NEEDS_REVIEW", "REJECTED"]




