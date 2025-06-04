import os
import json
from typing import Dict, Any, Optional, List
from google.adk.agents.llm_agent import LlmAgent
from dotenv import load_dotenv
import traceback
import httpx # Import httpx
import uuid # For generating messageId
import pydantic # To catch pydantic.ValidationError

import sys
project_root_orch = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_orch not in sys.path: sys.path.insert(0, project_root_orch)

DiscoveredA2AClientClass = None
SendMessageRequest, MessageSendParams, Message, Part, Task, Role = None, None, None, None, None, None
A2AAgentCard, SendMessageResponse, SendMessageSuccessResponse = None, None, None

shared_httpx_client: Optional[httpx.AsyncClient] = None

try:
    from a2a.client.client import A2AClient as ActualDiscoveredClient
    from a2a.types import (
        SendMessageRequest as TypesSMR,
        MessageSendParams as TypesMSP,
        Message as TypesMessage, # Import Message
        Part as TypesPart,
        Task as TypesTask,
        Role as TypesRole, # Import Role
        AgentCard as TypesA2AAgentCard,
        SendMessageResponse as TypesSMResponse,
        SendMessageSuccessResponse as TypesSMSuccessResponse, # Assuming this exists
    )

    DiscoveredA2AClientClass = ActualDiscoveredClient
    SendMessageRequest, MessageSendParams, Message, Part, Task, Role = \
        TypesSMR, TypesMSP, TypesMessage, TypesPart, TypesTask, TypesRole
    A2AAgentCard = TypesA2AAgentCard
    SendMessageResponse, SendMessageSuccessResponse = TypesSMResponse, TypesSMSuccessResponse

    print("SUCCESS: Client from 'a2a.client.client' and types from 'a2a.types' imported.")

except ImportError as e:
    print(f"ERROR: Could not import client from 'a2a.client.client' or types from 'a2a.types': {e}")
    print("       A2A functionality will be severely impaired or unavailable.")
    

from database_manager import get_invoice_by_number, get_po_by_number, get_invoice_by_related_po
import google.generativeai as genai

ORCH_AGENT_HOST = os.getenv("ORCH_AGENT_HOST", "localhost")
ORCH_AGENT_PORT = int(os.getenv("ORCH_AGENT_PORT", 8000))

class AgentCapability:
    def __init__(self, name: str, description: str, input_schema=None, output_schema=None):
        self.name = name
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description}

class AgentSkill:
    def __init__(self, name: str, description: str, capabilities: List[AgentCapability]):
        self.name = name
        self.description = description
        self.capabilities = capabilities
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": [cap.to_dict() for cap in self.capabilities]
        }

class AgentCard:
    def __init__(self, name: str, description: str, url: str, version: str,
                 defaultInputModes: List[str], defaultOutputModes: List[str],
                 capabilities: List[AgentCapability],
                 skills: List[AgentSkill]):
        self.name = name
        self.description = description
        self.url = url
        self.version = version
        self.defaultInputModes = defaultInputModes
        self.defaultOutputModes = defaultOutputModes
        self.capabilities = capabilities
        self.skills = skills

    def to_dict(self) -> Dict[str, Any]:
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

    def to_a2a_agent_card(self) -> Optional[Any]:
        """Convert to A2A AgentCard format (from a2a.types)"""
        if not A2AAgentCard:
            print("WARN: a2a.types.AgentCard class not available. Cannot create A2A AgentCard.")
            return None
        
        try:
            return A2AAgentCard(
                name=self.name,
                description=self.description,
                url=self.url,
                version=self.version,
                defaultInputModes=self.defaultInputModes,
                defaultOutputModes=self.defaultOutputModes
                
            )
        except Exception as card_ex:
            print(f"Error creating a2a.types.AgentCard: {card_ex}")
            return None


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

DATA_INGESTION_AGENT_URL = f"http://{os.getenv('DATA_INGESTION_AGENT_HOST', 'localhost')}:{int(os.getenv('DATA_INGESTION_AGENT_PORT', 8001))}/invoke"
RECONCILIATION_AGENT_URL = f"http://{os.getenv('RECON_AGENT_HOST', 'localhost')}:{int(os.getenv('RECON_AGENT_PORT', 8002))}/invoke"

if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (OrchestratorAgent): GOOGLE_API_KEY not set.")
elif not getattr(genai, 'API_KEY', None) and os.getenv("GOOGLE_API_KEY"):
    try: genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    except Exception as e: print(f"Error configuring GenAI in OrchestratorAgent: {e}")


async def _get_shared_httpx_client() -> httpx.AsyncClient:
    global shared_httpx_client
    if shared_httpx_client is None or shared_httpx_client.is_closed:
        print("INFO: Creating new shared httpx.AsyncClient instance.")
        shared_httpx_client = httpx.AsyncClient()
    return shared_httpx_client

async def _orchestrate_po_reconciliation_tool(
    po_number_input: str,
    new_po_file_path: Optional[str] = None,
    new_invoice_file_path: Optional[str] = None
    ) -> dict:
    print(f"ORCHESTRATOR_A2A_TOOL: po_number='{po_number_input}', "
          f"new_po_file='{new_po_file_path}', new_inv_file='{new_invoice_file_path}'")

    if not all([DiscoveredA2AClientClass, SendMessageRequest, MessageSendParams, Message, Part, Role]):
        return {
            "status": "error",
            "error_message": "A2A client components or types (Client, SMR, MSP, Message, Part, Role) not initialized. Check imports."
        }

    http_client = await _get_shared_httpx_client()
    final_report: Dict[str, Any] = {"steps_taken": [], "overall_status": "pending"}
    po_extraction_full_obj: Optional[Dict[str, Any]] = None
    invoice_extraction_full_obj: Optional[Dict[str, Any]] = None

    po_number_to_process = po_number_input.strip().upper() if po_number_input else None
    if not po_number_to_process:
        return {"status": "error", "error_message": "PO number input is required."}

    step_msg_po = f"Step 1: Acquiring PO '{po_number_to_process}'."
    final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po}")
    po_from_db = get_po_by_number(po_number_to_process)
    ingestion_response_dict = {}

    if po_from_db:
        po_extraction_full_obj = po_from_db
        final_report["po_acquisition"] = {"status": "success_from_db", "source": "database", "doc_number": po_extraction_full_obj.get("data",{}).get("document_number")}
        step_msg_po += " Found in database."
    elif new_po_file_path:
        step_msg_po += f" Not in DB. Delegating ingestion of new file '{new_po_file_path}'."
        ingestion_tool_text = f"_ingest_and_store_document_tool: {json.dumps({'raw_document_file_path': new_po_file_path, 'document_type': 'purchase_order'})}"
        try:
            msg_parts_po = [Part(text=ingestion_tool_text)]
            actual_msg_obj_po = Message(
                messageId=str(uuid.uuid4()),
                parts=msg_parts_po,
                role=Role.user
            )
            msg_params_po = MessageSendParams(message=actual_msg_obj_po)
            a2a_payload_po = SendMessageRequest(params=msg_params_po, id=str(uuid.uuid4())) # MODIFIED: Added 'params=', optionally 'id='
            ingestion_agent_client = DiscoveredA2AClientClass(httpx_client=http_client, url=DATA_INGESTION_AGENT_URL)
            print(f"ORCHESTRATOR: Sending A2A PO request to {DATA_INGESTION_AGENT_URL}")
            ingestion_response_sdk_obj = await ingestion_agent_client.send_message(request=a2a_payload_po)
            if ingestion_response_sdk_obj and hasattr(ingestion_response_sdk_obj, 'message') and ingestion_response_sdk_obj.message and hasattr(ingestion_response_sdk_obj.message, 'parts') and ingestion_response_sdk_obj.message.parts:
                response_text = ingestion_response_sdk_obj.message.parts[0].text
                print(f"ORCHESTRATOR: Received A2A PO response: {response_text[:200]}...")
                ingestion_response_dict = json.loads(response_text)
            elif ingestion_response_sdk_obj and hasattr(ingestion_response_sdk_obj, 'error') and ingestion_response_sdk_obj.error:
                ingestion_response_dict = {"status": "error", "error_message": f"A2A PO call failed - agent error: {ingestion_response_sdk_obj.error.message}"}
            else:
                ingestion_response_dict = {"status": "error", "error_message": "A2A PO call failed - unexpected response structure"}
        except pydantic.ValidationError as ve:
            ingestion_response_dict = {"status": "error", "error_message": f"Pydantic validation error creating A2A PO request: {ve}"}
            print(f"PYDANTIC ERROR (PO Ingestion): {ve}")
        except json.JSONDecodeError as e:
            ingestion_response_dict = {"status": "error", "error_message": f"Invalid JSON response from A2A (PO): {str(e)}"}
        except Exception as e:
            ingestion_response_dict = {"status": "error", "error_message": f"A2A PO communication error: {str(e)} \n{traceback.format_exc()}"}
            print(traceback.format_exc())
        final_report["po_acquisition"] = ingestion_response_dict
        if ingestion_response_dict.get("status") == "success":
            po_extraction_full_obj = ingestion_response_dict.get("full_extraction_result")
            if po_extraction_full_obj and isinstance(po_extraction_full_obj, dict):
                extracted_po_num_obj = po_extraction_full_obj.get("data",{}).get("document_number")
                extracted_po_num = str(extracted_po_num_obj).strip().upper() if extracted_po_num_obj is not None else ""
                if extracted_po_num and extracted_po_num != po_number_to_process:
                    step_msg_po += f" File extracted as PO '{extracted_po_num}'. Using this."
                    po_number_to_process = extracted_po_num
                step_msg_po += f" Successfully ingested new PO as '{po_number_to_process}' via A2A."
            else:
                ingestion_response_dict["status"] = "error"
                ingestion_response_dict["error_message"] = "A2A PO ingestion succeeded but response format was unexpected."
                final_report["overall_status"] = "error"; final_report["error_message"] = ingestion_response_dict["error_message"]
                final_report["steps_taken"].append(step_msg_po + " - Error in response format"); print(f"ORCHESTRATOR: {step_msg_po} - Error in response format"); return final_report
        else:
            final_report["overall_status"] = "error"; final_report["error_message"] = f"A2A PO ingestion failed: {ingestion_response_dict.get('error_message', 'Unknown error')}"
            final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po} - Error"); return final_report
    else:
        step_msg_po += f" PO '{po_number_to_process}' not found in DB and no new file provided."
        final_report["overall_status"] = "po_not_found_needs_file"; final_report["message_to_user"] = step_msg_po
        final_report["required_next_input"] = "new_po_file_path"; final_report["context_po_number"] = po_number_to_process
        final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po}"); return final_report
    final_report["steps_taken"].append(step_msg_po); print(f"ORCHESTRATOR: {step_msg_po}")
    if not po_extraction_full_obj:
        final_report["overall_status"] = "error"; final_report["error_message"] = "Critical: PO data object is missing after acquisition attempts."
        return final_report
    confirmed_po_number = ""
    if isinstance(po_extraction_full_obj, dict) and "data" in po_extraction_full_obj:
        confirmed_po_number = str(po_extraction_full_obj.get("data", {}).get("document_number", "")).strip().upper()
    if not confirmed_po_number and po_number_to_process :
         confirmed_po_number = po_number_to_process
    if not confirmed_po_number:
        final_report["overall_status"] = "error"; final_report["error_message"] = "Critical: PO number missing or could not be confirmed after acquisition."
        return final_report

    step_msg_inv = f"Step 2: Acquiring Invoice related to PO '{confirmed_po_number}'."
    final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv}")
    ingestion_response_dict_inv = {}
    if new_invoice_file_path:
        step_msg_inv += f" Delegating ingestion of new invoice file '{new_invoice_file_path}'."
        invoice_tool_text = f"_ingest_and_store_document_tool: {json.dumps({'raw_document_file_path': new_invoice_file_path, 'document_type': 'invoice'})}"
        try:
            msg_parts_inv = [Part(text=invoice_tool_text)]
            actual_msg_obj_inv = Message(
                messageId=str(uuid.uuid4()),
                parts=msg_parts_inv,
                role=Role.user
            )
            msg_params_inv = MessageSendParams(message=actual_msg_obj_inv)
            a2a_payload_inv = SendMessageRequest(params=msg_params_inv, id=str(uuid.uuid4())) # MODIFIED: Added 'params=', optionally 'id='
            invoice_agent_client = DiscoveredA2AClientClass(httpx_client=http_client, url=DATA_INGESTION_AGENT_URL)
            print(f"ORCHESTRATOR: Sending A2A invoice request to {DATA_INGESTION_AGENT_URL}")
            ingestion_response_inv_sdk_obj = await invoice_agent_client.send_message(request=a2a_payload_inv)
            if ingestion_response_inv_sdk_obj and hasattr(ingestion_response_inv_sdk_obj, 'message') and ingestion_response_inv_sdk_obj.message and hasattr(ingestion_response_inv_sdk_obj.message, 'parts') and ingestion_response_inv_sdk_obj.message.parts:
                response_text_inv = ingestion_response_inv_sdk_obj.message.parts[0].text
                print(f"ORCHESTRATOR: Received A2A invoice response: {response_text_inv[:200]}...")
                ingestion_response_dict_inv = json.loads(response_text_inv)
            elif ingestion_response_inv_sdk_obj and hasattr(ingestion_response_inv_sdk_obj, 'error') and ingestion_response_inv_sdk_obj.error:
                ingestion_response_dict_inv = {"status": "error", "error_message": f"A2A Invoice call failed - agent error: {ingestion_response_inv_sdk_obj.error.message}"}
            else:
                ingestion_response_dict_inv = {"status": "error", "error_message": "A2A Invoice call failed - unexpected response structure"}
        except pydantic.ValidationError as ve:
            ingestion_response_dict_inv = {"status": "error", "error_message": f"Pydantic validation error creating A2A Invoice request: {ve}"}
            print(f"PYDANTIC ERROR (Invoice Ingestion): {ve}")
        except json.JSONDecodeError as e:
            ingestion_response_dict_inv = {"status": "error", "error_message": f"Invalid JSON response from A2A (Invoice): {str(e)}"}
        except Exception as e:
            ingestion_response_dict_inv = {"status": "error", "error_message": f"A2A Invoice communication error: {str(e)} \n{traceback.format_exc()}"}
            print(traceback.format_exc())
        final_report["invoice_acquisition"] = ingestion_response_dict_inv
        if ingestion_response_dict_inv.get("status") == "success":
            invoice_extraction_full_obj = ingestion_response_dict_inv.get("full_extraction_result")
            if not (invoice_extraction_full_obj and isinstance(invoice_extraction_full_obj, dict)):
                 ingestion_response_dict_inv["status"] = "error"
                 ingestion_response_dict_inv["error_message"] = "A2A Invoice ingestion succeeded but response format was unexpected."
                 final_report["overall_status"] = "error"; final_report["error_message"] = ingestion_response_dict_inv["error_message"]
                 final_report["steps_taken"].append(step_msg_inv + " - Error in response format"); print(f"ORCHESTRATOR: {step_msg_inv} - Error in response format"); return final_report
            step_msg_inv += " Successfully ingested new invoice via A2A."
        else:
            final_report["overall_status"] = "error"; final_report["error_message"] = f"A2A Invoice ingestion failed: {ingestion_response_dict_inv.get('error_message', 'Unknown error')}"
            final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv} - Error"); return final_report
    else:
        step_msg_inv += f" Searching DB for invoice related to PO '{confirmed_po_number}'."
        invoice_extraction_full_obj = get_invoice_by_related_po(confirmed_po_number)
        if invoice_extraction_full_obj:
            inv_num_found_obj = invoice_extraction_full_obj.get('data',{}).get('document_number', 'UNKNOWN')
            inv_num_found = str(inv_num_found_obj)
            step_msg_inv += f" Found related invoice '{inv_num_found}' in DB."
            final_report["invoice_acquisition"] = {"status": "success_from_db_related_to_po", "source": "database", "document_number": inv_num_found}
        else:
            step_msg_inv += f" No related invoice found in DB for PO '{confirmed_po_number}'."
            final_report["overall_status"] = "po_secured_invoice_needed"; final_report["message_to_user"] = step_msg_inv
            final_report["required_next_input"] = "new_invoice_file_path"; final_report["context_po_number"] = confirmed_po_number
            final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv}"); return final_report
    final_report["steps_taken"].append(step_msg_inv); print(f"ORCHESTRATOR: {step_msg_inv}")
    if not invoice_extraction_full_obj:
        final_report["overall_status"] = "error"; final_report["error_message"] = "Valid Invoice data not obtained."
        return final_report

    step_msg_reco = f"Step 3: Delegating reconciliation to ReconciliationAgent."
    final_report["steps_taken"].append(step_msg_reco); print(f"ORCHESTRATOR: {step_msg_reco}")
    reco_response_dict = {}
    reco_tool_invocation_text = f"_perform_reconciliation_logic_tool: {json.dumps({'invoice_data_json_str': json.dumps(invoice_extraction_full_obj), 'po_data_json_str': json.dumps(po_extraction_full_obj)})}"
    try:
        msg_parts_reco = [Part(text=reco_tool_invocation_text)]
        actual_msg_obj_reco = Message(
            messageId=str(uuid.uuid4()),
            parts=msg_parts_reco,
            role=Role.user
        )
        msg_params_reco = MessageSendParams(message=actual_msg_obj_reco)
        a2a_payload_reco = SendMessageRequest(params=msg_params_reco, id=str(uuid.uuid4())) # MODIFIED: Added 'params=', optionally 'id='
        reco_agent_client = DiscoveredA2AClientClass(httpx_client=http_client, url=RECONCILIATION_AGENT_URL)
        print(f"ORCHESTRATOR: Sending A2A reconciliation request to {RECONCILIATION_AGENT_URL}")
        reco_response_sdk_obj = await reco_agent_client.send_message(request=a2a_payload_reco)
        if reco_response_sdk_obj and hasattr(reco_response_sdk_obj, 'message') and reco_response_sdk_obj.message and hasattr(reco_response_sdk_obj.message, 'parts') and reco_response_sdk_obj.message.parts:
            response_text_reco = reco_response_sdk_obj.message.parts[0].text
            print(f"ORCHESTRATOR: Received A2A reconciliation response: {response_text_reco[:200]}...")
            reco_response_dict = json.loads(response_text_reco)
        elif reco_response_sdk_obj and hasattr(reco_response_sdk_obj, 'error') and reco_response_sdk_obj.error:
            reco_response_dict = {"status": "error", "error_message": f"A2A Reconciliation call failed - agent error: {reco_response_sdk_obj.error.message}"}
        else:
            reco_response_dict = {"status": "error", "error_message": "A2A Reconciliation call failed - unexpected response structure"}
    except pydantic.ValidationError as ve:
        reco_response_dict = {"status": "error", "error_message": f"Pydantic validation error creating A2A Reconciliation request: {ve}"}
        print(f"PYDANTIC ERROR (Reconciliation): {ve}")
    except json.JSONDecodeError as e:
        reco_response_dict = {"status": "error", "error_message": f"Invalid JSON response from A2A (Reconciliation): {str(e)}"}
    except Exception as e:
        reco_response_dict = {"status": "error", "error_message": f"A2A Reconciliation communication error: {str(e)} \n{traceback.format_exc()}"}
        print(traceback.format_exc())
    final_report["reconciliation_report"] = reco_response_dict
    if reco_response_dict.get("status") == "success":
        final_report["overall_status"] = "success_reconciled"; final_report["message"] = "Reconciliation complete."
    else:
        final_report["overall_status"] = "error_in_reconciliation"; final_report["error_message"] = f"Reconciliation failed: {reco_response_dict.get('error_message', 'Unknown error')}"
    return final_report

async def close_shared_httpx_client():
    global shared_httpx_client
    if shared_httpx_client and not shared_httpx_client.is_closed:
        print("INFO: Closing shared httpx.AsyncClient instance.")
        await shared_httpx_client.aclose()
    shared_httpx_client = None

root_agent = LlmAgent(
    name=orchestrator_agent_card.name,
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=orchestrator_agent_card.description,
    instruction=(
        "You are the Vendor Reconciliation Orchestrator. Your primary goal is to reconcile an invoice with a Purchase Order (PO).\n\n"
        "**Your Main Tool:** `_orchestrate_po_reconciliation_tool`.\n\n"
        "**Interaction Flow & Logic:**\n"
        "1.  **Start:** Greet the user. Ask: 'Hello! Are you working with **new documents** you'd like to upload, or do you want to reconcile based on an **existing Purchase Order (PO) number** already in our system?'\n"
        "2.  **Handle User's Initial Choice:**\n"
        "    A.  If user indicates **'Existing PO'** or provides a PO number directly:\n"
        "        - Get the `po_number_input` from the user.\n"
        "        - Call `_orchestrate_po_reconciliation_tool` with just this `po_number_input`.\n"
        "    B.  If user indicates **'New Documents'** (implying new PO and likely new Invoice):\n"
        "        - Ask for the `new_po_file_path` (full local path to the new PO document).\n"
        "        - (Optional but good: you can ask for a target PO number they have in mind for this file, or let the tool extract it. For the tool, `po_number_input` can be omitted if `new_po_file_path` is given and the number is to be extracted from the file itself.)\n"
        "        - Then, ask for the `new_invoice_file_path` (full local path for the corresponding new invoice).\n"
        "        - Call `_orchestrate_po_reconciliation_tool` with `new_po_file_path` and `new_invoice_file_path` (and `po_number_input` if you asked for a target PO number for the new PO file).\n"
        "3.  **Interpret Tool Response & Follow Up (Iterative Process):**\n"
        "    The `_orchestrate_po_reconciliation_tool` tool will return a JSON response. Examine its `overall_status` and `context_po_number` (if present).\n"
        "    a.  If tool response has `overall_status: \"po_not_found_needs_file\"`:\n"
        "        - The tool provides `context_po_number`. Ask the user: 'PO \"[Value from tool's context_po_number]\" was not found. Please provide the full local file path for this new PO document.'\n"
        "        - Once user provides `new_po_file_path`: Call `_orchestrate_po_reconciliation_tool` tool AGAIN. Pass the `po_number_input` (which is `context_po_number` from previous tool response) AND the newly provided `new_po_file_path`.\n"
        "    b.  If tool response has `overall_status: \"po_secured_invoice_needed\"` (PO found/ingested, but no related invoice found in DB automatically):\n"
        "        - The tool provides `context_po_number`. Ask the user: 'PO \"[Value from tool's context_po_number]\" has been processed/found. However, no related invoice was found in the database. Do you have a new invoice file to upload for this PO? If yes, please provide its full local file path.'\n"
        "        - Once user provides `new_invoice_file_path`: Call `_orchestrate_po_reconciliation_tool` tool AGAIN. Pass the `po_number_input` (which is `context_po_number` from previous tool response) AND the newly provided `new_invoice_file_path`.\n"
        "    c.  If tool response indicates `overall_status: \"success_reconciled\"` or any other final status (e.g., `error`, `partial_success_..._only`):\n"
        "        - Present the full results (including `steps_taken`, `message_to_user` if any, and `reconciliation_report` if present from the tool's JSON response) clearly to the user.\n"
        "4.  **Clarity for File Paths:** Always request FULL LOCAL FILE PATHS.\n\n"
        "**Goal:** Guide the user to provide information step-by-step so you can eventually call `_orchestrate_po_reconciliation_tool` with enough arguments for it to either complete the reconciliation or return a status asking for the next specific piece of missing information (which you then ask the user for)."
    ),
    tools=[
        _orchestrate_po_reconciliation_tool
    ]
)