import os
import json
from typing import Dict, Any
from google.adk.agents.llm_agent import LlmAgent 
from dotenv import load_dotenv


import sys
project_root_di = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_di not in sys.path:
    sys.path.insert(0, project_root_di)


from document_parser import process_raw_document_to_json
from database_manager import store_invoice_data, store_po_data


if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (DataIngestionAgent): GOOGLE_API_KEY not set. LLM for this agent will fail.")

def _ingest_and_store_document_tool(raw_document_file_path: str, document_type: str) -> dict:
    """
    TOOL for DataIngestionAgent: Extracts data from a document file and stores it.
    Returns a dictionary containing the status, message, and key extracted information.
    """
    print(f"DATA_INGESTION_TOOL: Processing file='{raw_document_file_path}', type='{document_type}'")

    if document_type.lower() not in ["invoice", "purchase_order"]:
        return {"status": "error", "error_message": "Invalid document_type. Must be 'invoice' or 'purchase_order'."}

    extraction_result = process_raw_document_to_json(raw_document_file_path, document_type)

    if extraction_result.get("status") != "success":
        return { # Return the full error from parser
            "status": "error",
            "error_message": f"Data extraction failed: {extraction_result.get('error_message')}",
            "details": extraction_result 
        }

    doc_data = extraction_result.get("data")
    if not doc_data:
        return {"status": "error", "error_message": "Extraction successful, but no 'data' field found."}
    
    doc_number_raw = doc_data.get("document_number")
    if not doc_number_raw:
        return {"status": "error", "error_message": "Document number missing from extracted data, cannot store."}
    
    doc_number = str(doc_number_raw).strip().upper()
    if not doc_number:
         return {"status": "error", "error_message": "Document number is empty after processing."}

    stored_successfully = False
    if document_type.lower() == "invoice":
        stored_successfully = store_invoice_data(doc_number, extraction_result)
    elif document_type.lower() == "purchase_order":
        stored_successfully = store_po_data(doc_number, extraction_result)

    if stored_successfully:
        # Return the full extraction result, as the orchestrator might need it.
        # The message can summarize.
        return {
            "status": "success",
            "message": f"{document_type.capitalize()} '{doc_number}' processed and stored successfully.",
            "full_extraction_result": extraction_result # Orchestrator might need this
        }
    else:
        return {
            "status": "error",
            "error_message": f"Failed to store {document_type} '{doc_number}' in DB.",
            "full_extraction_result": extraction_result # Still return extracted data
        }


root_agent = LlmAgent(
    name="data_ingestion_specialist_agent", # Use this name when Orchestrator calls
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description="Specialized agent for uploading raw documents (invoices, POs), extracting their data using advanced parsing, and storing them into the database.",
    instruction=(
        "You are a Data Ingestion Specialist. Your ONLY task is to process a single document file.\n"
        "1. You will be given a `raw_document_file_path` and a `document_type` ('invoice' or 'purchase_order') by the Orchestrator agent.\n"
        "2. Use your `_ingest_and_store_document_tool` with these arguments.\n"
        "3. Return the complete JSON result from the tool directly back to the Orchestrator.\n"
        "Do NOT ask clarifying questions. Execute the tool with the provided arguments immediately."
    ),
    tools=[
        _ingest_and_store_document_tool
    ]
)

