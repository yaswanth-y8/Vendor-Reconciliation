import os
import json
from typing import Dict, Any, Optional
from google.adk.agents.llm_agent import LlmAgent
from dotenv import load_dotenv


import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database_manager import get_invoice_by_number, get_po_by_number

from difflib import SequenceMatcher 
import re 

load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (ReconciliationProcessingAgent): GOOGLE_API_KEY not found. Agent will fail.")



def _compare_strings_fuzzy_local(s1: Optional[str], s2: Optional[str], threshold=0.8) -> bool:
    if s1 is None and s2 is None: return True
    if s1 is None or s2 is None: return False
    clean_s1 = re.sub(r'[^\w\s]', '', s1.lower().strip())
    clean_s2 = re.sub(r'[^\w\s]', '', s2.lower().strip())
    if not clean_s1 and not clean_s2: return True
    if not clean_s1 or not clean_s2: return False
    return SequenceMatcher(None, clean_s1, clean_s2).ratio() >= threshold

def _compare_amounts_local(amount1: Any, amount2: Any, tolerance=0.01) -> bool:
    try:
        amt1 = float(str(amount1).replace(',','')) if amount1 is not None else 0.0
        amt2 = float(str(amount2).replace(',','')) if amount2 is not None else 0.0
        return abs(amt1 - amt2) <= tolerance
    except (ValueError, TypeError): return False

def _perform_reconciliation_logic(invoice_data_full: Dict[str, Any], po_data_full: Dict[str, Any]) -> Dict[str, Any]:
    """
    Core reconciliation logic. Expects full extraction objects.
    (This is the same logic as _perform_reconciliation from previous agent.py)
    """
    print("RECON_AGENT_LOGIC: Performing comparison.")
    try:
        if invoice_data_full.get("status") != "success":
            return {"status": "error", "error_message": "Invoice data for reconciliation is not valid."}
        if po_data_full.get("status") != "success":
            return {"status": "error", "error_message": "PO data for reconciliation is not valid."}

        invoice_data = invoice_data_full.get("data", {})
        po_data = po_data_full.get("data", {})
        
        discrepancies = []
        matched_fields = []

        inv_ref_po_num_raw = invoice_data.get("related_po_number") 
        inv_ref_po_num = inv_ref_po_num_raw.strip().upper() if inv_ref_po_num_raw and isinstance(inv_ref_po_num_raw, str) else None
        actual_po_num_raw = po_data.get("document_number")
        actual_po_num = actual_po_num_raw.strip().upper() if actual_po_num_raw and isinstance(actual_po_num_raw, str) else None

        if inv_ref_po_num and actual_po_num and inv_ref_po_num == actual_po_num:
            matched_fields.append("po_number_reference_match")
        elif actual_po_num and inv_ref_po_num: 
            discrepancies.append(f"PO Number Mismatch on Invoice: Invoice refs PO '{inv_ref_po_num}', reconciled PO is '{actual_po_num}'.")
        elif actual_po_num and not inv_ref_po_num : 
             discrepancies.append(f"Missing PO Reference on Invoice for PO '{actual_po_num}'.")
        elif not actual_po_num:
             discrepancies.append("Critical: Actual PO number missing from PO data.")

        inv_vendor = invoice_data.get("vendor_name") 
        po_vendor = po_data.get("vendor_name")
        if _compare_strings_fuzzy_local(inv_vendor, po_vendor): 
            matched_fields.append("vendor_name")
        else:
            discrepancies.append(f"Vendor Mismatch: Invoice='{inv_vendor or 'N/A'}' vs PO='{po_vendor or 'N/A'}'")

        inv_amount = invoice_data.get("total_amount")
        po_amount = po_data.get("total_amount")
        if _compare_amounts_local(inv_amount, po_amount):
            matched_fields.append("total_amount")
        else:
            discrepancies.append(f"Total Amount Mismatch: Invoice=${float(inv_amount or 0):.2f} vs PO=${float(po_amount or 0):.2f}")
            
        inv_items = invoice_data.get("line_items", [])
        po_items = po_data.get("line_items", [])
        if len(inv_items) == len(po_items) and (len(inv_items) > 0 or (len(inv_items)==0 and len(po_items)==0)):
            matched_fields.append("line_items_count")
        else:
            discrepancies.append(f"Line Item Count Mismatch: Invoice={len(inv_items)} vs PO={len(po_items)}")

        total_key_fields = 4 
        if not inv_items and not po_items: total_key_fields = 3 
        match_percentage = (len(matched_fields) / total_key_fields * 100) if total_key_fields > 0 else 0

        status_reco = "REJECTED" # Default
        if not discrepancies: status_reco = "APPROVED"
        elif "po_number_reference_match" not in matched_fields and inv_ref_po_num and actual_po_num and inv_ref_po_num != actual_po_num: status_reco = "REJECTED"
        elif not actual_po_num: status_reco = "REJECTED"
        elif match_percentage >= 75: status_reco = "NEEDS_REVIEW"
        
        recommendation = "Default recommendation: Review details."
        if status_reco == "APPROVED": recommendation = "Invoice and PO appear to match."
        elif status_reco == "REJECTED": recommendation = "Significant discrepancies or critical mismatch found."
        elif status_reco == "NEEDS_REVIEW": recommendation = f"High match ({match_percentage:.1f}%) but with discrepancies."
            
        inv_conf = float(invoice_data.get("confidence_score", 0.5))
        po_conf = float(po_data.get("confidence_score", 0.5))
        overall_confidence_score = ((inv_conf + po_conf) / 2 * 0.5) + ((match_percentage / 100) * 0.5)

        return {
            "status": "success", 
            "reconciliation_result": {
                "approval_status": status_reco, "match_percentage": round(match_percentage, 1),
                "confidence_score": round(overall_confidence_score, 2), "matched_fields": matched_fields,
                "discrepancies": discrepancies, "recommendation": recommendation,
                "summary": { "invoice_number": invoice_data.get("document_number"), "po_number": po_data.get("document_number"),
                             "invoice_total": inv_amount, "po_total": po_amount }
            }
        }
    except Exception as e:
        import traceback
        print(f"ERROR in _perform_reconciliation_logic: {e}\n{traceback.format_exc()}")
        return {"status": "error", "error_message": f"Reconciliation logic error: {str(e)}"}


def _reconcile_from_db_by_numbers_tool(invoice_number: str, po_number: str) -> dict:
    """
    TOOL: Fetches an invoice and a PO from the database by their numbers,
    then performs reconciliation between them.
    """
    print(f"RECON_AGENT_TOOL: _reconcile_from_db_by_numbers_tool called for Invoice: '{invoice_number}', PO: '{po_number}'")
    
    invoice_data_full = get_invoice_by_number(invoice_number)
    if not invoice_data_full:
        return {"status": "error", "error_message": f"Invoice '{invoice_number}' not found in database."}
    if invoice_data_full.get("status") != "success": # Check if the stored data itself indicates prior error
        return {"status": "error", "error_message": f"Stored invoice '{invoice_number}' has an error status: {invoice_data_full.get('error_message', 'Unknown stored error')}"}


    po_data_full = get_po_by_number(po_number)
    if not po_data_full:
        return {"status": "error", "error_message": f"Purchase Order '{po_number}' not found in database."}
    if po_data_full.get("status") != "success":
        return {"status": "error", "error_message": f"Stored PO '{po_number}' has an error status: {po_data_full.get('error_message', 'Unknown stored error')}"}

    return _perform_reconciliation_logic(invoice_data_full, po_data_full)

def _reconcile_with_provided_data_tool(invoice_data_json_str: str, po_data_json_str: str) -> dict:
    """
    TOOL: Performs reconciliation given JSON strings of pre-extracted invoice and PO data.
    The JSON strings are expected to be the full output structure from an extraction step.
    """
    print(f"RECON_AGENT_TOOL: _reconcile_with_provided_data_tool called.")
    try:
        invoice_data_full = json.loads(invoice_data_json_str)
        po_data_full = json.loads(po_data_json_str)
    except json.JSONDecodeError as e:
        return {"status": "error", "error_message": f"Invalid JSON input for reconciliation: {str(e)}"}

    return _perform_reconciliation_logic(invoice_data_full, po_data_full)


root_agent = LlmAgent(
    name="reconciliation_specialist_agent",
    model=os.getenv("MODEL_NAME", "gemini-1.5-flash-latest"),
    description="Specialized agent for comparing invoice and purchase order data, either fetched from a database or provided directly, to identify discrepancies and determine a reconciliation status.",
    instruction=(
        "You are a Reconciliation Specialist. Your task is to compare an invoice with a purchase order.\n"
        "1. If you are given an `invoice_number` and a `po_number`, use the `_reconcile_from_db_by_numbers_tool` to fetch them from the database and reconcile.\n"
        "2. If you are given `invoice_data_json_str` and `po_data_json_str` (which are JSON strings of already extracted data), use the `_reconcile_with_provided_data_tool`.\n"
        "3. Report the full reconciliation result (status, approval_status, discrepancies, etc.) back.\n"
        "Do NOT ask for file paths. Assume data is either in the DB or provided as JSON strings."
    ),
    tools=[
        _reconcile_from_db_by_numbers_tool,
        _reconcile_with_provided_data_tool
    ]
)

