import os
import json
from typing import Dict, Any, Optional,List
from google.adk.agents.llm_agent import LlmAgent
from dotenv import load_dotenv
import traceback
import asyncio 

# Path setup
import sys
project_root_orch = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_orch not in sys.path: sys.path.insert(0, project_root_orch)

# Import the A2A client and hypothetical types
from client import a2a_client, SendMessageRequest, MessageSendParams, Part # Use your actual client

# Import DB functions for direct checks by Orchestrator if needed
from database_manager import get_invoice_by_number, get_po_by_number, get_invoice_by_related_po
import google.generativeai as genai

# --- AgentCard Definition for Orchestrator (optional, but good practice) ---
ORCH_AGENT_HOST = os.getenv("ORCH_AGENT_HOST", "localhost")
ORCH_AGENT_PORT = int(os.getenv("ORCH_AGENT_PORT", 8000)) # Main agent port





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



orchestrator_capability = AgentCapability(name="_orchestrate_po_reconciliation_tool", description="Manages the PO-centric reconciliation workflow.")
orchestrator_skill = AgentSkill(name="Reconciliation Orchestration", description="Coordinates data ingestion and reconciliation sub-tasks.", capabilities=[orchestrator_capability])

orchestrator_agent_card = AgentCard(
    name="vendor_reconciliation_orchestrator_a2a",
    description="Main orchestrator AI agent for vendor reconciliation via A2A.",
    url=f"http://{ORCH_AGENT_HOST}:{ORCH_AGENT_PORT}/invoke",
    version="1.0.0",
    defaultInputModes=["text/plain"], defaultOutputModes=["application/json"],
    capabilities=[], skills=[orchestrator_skill]
)
print(f"ORCHESTRATOR_AGENT: Defined AgentCard: {json.dumps(orchestrator_agent_card.to_dict(), indent=2)}")
print("ORCHESTRATOR_AGENT: Registering sub-agent URLs/names with A2AClient (mock)...")
a2a_client.register_agent_url(
    "data_ingestion_specialist_agent", 
    # For the mock, the URL isn't strictly used for HTTP, but good to have.
    # It's the NAME that the mock A2AClient uses to find the right Python function.
    f"http://{os.getenv('DATA_INGESTION_AGENT_HOST', 'localhost')}:{int(os.getenv('DATA_INGESTION_AGENT_PORT', 8001))}/mock_invoke" 
)
a2a_client.register_agent_url(
    "reconciliation_specialist_agent", 
    f"http://{os.getenv('RECON_AGENT_HOST', 'localhost')}:{int(os.getenv('RECON_AGENT_PORT', 8002))}/mock_invoke"\
)



if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (OrchestratorAgent): GOOGLE_API_KEY not set.")
elif not getattr(genai, 'API_KEY', None) and os.getenv("GOOGLE_API_KEY"):
    try: genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    except Exception as e: print(f"Error configuring GenAI in OrchestratorAgent: {e}")


async def _orchestrate_po_reconciliation_tool( 
    po_number_input: str,
    new_po_file_path: Optional[str] = None,
    new_invoice_file_path: Optional[str] = None
    ) -> dict:
    """
    TOOL (Orchestrator): Drives reconciliation starting with a PO number.
    Delegates to sub-agents via A2A calls.
    """
    print(f"ORCHESTRATOR_A2A_TOOL: po_number='{po_number_input}', "
          f"new_po_file='{new_po_file_path}', new_inv_file='{new_invoice_file_path}'")

    final_report: Dict[str, Any] = {"steps_taken": [], "overall_status": "pending"}
    po_extraction_full_obj: Optional[Dict[str, Any]] = None
    invoice_extraction_full_obj: Optional[Dict[str, Any]] = None
    
    po_number_to_process = po_number_input.strip().upper() if po_number_input else None
    if not po_number_to_process:
        return {"status": "error", "error_message": "PO number input is required."}

    
    step_msg_po = f"Step 1: Acquiring PO '{po_number_to_process}'."
    final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po}")
    po_from_db = get_po_by_number(po_number_to_process)

    if po_from_db:
        po_extraction_full_obj = po_from_db
        final_report["po_acquisition"] = {"status": "success_from_db", "source": "database", "doc_number": po_extraction_full_obj.get("data",{}).get("document_number")}
        step_msg_po += " Found in database."
    elif new_po_file_path:
        step_msg_po += f" Not in DB. Delegating ingestion of new file '{new_po_file_path}'."
        
        ingestion_query = (f"Use your `_ingest_and_store_document_tool` to process this document: "
                           f"File path is '{new_po_file_path}', document type is 'purchase_order'. "
                           f"Return the full JSON result from your tool.") 
        
        
        ingestion_query_for_mock_a2a = (
            f"_ingest_and_store_document_tool: {json.dumps({'raw_document_file_path': new_po_file_path, 'document_type': 'purchase_order'})}"
        )
        a2a_request = SendMessageRequest(
            agent_id_or_url="data_ingestion_specialist_agent", 
            message=MessageSendParams(parts=[Part(text=ingestion_query_for_mock_a2a)])
        )
        ingestion_response_dict = await a2a_client.send_message(a2a_request) # Use the A2A client

        final_report["po_acquisition"] = ingestion_response_dict
        if ingestion_response_dict.get("status") == "success":
            po_extraction_full_obj = ingestion_response_dict.get("full_extraction_result")
            extracted_po_num = po_extraction_full_obj.get("data",{}).get("document_number","").strip().upper()
            if extracted_po_num and extracted_po_num != po_number_to_process:
                step_msg_po += f" File extracted as PO '{extracted_po_num}'. Using this."
                po_number_to_process = extracted_po_num
            step_msg_po += f" Successfully ingested new PO as '{po_number_to_process}' via A2A."
        else:
            final_report["overall_status"] = "error"; final_report["error_message"] = f"A2A PO ingestion failed: {ingestion_response_dict.get('error_message')}"
            final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po} - Error"); return final_report
    else:
        step_msg_po += f" PO '{po_number_to_process}' not found in DB and no new file provided."
        final_report["overall_status"] = "po_not_found_needs_file"; final_report["message_to_user"] = step_msg_po
        final_report["required_next_input"] = "new_po_file_path"; final_report["context_po_number"] = po_number_to_process
        final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po}"); return final_report
    
    final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po}")

    if not po_extraction_full_obj or po_extraction_full_obj.get("status") != "success":
        final_report["overall_status"] = "error"; final_report["error_message"] = "Valid PO data not obtained."
        return final_report
    confirmed_po_number = po_extraction_full_obj.get("data", {}).get("document_number", "").strip().upper()
    if not confirmed_po_number:
        final_report["overall_status"] = "error"; final_report["error_message"] = "Critical: PO number missing."
        return final_report

    
    step_msg_inv = f"Step 2: Acquiring Invoice related to PO '{confirmed_po_number}'."
    final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv}")
    if new_invoice_file_path:
        step_msg_inv += f" Delegating ingestion of new invoice file '{new_invoice_file_path}'."
        ingestion_query_for_mock_a2a = (
             f"_ingest_and_store_document_tool: {json.dumps({'raw_document_file_path': new_invoice_file_path, 'document_type': 'invoice'})}"
        )
        a2a_request_inv = SendMessageRequest(
            agent_id_or_url="data_ingestion_specialist_agent",
            message=MessageSendParams(parts=[Part(text=ingestion_query_for_mock_a2a)])
        )
        ingestion_response_dict_inv = await a2a_client.send_message(a2a_request_inv)
        final_report["invoice_acquisition"] = ingestion_response_dict_inv
        if ingestion_response_dict_inv.get("status") == "success":
            invoice_extraction_full_obj = ingestion_response_dict_inv.get("full_extraction_result")
            step_msg_inv += " Successfully ingested new invoice via A2A."
        else:
            final_report["overall_status"] = "error"; final_report["error_message"] = f"A2A Invoice ingestion failed: {ingestion_response_dict_inv.get('error_message')}"
            final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv} - Error"); return final_report
    else:
        step_msg_inv += f" Searching DB for invoice related to PO '{confirmed_po_number}'."
        invoice_extraction_full_obj = get_invoice_by_related_po(confirmed_po_number)
        if invoice_extraction_full_obj:
            inv_num_found = invoice_extraction_full_obj.get('data',{}).get('document_number', 'UNKNOWN')
            step_msg_inv += f" Found related invoice '{inv_num_found}' in DB."
            final_report["invoice_acquisition"] = {"status": "success_from_db_related_to_po", "source": "database", "document_number": inv_num_found}
        else:
            step_msg_inv += f" No related invoice found in DB for PO '{confirmed_po_number}'."
            final_report["overall_status"] = "po_secured_invoice_needed"; final_report["message_to_user"] = step_msg_inv
            final_report["required_next_input"] = "new_invoice_file_path"; final_report["context_po_number"] = confirmed_po_number
            final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv}"); return final_report
            
    final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv}")

    if not invoice_extraction_full_obj or invoice_extraction_full_obj.get("status") != "success":
        final_report["overall_status"] = "error"; final_report["error_message"] = "Valid Invoice data not obtained."
        return final_report

    
    step_msg_reco = f"Step 3: Delegating reconciliation to ReconciliationAgent."
    final_report["steps_taken"].append(step_msg_reco); print(f"ORCHESTRATOR: {step_msg_reco}")
    
    reco_query_for_mock_a2a = (
        f"_perform_reconciliation_logic_tool: {json.dumps({
            'invoice_data_json_str': json.dumps(invoice_extraction_full_obj), 
            'po_data_json_str': json.dumps(po_extraction_full_obj)
        })}"
    )
    a2a_request_reco = SendMessageRequest(
        agent_id_or_url="reconciliation_specialist_agent",
        message=MessageSendParams(parts=[Part(text=reco_query_for_mock_a2a)])
    )
    reco_response_dict = await a2a_client.send_message(a2a_request_reco)
    final_report["reconciliation_report"] = reco_response_dict

    if reco_response_dict.get("status") == "success":
        final_report["overall_status"] = "success_reconciled"; final_report["message"] = "Reconciliation complete."
    else:
        final_report["overall_status"] = "error_in_reconciliation"; final_report["error_message"] = f"Reconciliation A2A call failed: {reco_response_dict.get('error_message')}"
            
    return final_report

# Orchestrator LlmAgent instance
root_agent = LlmAgent(
    name=orchestrator_agent_card.name, # Use name from AgentCard
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=orchestrator_agent_card.description,
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
        _orchestrate_po_reconciliation_tool
    ]
)

