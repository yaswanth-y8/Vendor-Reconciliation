import os
import json
from typing import Dict, List, Any
from google.adk.agents.llm_agent import LlmAgent
from difflib import SequenceMatcher
import re
from datetime import datetime


from document_parser import process_raw_document_to_json 

from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")


def extract_document_data(raw_document_file_path: str, document_type: str) -> dict:
    """
    Extracts structured data from a raw document file (PDF/image) by calling
    the processing logic in document_parser.py.
    
    Args:
        raw_document_file_path (str): The path to the local raw document file 
                                      (e.g., "sample_raw_documents/invoice1.pdf").
        document_type (str): Expected type of document - "invoice" or "receipt".
        
    Returns:
        dict: Extracted document data in JSON format with status, matching the
              structure expected by downstream tools.
    """
    print(f"AGENT TOOL: extract_document_data called for raw file='{raw_document_file_path}', type='{document_type}'")
    
    extraction_result = process_raw_document_to_json(raw_document_file_path, document_type)
    
    return extraction_result


def reconcile_vendor_documents(invoice_data_json: str, receipt_data_json: str) -> dict:
    """Compares invoice and receipt data to determine if they match for vendor reconciliation."""
    try:
        invoice_full_extraction = json.loads(invoice_data_json)
        receipt_full_extraction = json.loads(receipt_data_json)

        if invoice_full_extraction.get("status") != "success":
            return {
                "status": "error",
                "error_message": f"Reconciliation cannot proceed due to invoice extraction error: {invoice_full_extraction.get('error_message', 'Unknown extraction error')}"
            }
        if receipt_full_extraction.get("status") != "success":
            return {
                "status": "error",
                "error_message": f"Reconciliation cannot proceed due to receipt extraction error: {receipt_full_extraction.get('error_message', 'Unknown extraction error')}"
            }

        invoice_data = invoice_full_extraction.get("data", {}) 
        receipt_data = receipt_full_extraction.get("data", {}) 

        matched_fields = []
        discrepancies = []
        
        invoice_vendor_raw = invoice_data.get("vendor_name")
        invoice_vendor = invoice_vendor_raw.strip() if invoice_vendor_raw else ""

        receipt_vendor_raw = receipt_data.get("vendor_name")
        receipt_vendor = receipt_vendor_raw.strip() if receipt_vendor_raw else ""
        
        if _compare_vendor_names(invoice_vendor, receipt_vendor):
            matched_fields.append("vendor_name")
        else:
            discrepancies.append(f"Vendor mismatch: Invoice='{invoice_vendor}' vs Receipt='{receipt_vendor}'")
        
        invoice_amount_raw = invoice_data.get("total_amount")
        invoice_amount = float(invoice_amount_raw) if invoice_amount_raw is not None else 0.0

        receipt_amount_raw = receipt_data.get("total_amount")
        receipt_amount = float(receipt_amount_raw) if receipt_amount_raw is not None else 0.0
        
        if _compare_amounts(invoice_amount, receipt_amount):
            matched_fields.append("total_amount")
        else:
            discrepancies.append(f"Amount mismatch: Invoice=${invoice_amount:.2f} vs Receipt=${receipt_amount:.2f}")
        
        invoice_date_raw = invoice_data.get("date")
        invoice_date_str = invoice_date_raw.strip() if invoice_date_raw else ""

        receipt_date_raw = receipt_data.get("date")
        receipt_date_str = receipt_date_raw.strip() if receipt_date_raw else ""
        
        if _compare_dates(invoice_date_str, receipt_date_str):
            matched_fields.append("date")
        else:
            discrepancies.append(f"Date mismatch: Invoice='{invoice_date_str}' vs Receipt='{receipt_date_str}'")
        
        invoice_items_count = len(invoice_data.get("line_items", []))
        receipt_items_count = len(receipt_data.get("line_items", []))
        
        if invoice_items_count == receipt_items_count:
            if invoice_items_count > 0 or receipt_items_count > 0 or (invoice_items_count == 0 and receipt_items_count == 0) :
                 matched_fields.append("line_items_count")
        else:
            discrepancies.append(f"Items count mismatch: Invoice={invoice_items_count} items vs Receipt={receipt_items_count} items")
        
        total_comparison_fields = 4
        match_percentage = (len(matched_fields) / total_comparison_fields * 100) if total_comparison_fields > 0 else 0
        
        if not discrepancies:
            status = "APPROVED"
            recommendation = "All key fields match. Approve for payment processing."
        elif match_percentage >= 75:
            status = "NEEDS_REVIEW"
            recommendation = f"High confidence match ({match_percentage:.1f}%) with minor discrepancies. Manual review recommended."
        elif match_percentage >= 50:
            status = "NEEDS_REVIEW"
            recommendation = f"Moderate match ({match_percentage:.1f}%) found. Requires careful manual review before approval."
        else:
            status = "REJECTED"
            recommendation = f"Low match confidence ({match_percentage:.1f}%). Significant discrepancies found. Investigate and resolve issues."
        
        inv_extraction_confidence = float(invoice_data.get("confidence_score", 0.3))
        rec_extraction_confidence = float(receipt_data.get("confidence_score", 0.3))
        overall_confidence_score = ((inv_extraction_confidence + rec_extraction_confidence) / 2 * 0.5) + \
                                   ((match_percentage / 100) * 0.5)
        
        return {
            "status": "success",
            "reconciliation_result": {
                "approval_status": status,
                "match_percentage": round(match_percentage, 1),
                "confidence_score": round(overall_confidence_score, 2),
                "matched_fields": matched_fields,
                "discrepancies": discrepancies,
                "recommendation": recommendation,
                "summary": {
                    "invoice_vendor": invoice_vendor,
                    "receipt_vendor": receipt_vendor,
                    "invoice_amount": invoice_amount,
                    "receipt_amount": receipt_amount,
                    "amount_difference": round(abs(invoice_amount - receipt_amount), 2)
                }
            }
        }
    except Exception as e:
        import traceback
        print(f"ERROR in reconcile_vendor_documents: {e}\n{traceback.format_exc()}")
        return {
            "status": "error",
            "error_message": f"Reconciliation logic failed unexpectedly: {str(e)}"
        }


def process_vendor_reconciliation_workflow(invoice_raw_file_path: str, receipt_raw_file_path: str) -> dict:
    """
    Complete vendor reconciliation workflow by processing raw document files,
    extracting data, and comparing them. 
    """
    try:
        workflow_start_time = datetime.now()
        print(f"Workflow starting for Invoice: {invoice_raw_file_path}, Receipt: {receipt_raw_file_path}")
        
        invoice_extraction = extract_document_data(invoice_raw_file_path, "invoice")
        if invoice_extraction.get("status") == "error": 
            return { 
                "status": "error", 
                "error_message": f"Invoice data extraction failed: {invoice_extraction.get('error_message', 'Unknown extraction error')}" 
            }
        
        receipt_extraction = extract_document_data(receipt_raw_file_path, "receipt")
        if receipt_extraction.get("status") == "error":
            return { 
                "status": "error", 
                "error_message": f"Receipt data extraction failed: {receipt_extraction.get('error_message', 'Unknown extraction error')}" 
            }
        
        
        if not invoice_extraction.get("data") or not receipt_extraction.get("data"):
             return {
                "status": "error",
                "error_message": "Extraction step did not return 'data' object for one or both documents."
            }

        reconciliation_result = reconcile_vendor_documents(
            json.dumps(invoice_extraction), 
            json.dumps(receipt_extraction)  
        )
        
        if reconciliation_result.get("status") == "error":
            return { 
                "status": "error", 
                "error_message": f"Reconciliation logic failed: {reconciliation_result.get('error_message', 'Unknown reconciliation error')}" 
            }
        
        processing_time = (datetime.now() - workflow_start_time).total_seconds()
        
        
        inv_doc_num = invoice_extraction.get("data", {}).get("document_number", "N/A")
        rec_doc_num = receipt_extraction.get("data", {}).get("document_number", "N/A")

        return {
            "status": "success",
            "workflow_results": {
                "processing_time_seconds": round(processing_time, 2),
                "invoice_data_source": invoice_raw_file_path,
                "receipt_data_source": receipt_raw_file_path,
                "invoice_extraction_summary": {
                    "status": invoice_extraction.get("status"), 
                    "data_preview_doc_number": inv_doc_num
                },
                "receipt_extraction_summary": {
                    "status": receipt_extraction.get("status"), 
                    "data_preview_doc_number": rec_doc_num
                },
                "reconciliation": reconciliation_result.get("reconciliation_result", {}), # Ensure key exists
                "final_decision": {
                    "status": reconciliation_result.get("reconciliation_result", {}).get("approval_status"),
                    "confidence": reconciliation_result.get("reconciliation_result", {}).get("confidence_score"),
                    "action_required": _get_action_required(reconciliation_result.get("reconciliation_result", {}).get("approval_status")),
                    "timestamp": datetime.now().isoformat()
                }
            }
        }
    except Exception as e:
        import traceback
        print(f"CRITICAL ERROR in process_vendor_reconciliation_workflow: {e}\n{traceback.format_exc()}")
        return { 
            "status": "error", 
            "error_message": f"Workflow execution failed unexpectedly: {str(e)}" 
        }

def _compare_vendor_names(name1: str, name2: str) -> bool:
    if not name1 and not name2: return True 
    if not name1 or not name2: return False
    clean_name1 = re.sub(r'[^\w\s]', '', name1.lower())
    clean_name2 = re.sub(r'[^\w\s]', '', name2.lower())
    if not clean_name1 and not clean_name2: return True
    if not clean_name1 or not clean_name2: return False
    return SequenceMatcher(None, clean_name1, clean_name2).ratio() > 0.8

def _compare_amounts(amount1: Any, amount2: Any) -> bool:
    try:
        amt1 = float(str(amount1).replace(',','')) if amount1 is not None else 0.0
        amt2 = float(str(amount2).replace(',','')) if amount2 is not None else 0.0
        return abs(amt1 - amt2) <= 0.01
    except (ValueError, TypeError): return False

def _compare_dates(date1_str: str, date2_str: str) -> bool:
    if not date1_str and not date2_str: return True
    if not date1_str or not date2_str: return False
    return date1_str == date2_str 

def _get_action_required(status: str) -> str:
    actions = {
        "APPROVED": "Proceed with payment processing",
        "NEEDS_REVIEW": "Manual review required before approval",
        "REJECTED": "Investigate discrepancies and resolve issues"
    }
    return actions.get(status, "Unknown status")


 
root_agent = LlmAgent(
    name="vendor_reconciliation_agent_raw_docs", 
    model=os.getenv("MODEL_NAME"), 
    description=(
        "AI agent for vendor reconciliation. Processes raw invoice/receipt files (PDF/image), "
        "extracts data using an open-source parser, compares them, and provides approval decisions."
    ),
    instruction=(
        "You are a vendor reconciliation specialist. Your primary function is to:\n"
        "1. Ask the user for the FULL LOCAL FILE PATHS for the invoice and receipt documents.\n"
        "2. Once you have BOTH file paths, use the 'process_vendor_reconciliation_workflow' tool, passing the "
        "invoice file path as 'invoice_raw_file_path' and the receipt file path as 'receipt_raw_file_path'.\n"
        "3. Present the reconciliation results from the tool to the user clearly.\n"
        "Do NOT attempt to access files yourself. Your tools will handle local file access. "
        "If the user provides files via upload (inline_data), acknowledge it, but you MUST still ask for and use the explicit file paths to pass to your tools."
    ),
    tools=[
        extract_document_data,       
        reconcile_vendor_documents,
        process_vendor_reconciliation_workflow 
    ],
)

# --- Example Usage (to be placed in your main execution script/FastAPI endpoint etc.) ---
if __name__ == "__main__":
    print("Demonstrating Vendor Reconciliation ADK Agent with OPEN-SOURCE PARSING of RAW DOCUMENT FILES")

    sample_raw_docs_dir = "sample_raw_documents" 
    if not os.path.exists(sample_raw_docs_dir):
        os.makedirs(sample_raw_docs_dir)
        print(f"Created directory: {sample_raw_docs_dir}")
        print(f"Please place your sample invoice PDFs/images in '{sample_raw_docs_dir}' for testing.")
        # Example: Create dummy_invoice.pdf and dummy_receipt.png using document_parser.py's main block
        # by running `python document_parser.py` once.

    # --- DEFINE PATHS TO YOUR ACTUAL RAW DOCUMENT FILES ---
    # Update these paths to point to real invoice and receipt files on your system for testing.
    # Using raw strings (r"") is good for Windows paths.
    test_invoice_file = r"C:\Users\Yaswanth\Downloads\invoice.pdf"
    test_receipt_file = r"C:\Users\Yaswanth\Downloads\receipt.pdf"
    
    # Fallback to dummy files if the user's specific files aren't found (for basic script running)
    dummy_invoice_fallback = os.path.join(sample_raw_docs_dir, "dummy_invoice.pdf")
    dummy_receipt_fallback = os.path.join(sample_raw_docs_dir, "dummy_receipt.png")

    if not os.path.exists(test_invoice_file):
        print(f"User invoice file not found at '{test_invoice_file}'. Will try dummy: '{dummy_invoice_fallback}'")
        test_invoice_file = dummy_invoice_fallback
        if not os.path.exists(test_invoice_file):
             print(f"Dummy invoice also not found. Please run `python document_parser.py` or place a file at {dummy_invoice_fallback}")


    if not os.path.exists(test_receipt_file):
        print(f"User receipt file not found at '{test_receipt_file}'. Will try dummy: '{dummy_receipt_fallback}'")
        test_receipt_file = dummy_receipt_fallback
        if not os.path.exists(test_receipt_file):
            print(f"Dummy receipt also not found. Please run `python document_parser.py` or place a file at {dummy_receipt_fallback}")


    # --- Test Case 1: Processing Raw Documents ---
    print(f"\n--- Test Case 1: Processing Raw Document Files ---")
    print(f"Invoice: '{test_invoice_file}'")
    print(f"Receipt: '{test_receipt_file}'")
    
    if not os.path.exists(test_invoice_file) or not os.path.exists(test_receipt_file):
        print(f"SKIPPING TEST: One or both test files not found after checking user paths and fallbacks.")
        print("Please ensure these files exist or update the paths.")
    else:
        result_raw_docs = process_vendor_reconciliation_workflow(test_invoice_file, test_receipt_file)
        print("\n--- Full Workflow Result (JSON) ---")
        print(json.dumps(result_raw_docs, indent=2))
        
        if result_raw_docs.get("status") == "success":
            workflow_res = result_raw_docs.get("workflow_results", {})
            final_decision = workflow_res.get("final_decision", {})
            print(f"\nFinal Decision for Test Case 1: {final_decision.get('status', 'N/A')}")
            print(f"  Confidence: {final_decision.get('confidence', 'N/A')}")
            print(f"  Action Required: {final_decision.get('action_required', 'N/A')}")
            
            reconciliation_details = workflow_res.get("reconciliation", {})
            if reconciliation_details.get("discrepancies"):
                print("\n  Discrepancies Found:")
                for disc in reconciliation_details["discrepancies"]:
                    print(f"    - {disc}")
            else:
                print("\n  No discrepancies reported by reconciliation logic.")

        elif result_raw_docs.get("status") == "error":
             print(f"\nError in Test Case 1: {result_raw_docs.get('error_message', 'Unknown error')}")

    print("\nTo use with ADK Agent's `chat` method, you would provide the full file paths when prompted.")
    print("Example interaction:")
    print("User: process invoice and receipt")
    print("Agent: Okay, provide invoice path.")
    print("User: C:\\path\\to\\invoice.pdf")
    print("Agent: Okay, provide receipt path.")
    print("User: C:\\path\\to\\receipt.pdf")
    print("Agent: (Makes function call to process_vendor_reconciliation_workflow)")