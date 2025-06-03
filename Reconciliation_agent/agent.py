# reconciliation_processing_agent/agent.py
import os
import json
from typing import Dict, Any, Optional,List
from google.adk.agents.llm_agent import LlmAgent
# from google.adk import AgentCard # Hypothetical
# from a2a.types import Part # Hypothetical
import traceback

# Path setup
import sys
project_root_rc = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_rc not in sys.path: sys.path.insert(0, project_root_rc)

from database_manager import get_invoice_by_number, get_po_by_number
from difflib import SequenceMatcher 
import re 
import google.generativeai as genai

# ---- AgentCard Definition (Hypothetical) ----
RECON_AGENT_HOST = os.getenv("RECON_AGENT_HOST", "localhost")
RECON_AGENT_PORT = int(os.getenv("RECON_AGENT_PORT", 8002)) # Example port

# In orchestrator_agent/agent.py
# In data_ingestion_agent/agent.py
# In reconciliation_processing_agent/agent.py

# --- Start Hypothetical AgentCard and related types ---
class AgentCapability: # Mock
    def __init__(self, name: str, description: str, input_schema=None, output_schema=None):
        self.name = name
        self.description = description
        # self.input_schema = input_schema # Store if needed for to_dict
        # self.output_schema = output_schema # Store if needed for to_dict
    def to_dict(self) -> Dict[str, Any]: # ADDED
        return {"name": self.name, "description": self.description}

class AgentSkill: # Mock
    def __init__(self, name: str, description: str, capabilities: List[AgentCapability]):
        self.name = name
        self.description = description
        self.capabilities = capabilities
    def to_dict(self) -> Dict[str, Any]: # ADDED
        return {
            "name": self.name, 
            "description": self.description, 
            "capabilities": [cap.to_dict() for cap in self.capabilities]
        }

class AgentCard: # Mock
    def __init__(self, name: str, description: str, url: str, version: str, 
                 defaultInputModes: List[str], defaultOutputModes: List[str], 
                 capabilities: List[AgentCapability], # Assuming top-level capabilities
                 skills: List[AgentSkill]):
        self.name = name
        self.description = description
        self.url = url
        self.version = version
        self.defaultInputModes = defaultInputModes
        self.defaultOutputModes = defaultOutputModes
        self.capabilities = capabilities # List of AgentCapability objects
        self.skills = skills # List of AgentSkill objects

    def to_dict(self) -> Dict[str, Any]: # ADDED
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "defaultInputModes": self.defaultInputModes,
            "defaultOutputModes": self.defaultOutputModes,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "skills": [skill.to_dict() for skill in self.skills]
        }


reco_capability = AgentCapability(
    name="_perform_reconciliation_logic_tool",
    description="Compares extracted invoice and PO data."
)
reco_skill = AgentSkill(
    name="Document Reconciliation Skill",
    description="Performs detailed comparison of financial documents.",
    capabilities=[reco_capability]
)

reconciliation_agent_card = AgentCard(
    name="reconciliation_specialist_agent", # Must match name used by orchestrator
    description="Specialized agent for comparing invoice and PO data.",
    url=f"http://{RECON_AGENT_HOST}:{RECON_AGENT_PORT}/invoke", # ADK endpoint
    version="1.0.0",
    defaultInputModes=["application/json"], # Expects JSON in A2A call
    defaultOutputModes=["application/json"],
    capabilities=[],
    skills=[reco_skill]
)
print(f"RECONCILIATION_AGENT: Defined AgentCard: {json.dumps(reconciliation_agent_card.to_dict(), indent=2)}")
# --- End AgentCard Definition ---


if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (ReconciliationAgent): GOOGLE_API_KEY not set.")
elif not getattr(genai, 'API_KEY', None) and os.getenv("GOOGLE_API_KEY"):
    try: genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    except Exception as e: print(f"Error configuring GenAI in ReconciliationAgent: {e}")

# Helper functions (same as before)
def _compare_strings_fuzzy_local(s1,s2,t=0.8): ... # Ellipsis, use full code
def _compare_amounts_local(a1,a2,t=0.01): ...
def _get_action_required_local(s): ...
# --- Start Full Helper Functions ---
def _compare_strings_fuzzy_local(s1: Optional[str], s2: Optional[str], threshold=0.8) -> bool:
    if s1 is None and s2 is None: return True; # ... (rest of function from previous)
    if s1 is None or s2 is None: return False
    clean_s1 = re.sub(r'[^\w\s]', '', s1.lower().strip()); clean_s2 = re.sub(r'[^\w\s]', '', s2.lower().strip())
    if not clean_s1 and not clean_s2: return True
    if not clean_s1 or not clean_s2: return False
    return SequenceMatcher(None, clean_s1, clean_s2).ratio() >= threshold
def _compare_amounts_local(amount1: Any, amount2: Any, tolerance=0.01) -> bool:
    try: # ... (rest of function from previous)
        amt1 = float(str(amount1).replace(',','')) if amount1 is not None else 0.0
        amt2 = float(str(amount2).replace(',','')) if amount2 is not None else 0.0
        return abs(amt1 - amt2) <= tolerance
    except (ValueError, TypeError): return False
def _get_action_required_local(status: str) -> str: # ... (rest of function from previous)
    actions = { "APPROVED": "Proceed.", "NEEDS_REVIEW": "Manual review.", "REJECTED": "Investigate." }
    return actions.get(status, "Unknown status")
# --- End Full Helper Functions ---

def _perform_reconciliation_logic_tool(invoice_data_json_str: str, po_data_json_str: str) -> dict:
    # ... (Implementation is THE SAME as your last working version for this tool)
    print(f"RECON_AGENT_TOOL: _perform_reconciliation_logic_tool called.")
    try:
        invoice_data_full = json.loads(invoice_data_json_str); po_data_full = json.loads(po_data_json_str)
        if invoice_data_full.get("status") != "success": return {"status": "error", "error_message": "Invoice data invalid."}
        if po_data_full.get("status") != "success": return {"status": "error", "error_message": "PO data invalid."}
        invoice_data = invoice_data_full.get("data", {}); po_data = po_data_full.get("data", {})
        discrepancies, matched_fields = [], []
        inv_ref_po_num_raw = invoice_data.get("related_po_number"); inv_ref_po_num = inv_ref_po_num_raw.strip().upper() if inv_ref_po_num_raw and isinstance(inv_ref_po_num_raw, str) else None
        actual_po_num_raw = po_data.get("document_number"); actual_po_num = actual_po_num_raw.strip().upper() if actual_po_num_raw and isinstance(actual_po_num_raw, str) else None
        if inv_ref_po_num and actual_po_num and inv_ref_po_num == actual_po_num: matched_fields.append("po_number_reference_match")
        elif actual_po_num and inv_ref_po_num: discrepancies.append(f"PO Mismatch: Inv PO '{inv_ref_po_num}' vs Actual PO '{actual_po_num}'.")
        elif actual_po_num and not inv_ref_po_num : discrepancies.append(f"Missing PO Ref on Inv for PO '{actual_po_num}'.")
        elif not actual_po_num: discrepancies.append("Critical: PO number missing in PO data.")
        inv_vendor = invoice_data.get("vendor_name"); po_vendor = po_data.get("vendor_name")
        if _compare_strings_fuzzy_local(inv_vendor, po_vendor): matched_fields.append("vendor_name")
        else: discrepancies.append(f"Vendor Mismatch: Inv='{inv_vendor or 'N/A'}' vs PO='{po_vendor or 'N/A'}'")
        inv_amount = invoice_data.get("total_amount"); po_amount = po_data.get("total_amount")
        if _compare_amounts_local(inv_amount, po_amount): matched_fields.append("total_amount")
        else: discrepancies.append(f"Amount Mismatch: Inv=${float(inv_amount or 0):.2f} vs PO=${float(po_amount or 0):.2f}")
        inv_items = invoice_data.get("line_items", []); po_items = po_data.get("line_items", [])
        if len(inv_items) == len(po_items) and (len(inv_items) > 0 or (len(inv_items)==0 and len(po_items)==0)): matched_fields.append("line_items_count")
        else: discrepancies.append(f"Item Count Mismatch: Inv={len(inv_items)} vs PO={len(po_items)}")
        total_key_fields = 4; match_percentage = (len(matched_fields) / total_key_fields * 100) if total_key_fields > 0 else 0
        status_reco = "REJECTED"; recommendation = "Review details."
        if not discrepancies: status_reco = "APPROVED"; recommendation = "Match."
        elif "po_number_reference_match" not in matched_fields and inv_ref_po_num and actual_po_num and inv_ref_po_num != actual_po_num: status_reco = "REJECTED"; recommendation = "Critical PO ref mismatch."
        elif not actual_po_num: status_reco = "REJECTED"; recommendation = "PO missing number."
        elif match_percentage >= 75: status_reco = "NEEDS_REVIEW"; recommendation = f"High match ({match_percentage:.1f}%) with discrepancies."
        else: recommendation = f"Low match ({match_percentage:.1f}%)."
        inv_conf = float(invoice_data.get("confidence_score",0.5)); po_conf = float(po_data.get("confidence_score",0.5))
        overall_conf = ((inv_conf+po_conf)/2*0.5) + ((match_percentage/100)*0.5)
        return {"status": "success", "reconciliation_result": {"approval_status": status_reco, "match_percentage": round(match_percentage,1), "confidence_score": round(overall_conf,2), "matched_fields": matched_fields, "discrepancies": discrepancies, "recommendation": recommendation, "summary": {"invoice_number": invoice_data.get("document_number"), "po_number": po_data.get("document_number"), "invoice_total": inv_amount, "po_total": po_amount}}}
    except json.JSONDecodeError as e: return {"status": "error", "error_message": f"Invalid JSON: {str(e)}"}
    except Exception as e: print(f"ERROR: {e}\n{traceback.format_exc()}"); return {"status": "error", "error_message": f"Reco logic error: {str(e)}"}

reconciliation_llm_agent = LlmAgent(
    name=reconciliation_agent_card.name, # Use name from AgentCard
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=reconciliation_agent_card.description,
    instruction=(
        "You are a Reconciliation Specialist. An Orchestrator Agent will send you a message "
        "effectively asking you to call your `_perform_reconciliation_logic_tool`. "
        "The message will contain `invoice_data_json_str` and `po_data_json_str` arguments.\n"
        "Your ONLY task is to use this tool with the provided JSON strings "
        "and return its complete JSON result. Do not add conversational fluff."
    ),
    tools=[_perform_reconciliation_logic_tool]
)

root_agent = reconciliation_llm_agent