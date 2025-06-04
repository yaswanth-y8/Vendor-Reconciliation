import os
import json
from typing import Dict, Any, Optional, List
from google.adk.agents.llm_agent import LlmAgent
from dotenv import load_dotenv 
import traceback


import sys
project_root_db_agent = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_db_agent not in sys.path: sys.path.insert(0, project_root_db_agent)

# Import your database query functions
try:
    from database_manager import (
        get_documents_count_by_date_range,
        get_documents_count_by_vendor,
        get_total_amount_by_vendor,
        get_documents_by_vendor,
        get_documents_by_date_range
    )
    print("INFO (DbQueryAgent): Successfully imported database_manager functions.")
except ImportError as e:
    print(f"ERROR (DbQueryAgent): Could not import database_manager functions: {e}")
    def get_documents_count_by_date_range(*args, **kwargs): return {"error": "database_manager not available"}
    def get_documents_count_by_vendor(*args, **kwargs): return {"error": "database_manager not available"}
    def get_total_amount_by_vendor(*args, **kwargs): return {"error": "database_manager not available"}
    def get_documents_by_vendor(*args, **kwargs): return {"error": "database_manager not available"}
    def get_documents_by_date_range(*args, **kwargs): return {"error": "database_manager not available"}


DB_QUERY_AGENT_NAME = "database_query_agent"
DB_QUERY_AGENT_DESCRIPTION = "Agent to query invoice and purchase order database using provided tools."

print(f"DB_QUERY_AGENT: Name='{DB_QUERY_AGENT_NAME}', Desc='{DB_QUERY_AGENT_DESCRIPTION}'")



def _get_doc_count_date_range_tool(document_type: str, start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Gets the count of documents (invoices or purchase_orders) within a specified date range.
    Dates should be in YYYY-MM-DD format.
    document_type must be 'invoice' or 'purchase_order'.
    """
    print(f"DB_QUERY_TOOL: _get_doc_count_date_range_tool called with type='{document_type}', start='{start_date}', end='{end_date}'")
    if document_type.lower() not in ["invoice", "purchase_order"]: 
        return {"status": "error", "message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}
    try:
        # TODO: 
        count = get_documents_count_by_date_range(document_type.lower(), start_date, end_date)
        return {"status": "success", "document_type": document_type, "start_date": start_date, "end_date": end_date, "count": count}
    except Exception as e:
        print(f"ERROR in _get_doc_count_date_range_tool: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": f"Error querying database: {str(e)}"}

def _get_doc_count_vendor_tool(document_type: str, vendor_name: str) -> Dict[str, Any]:
    """
    Gets the count of documents (invoices or purchase_orders) for a specific vendor name.
    document_type must be 'invoice' or 'purchase_order'.
    """
    print(f"DB_QUERY_TOOL: _get_doc_count_vendor_tool called with type='{document_type}', vendor='{vendor_name}'")
    if document_type.lower() not in ["invoice", "purchase_order"]:
        return {"status": "error", "message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}
    try:
        count = get_documents_count_by_vendor(document_type.lower(), vendor_name)
        return {"status": "success", "document_type": document_type, "vendor_name": vendor_name, "count": count}
    except Exception as e:
        print(f"ERROR in _get_doc_count_vendor_tool: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": f"Error querying database: {str(e)}"}

def _get_total_amount_vendor_tool(document_type: str, vendor_name: str) -> Dict[str, Any]:
    """
    Gets the total amount of documents (invoices or purchase_orders) for a specific vendor name.
    document_type must be 'invoice' or 'purchase_order'.
    """
    print(f"DB_QUERY_TOOL: _get_total_amount_vendor_tool called with type='{document_type}', vendor='{vendor_name}'")
    if document_type.lower() not in ["invoice", "purchase_order"]:
        return {"status": "error", "message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}
    try:
        total_amount = get_total_amount_by_vendor(document_type.lower(), vendor_name)
        return {"status": "success", "document_type": document_type, "vendor_name": vendor_name, "total_amount": f"{total_amount:.2f}"} # Format as string
    except Exception as e:
        print(f"ERROR in _get_total_amount_vendor_tool: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": f"Error querying database: {str(e)}"}

def _list_documents_vendor_tool(document_type: str, vendor_name: str, limit: int = 5) -> Dict[str, Any]:
    """
    Lists documents (invoices or purchase_orders) for a specific vendor name, up to a limit.
    document_type must be 'invoice' or 'purchase_order'.
    """
    print(f"DB_QUERY_TOOL: _list_documents_vendor_tool called with type='{document_type}', vendor='{vendor_name}', limit={limit}")
    if document_type.lower() not in ["invoice", "purchase_order"]:
        return {"status": "error", "message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}
    try:
        documents = get_documents_by_vendor(document_type.lower(), vendor_name)
        return {"status": "success", "document_type": document_type, "vendor_name": vendor_name, "documents_found": len(documents), "documents_preview": documents[:limit]}
    except Exception as e:
        print(f"ERROR in _list_documents_vendor_tool: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": f"Error querying database: {str(e)}"}

def _list_documents_date_range_tool(document_type: str, start_date: str, end_date: str, limit: int = 5) -> Dict[str, Any]:
    """
    Lists documents (invoices or purchase_orders) within a date range, up to a limit.
    Dates should be in YYYY-MM-DD format.
    document_type must be 'invoice' or 'purchase_order'.
    """
    print(f"DB_QUERY_TOOL: _list_documents_date_range_tool called with type='{document_type}', start='{start_date}', end='{end_date}', limit={limit}")
    if document_type.lower() not in ["invoice", "purchase_order"]:
        return {"status": "error", "message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}
    try:
        documents = get_documents_by_date_range(document_type.lower(), start_date, end_date)
        return {"status": "success", "document_type": document_type, "start_date": start_date, "end_date": end_date, "documents_found": len(documents), "documents_preview": documents[:limit]}
    except Exception as e:
        print(f"ERROR in _list_documents_date_range_tool: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": f"Error querying database: {str(e)}"}



db_query_llm_agent = LlmAgent(
    name=DB_QUERY_AGENT_NAME, 
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=DB_QUERY_AGENT_DESCRIPTION, 
    instruction=(
        "You are a Database Query Assistant. Your role is to help users get information about invoices and purchase orders from a database. "
        "You have several tools to query the database based on user requests. "
        "Always clarify the 'document_type' ('invoice' or 'purchase_order') if not specified by the user for queries that require it. "
        "If a user provides a vague date like 'last month' or 'this year', ask for specific start and end dates in YYYY-MM-DD format.\n\n"
        "Available tools and their required parameters:\n"
        "- `_get_doc_count_date_range_tool`: Gets count. Requires: `document_type`, `start_date` (YYYY-MM-DD), `end_date` (YYYY-MM-DD).\n"
        "- `_get_doc_count_vendor_tool`: Gets count for vendor. Requires: `document_type`, `vendor_name`.\n"
        "- `_get_total_amount_vendor_tool`: Gets total amount for vendor. Requires: `document_type`, `vendor_name`.\n"
        "- `_list_documents_vendor_tool`: Lists documents for vendor. Requires: `document_type`, `vendor_name`. Optional: `limit` (default 5).\n"
        "- `_list_documents_date_range_tool`: Lists documents in date range. Requires: `document_type`, `start_date`, `end_date`. Optional: `limit` (default 5).\n\n"
        "When a user asks a general question (e.g., 'invoices for Acme Corp'), first offer to provide a count or total amount. If they want more details, then offer to list some documents. "
        "Present results from tools clearly. If a tool returns an error, inform the user and state the error message."
    ),
    tools=[
        _get_doc_count_date_range_tool,
        _get_doc_count_vendor_tool,
        _get_total_amount_vendor_tool,
        _list_documents_vendor_tool,
        _list_documents_date_range_tool
    ]
)

root_agent = db_query_llm_agent