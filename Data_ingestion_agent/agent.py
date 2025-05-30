import os
import json
from typing import Dict, Any
from google.adk.agents.llm_agent import LlmAgent
from dotenv import load_dotenv


import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from document_parser import process_raw_document_to_json
from database_manager import store_invoice_data, store_po_data

load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (DataIngestionAgent): GOOGLE_API_KEY not found. Agent will fail.")

def _process_and_store_document_tool(raw_document_file_path: str, document_type: str) -> dict:
    """
    TOOL: Extracts data from a given document file path using Gemini,
    then stores the structured data in the database.
    Returns the full extraction result which includes status and data.
    """
    print(f"DATA_INGESTION_AGENT_TOOL: _process_and_store_document_tool called for "
          f"file='{raw_document_file_path}', type='{document_type}'")

    if document_type.lower() not in ["invoice", "purchase_order"]:
        return {"status": "error", "error_message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}

   
    extraction_result = process_raw_document_to_json(raw_document_file_path, document_type)

    if extraction_result.get("status") != "success":
        return {
            "status": "error",
            "error_message": f"Data extraction failed: {extraction_result.get('error_message')}",
            "extraction_details": extraction_result # Pass along original extraction error
        }

    # Step 2: Store the successfully extracted data
    doc_data = extraction_result.get("data")
    if not doc_data:
        return {"status": "error", "error_message": "Extraction successful, but no 'data' field found to store."}
    
    doc_number_raw = doc_data.get("document_number")
    if not doc_number_raw:
        return {"status": "error", "error_message": "Document number missing from extracted data, cannot store."}
    
    doc_number = str(doc_number_raw).strip().upper()
    if not doc_number:
         return {"status": "error", "error_message": "Document number is empty after processing, cannot store."}


    stored_successfully = False
    if document_type.lower() == "invoice":
        stored_successfully = store_invoice_data(doc_number, extraction_result)
    elif document_type.lower() == "purchase_order":
        stored_successfully = store_po_data(doc_number, extraction_result)

    if stored_successfully:
        return {
            "status": "success",
            "message": f"{document_type.capitalize()} '{doc_number}' processed and stored successfully.",
            "document_number": doc_number,
            "stored_data_summary": { 
                "vendor_name": doc_data.get("vendor_name"),
                "date": doc_data.get("date"),
                "total_amount": doc_data.get("total_amount")
            }
        }
    else:
        return {
            "status": "error",
            "error_message": f"Failed to store {document_type} '{doc_number}' in DB.",
            "extracted_data_preview": doc_data 
        }

root_agent = LlmAgent(
    name="data_ingestion_specialist_agent",
    model=os.getenv("MODEL_NAME", "gemini-1.5-flash-latest"),
    description="Specialized agent for uploading raw documents (invoices, POs), extracting their data using advanced parsing, and storing them into the database.",
    instruction=(
        "You are a Data Ingestion Specialist. Your ONLY task is to process a single document file provided by the Orchestrator/User.\n"
        "1. You will be given a `raw_document_file_path` and a `document_type` ('invoice' or 'purchase_order').\n"
        "2. Use the `_process_and_store_document_tool` to perform extraction and storage.\n"
        "3. Report the outcome (success with document number, or error message) back.\n"
        "Do NOT ask clarifying questions. Assume the file path and type are correct and proceed directly with the tool call."
    ),
    tools=[
        _process_and_store_document_tool
    ]
)
