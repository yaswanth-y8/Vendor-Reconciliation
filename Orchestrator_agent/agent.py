# orchestrator_agent/agent.py
import os
import json
from typing import Dict, Any, Optional
from google.adk.agents.llm_agent import LlmAgent 
from dotenv import load_dotenv
import traceback


import sys
project_root_orch = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_orch not in sys.path: sys.path.insert(0, project_root_orch)

from Data_ingestion_agent.agent import _ingest_and_store_document_tool as ingest_tool_function
from Reconciliation_agent.agent import _perform_reconciliation_logic_tool as reconcile_tool_function
from database_manager import get_invoice_by_number, get_po_by_number, get_invoice_by_related_po

if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (OrchestratorAgent): GOOGLE_API_KEY not set. LLM will fail.")



def _process_reconciliation_starting_with_po(
    
    po_number_input: Optional[str] = None, 
    new_po_file_path: Optional[str] = None,
    new_invoice_file_path: Optional[str] = None,
    specific_invoice_number_to_find_in_db: Optional[str] = None 
    ) -> dict:
    """
    TOOL (Orchestrator): Drives reconciliation.
    - If new_po_file_path is given, it's prioritized for PO data. po_number_input can be used as a reference/target.
    - If only po_number_input is given, it's fetched from DB.
    - Then, it attempts to get invoice data (specific_invoice_number_to_find_in_db, then related from PO, then new_invoice_file_path).
    """
    print(f"ORCHESTRATOR_TOOL_V3: Called with: "
          f"po_num_in='{po_number_input}', new_po_file='{new_po_file_path}', "
          f"new_inv_file='{new_invoice_file_path}', spec_inv_num='{specific_invoice_number_to_find_in_db}'")

    final_report: Dict[str, Any] = {"steps_taken": [], "overall_status": "pending"}
    po_extraction_obj: Optional[Dict[str, Any]] = None
    invoice_extraction_obj: Optional[Dict[str, Any]] = None
    
    
    effective_po_number_for_processing = po_number_input.strip().upper() if po_number_input else None


    step_msg_po = ""
    if new_po_file_path:
        step_msg_po = f"Step 1: Processing new PO file: '{new_po_file_path}'."
        ingestion_result = ingest_tool_function(raw_document_file_path=new_po_file_path, document_type="purchase_order")
        final_report["po_acquisition"] = ingestion_result
        if ingestion_result.get("status") == "success":
            po_extraction_obj = ingestion_result.get("full_extraction_result")
            extracted_po_num = po_extraction_obj.get("data",{}).get("document_number","").strip().upper()
            if not extracted_po_num: 
                 final_report["overall_status"] = "error"
                 final_report["error_message"] = "Failed to extract document number from the provided new PO file."
                 print(f"ORCHESTRATOR_TOOL_V3: {step_msg_po}\n  {final_report['error_message']}")
                 final_report["steps_taken"].append(step_msg_po)
                 return final_report
            
            if effective_po_number_for_processing and extracted_po_num != effective_po_number_for_processing:
                step_msg_po += f" Note: User might have mentioned PO '{effective_po_number_for_processing}', but file extracted as '{extracted_po_num}'. Using extracted number '{extracted_po_num}'."
            effective_po_number_for_processing = extracted_po_num # Prioritize number from actual document
            step_msg_po += f" Successfully ingested new PO as '{effective_po_number_for_processing}'."
        else: # Ingestion of new PO file failed
            final_report["overall_status"] = "error"
            final_report["error_message"] = f"Failed to ingest new PO file '{new_po_file_path}': {ingestion_result.get('error_message')}"
            print(f"ORCHESTRATOR_TOOL_V3: {step_msg_po}\n  {final_report['error_message']}")
            final_report["steps_taken"].append(step_msg_po)
            return final_report
    elif effective_po_number_for_processing: 
        step_msg_po = f"Step 1: Attempting to retrieve existing PO '{effective_po_number_for_processing}' from database."
        po_extraction_obj = get_po_by_number(effective_po_number_for_processing)
        if po_extraction_obj:
            step_msg_po += f" Found existing PO '{effective_po_number_for_processing}' in database."
            final_report["po_acquisition"] = {"status": "success_from_db", "source": "database", 
                                              "document_number": po_extraction_obj.get("data",{}).get("document_number")}
        else: # PO not found in DB, and no new file path was given in this call
            step_msg_po += f" PO '{effective_po_number_for_processing}' not found in database. A new PO file for this number is needed."
            final_report["overall_status"] = "po_not_found_needs_file"
            final_report["message_to_user"] = step_msg_po
            final_report["required_next_input"] = "new_po_file_path" # LLM should ask for this
            final_report["context_po_number"] = effective_po_number_for_processing # For LLM to use in follow-up
            print(f"ORCHESTRATOR_TOOL_V3: {step_msg_po}")
            final_report["steps_taken"].append(step_msg_po)
            return final_report
    else: # No po_number_input and no new_po_file_path
        final_report["overall_status"] = "error"
        final_report["error_message"] = "No PO information (neither number for DB lookup nor new file path) was provided."
        final_report["steps_taken"].append("Step 1: PO acquisition failed due to missing input.")
        return final_report
        
    final_report["steps_taken"].append(step_msg_po)
    print(f"ORCHESTRATOR_TOOL_V3: {step_msg_po}")

    # Safeguard: PO data must be valid to proceed
    if not po_extraction_obj or po_extraction_obj.get("status") != "success":
        final_report["overall_status"] = "error"
        final_report["error_message"] = final_report.get("po_acquisition",{}).get("error_message", "Valid PO data could not be obtained.")
        return final_report
    if not effective_po_number_for_processing: # Should be set if po_extraction_obj is valid
        effective_po_number_for_processing = po_extraction_obj.get("data",{}).get("document_number","").strip().upper()
        if not effective_po_number_for_processing:
            final_report["overall_status"] = "error"; final_report["error_message"] = "Critical: PO number missing after PO processing."
            return final_report


    # --- Step 2: Secure the Invoice data ---
    step_msg_inv = ""
    if new_invoice_file_path:
        step_msg_inv = f"Step 2: Processing provided new invoice file: '{new_invoice_file_path}' (intended for PO '{effective_po_number_for_processing}')."
        ingestion_result = ingest_tool_function(raw_document_file_path=new_invoice_file_path, document_type="invoice")
        final_report["invoice_acquisition"] = ingestion_result
        if ingestion_result.get("status") == "success":
            invoice_extraction_obj = ingestion_result.get("full_extraction_result")
            # Optional: Cross-check if new invoice actually relates to the effective_po_number_for_processing
            extracted_related_po = invoice_extraction_obj.get("data",{}).get("related_po_number","").strip().upper()
            if extracted_related_po and extracted_related_po != effective_po_number_for_processing:
                step_msg_inv += (f" Warning: New invoice processed. It references PO '{extracted_related_po}', "
                                 f"but reconciliation is against PO '{effective_po_number_for_processing}'.")
            elif not extracted_related_po:
                 step_msg_inv += (f" Note: New invoice processed. It does not explicitly reference PO '{effective_po_number_for_processing}'. "
                                  "Reconciliation will proceed based on user intent.")
            step_msg_inv += " Successfully ingested new invoice."
        else: # Failed to ingest the provided new invoice file
            final_report["overall_status"] = "error"
            final_report["error_message"] = f"Failed to ingest new invoice file '{new_invoice_file_path}': {ingestion_result.get('error_message')}"
            print(f"ORCHESTRATOR_TOOL_V3: {step_msg_inv}\n  {final_report['error_message']}")
            final_report["steps_taken"].append(step_msg_inv)
            return final_report
            
    elif specific_invoice_number_to_find_in_db: # User specified an existing invoice number
        inv_to_find = specific_invoice_number_to_find_in_db.strip().upper()
        step_msg_inv = f"Step 2: Attempting to retrieve specific existing Invoice '{inv_to_find}' from database (for PO '{effective_po_number_for_processing}')."
        invoice_extraction_obj = get_invoice_by_number(inv_to_find)
        if invoice_extraction_obj:
            related_po_on_found_inv = invoice_extraction_obj.get("data",{}).get("related_po_number","").strip().upper()
            if related_po_on_found_inv and related_po_on_found_inv != effective_po_number_for_processing:
                step_msg_inv += (f" Warning: Found specified Invoice '{inv_to_find}', but it references PO '{related_po_on_found_inv}' "
                                 f"instead of target PO '{effective_po_number_for_processing}'. Reconciliation might highlight this.")
            final_report["invoice_acquisition"] = {"status": "success_from_db_specific", "source": "database", "document_number": inv_to_find}
        else: 
             step_msg_inv += f" Specified Invoice '{inv_to_find}' not found in database."
             final_report["overall_status"] = "invoice_not_found_needs_file" # Specific status
             final_report["message_to_user"] = step_msg_inv
             final_report["required_next_input"] = "new_invoice_file_path"
             final_report["context_po_number"] = effective_po_number_for_processing # For LLM to use
             print(f"ORCHESTRATOR_TOOL_V3: {step_msg_inv}")
             final_report["steps_taken"].append(step_msg_inv)
             return final_report
    
    else: # No new_invoice_file_path and no specific_invoice_number_db, so search DB for related invoice
        step_msg_inv = f"Step 2: Attempting to find an invoice in database related to PO '{effective_po_number_for_processing}'."
        invoice_extraction_obj = get_invoice_by_related_po(effective_po_number_for_processing)
        if invoice_extraction_obj:
            inv_num_found = invoice_extraction_obj.get('data',{}).get('document_number', 'UNKNOWN')
            step_msg_inv += f" Found invoice '{inv_num_found}' related to PO '{effective_po_number_for_processing}' in database."
            final_report["invoice_acquisition"] = {"status": "success_from_db_related_to_po", "source": "database", "document_number": inv_num_found}
        else: # No related invoice found in DB, and no new file path given in *this* call
            step_msg_inv += (f" No invoice related to PO '{effective_po_number_for_processing}' found in database. "
                             f"A new invoice file is needed for reconciliation.")
            final_report["overall_status"] = "po_secured_invoice_needed" # Specific status
            final_report["message_to_user"] = step_msg_inv
            final_report["required_next_input"] = "new_invoice_file_path"
            final_report["context_po_number"] = effective_po_number_for_processing
            final_report["po_data_processed_summary"] = po_extraction_obj.get("data", {}).get("document_number","N/A") # po_extraction_obj is valid here
            print(f"ORCHESTRATOR_TOOL_V3: {step_msg_inv}")
            final_report["steps_taken"].append(step_msg_inv)
            return final_report

    final_report["steps_taken"].append(step_msg_inv)
    print(f"ORCHESTRATOR_TOOL_V3: {step_msg_inv}")

    # Safeguards
    if not invoice_extraction_obj or invoice_extraction_obj.get("status") != "success":
        final_report["overall_status"] = "error"
        final_report["error_message"] = final_report.get("invoice_acquisition",{}).get("error_message","Valid Invoice data could not be obtained.")
        return final_report
    if not po_extraction_obj or po_extraction_obj.get("status") != "success": # Should be fine by now
        final_report["overall_status"] = "error"; final_report["error_message"] = "Valid PO data not available for reconciliation."
        return final_report

    # --- Step 3: Perform Reconciliation ---
    step_msg_reco = "Step 3: Both PO and Invoice data are available. Performing reconciliation."
    final_report["steps_taken"].append(step_msg_reco)
    print(f"ORCHESTRATOR_TOOL_V3: {step_msg_reco}")
    
    reconciliation_response_str = _delegate_to_reconciliation_agent_tool_sync_placeholder(
        invoice_data_json_str=json.dumps(invoice_extraction_obj),
        po_data_json_str=json.dumps(po_extraction_obj)
    )
    reconciliation_call_outcome = json.loads(reconciliation_response_str)
    final_report["reconciliation_report"] = reconciliation_call_outcome

    if reconciliation_call_outcome.get("status") == "success":
        final_report["overall_status"] = "success_reconciled"
        final_report["message"] = "Reconciliation process complete."
    else:
        final_report["overall_status"] = "error_in_reconciliation"
        final_report["error_message"] = f"Reconciliation failed: {reconciliation_call_outcome.get('error_message')}"
            
    return final_report


# Placeholder sync versions (same as before)
def _delegate_to_data_ingestion_agent_tool_sync_placeholder(raw_document_file_path: str, document_type: str) -> str:
    try: result_dict = ingest_tool_function(raw_document_file_path=raw_document_file_path, document_type=document_type)
    except Exception as e: result_dict = {"status": "error", "error_message": f"Delegate placeholder (ingestion) exception: {str(e)}"}
    return json.dumps(result_dict)

def _delegate_to_reconciliation_agent_tool_sync_placeholder(invoice_data_json_str: str, po_data_json_str: str) -> str:
    try: result_dict = reconcile_tool_function(invoice_data_json_str=invoice_data_json_str, po_data_json_str=po_data_json_str)
    except Exception as e: result_dict = {"status": "error", "error_message": f"Delegate placeholder (reconciliation) exception: {str(e)}"}
    return json.dumps(result_dict)


# Orchestrator LlmAgent instance
root_agent = LlmAgent(
    name="interactive_reconciliation_orchestrator", 
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=(
        "Orchestrator AI agent for vendor reconciliation. Guides user through providing PO information, "
        "then invoice information if needed, and coordinates document processing and reconciliation."
    ),
    instruction=(
        "You are the Vendor Reconciliation Orchestrator. Your primary goal is to reconcile an invoice with a Purchase Order (PO).\n\n"
        "**Your Main Tool:** `_process_reconciliation_starting_with_po`.\n\n"
        "**Interaction Flow & Logic:**\n"
        "1.  **Start:** Greet the user. Ask: 'Hello! Are you working with **new documents** you'd like to upload, or do you want to reconcile based on an **existing Purchase Order (PO) number** already in our system?'\n"
        "2.  **Handle User's Initial Choice:**\n"
        "    A.  If user indicates **'Existing PO'** or provides a PO number directly:\n"
        "        - Get the `po_number_input` from the user.\n"
        "        - Call `_process_reconciliation_starting_with_po` with just this `po_number_input`.\n"
        "    B.  If user indicates **'New Documents'** (implying new PO and likely new Invoice):\n"
        "        - Ask for the `new_po_file_path` (full local path to the new PO document).\n"
        "        - (Optional but good: you can ask for a target PO number they have in mind for this file, or let the tool extract it. For the tool, `po_number_input` can be omitted if `new_po_file_path` is given and the number is to be extracted from the file itself.)\n"
        "        - Then, ask for the `new_invoice_file_path` (full local path for the corresponding new invoice).\n"
        "        - Call `_process_reconciliation_starting_with_po` with `new_po_file_path` and `new_invoice_file_path` (and `po_number_input` if you asked for a target PO number for the new PO file).\n"
        "3.  **Interpret Tool Response & Follow Up (Iterative Process):**\n"
        "    The `_process_reconciliation_starting_with_po` tool will return a JSON response. Examine its `overall_status` and `context_po_number` (if present).\n"
        "    a.  If tool response has `overall_status: \"po_not_found_needs_file\"`:\n"
        "        - The tool provides `context_po_number`. Ask the user: 'PO \"[Value from tool's context_po_number]\" was not found. Please provide the full local file path for this new PO document.'\n"
        "        - Once user provides `new_po_file_path`: Call `_process_reconciliation_starting_with_po` tool AGAIN. Pass the `po_number_input` (which is `context_po_number` from previous tool response) AND the newly provided `new_po_file_path`.\n"
        "    b.  If tool response has `overall_status: \"po_secured_invoice_needed\"` (PO found/ingested, but no related invoice found in DB automatically):\n"
        "        - The tool provides `context_po_number`. Ask the user: 'PO \"[Value from tool's context_po_number]\" has been processed/found. However, no related invoice was found in the database. Do you have a new invoice file to upload for this PO? If yes, please provide its full local file path.'\n"
        "        - Once user provides `new_invoice_file_path`: Call `_process_reconciliation_starting_with_po` tool AGAIN. Pass the `po_number_input` (which is `context_po_number` from previous tool response) AND the newly provided `new_invoice_file_path`.\n"
        "    c.  If tool response indicates `overall_status: \"success_reconciled\"` or any other final status (e.g., `error`, `partial_success_..._only`):\n"
        "        - Present the full results (including `steps_taken`, `message_to_user` if any, and `reconciliation_report` if present from the tool's JSON response) clearly to the user.\n"
        "4.  **Clarity for File Paths:** Always request FULL LOCAL FILE PATHS.\n\n"
        "**Goal:** Guide the user to provide information step-by-step so you can eventually call `_process_reconciliation_starting_with_po` with enough arguments for it to either complete the reconciliation or return a status asking for the next specific piece of missing information (which you then ask the user for)."
    ),
    tools=[
        _process_reconciliation_starting_with_po
    ]
)

