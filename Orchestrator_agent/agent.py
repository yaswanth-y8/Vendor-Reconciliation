# orchestrator_agent/agent.py
import os
import json
from typing import Dict, Any, Optional
from google.adk.agents.llm_agent import LlmAgent
from dotenv import load_dotenv
import asyncio # If sub-agent calls are async

# Adjust import paths for sub-agents and shared_services
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from Data_ingestion_agent.agent import root_agent 
from Reconciliation_agent.agent import root_agent 
from database_manager import get_invoice_by_number, get_po_by_number 


if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (OrchestratorAgent): GOOGLE_API_KEY not found. Agent will fail.")



async def _get_final_agent_response(agent_instance: LlmAgent, query: str) -> str:
    """
    Calls a sub-agent's chat method and aggregates its response.
    This needs to be adapted based on how your ADK agent.chat() actually returns data.
    If it's async and yields events, you need to consume them.
    """
    print(f"ORCHESTRATOR_HELPER: Calling sub-agent '{agent_instance.name}' with query: '{query}'")
    final_response_text = ""
    # Assuming agent.chat() is async and returns a generator of event-like objects
    # This is a common pattern for ADK. If it's synchronous and returns a string, simplify this.
    try:
        # The actual ADK `run_async` or `chat_async` might be needed here,
        # or if `chat` can be awaited if it's an async method returning final string.
        # For simplicity, let's assume a hypothetical sync `chat_and_get_final_text` method
        # If `chat` is a generator:
        # async for event in agent_instance.chat(query): # This might be how ADK works
        #     if isinstance(event, dict) and "content" in event and "parts" in event["content"]:
        #         for part in event["content"]["parts"]:
        #             if "text" in part:
        #                 final_response_text += part["text"]
        #     elif isinstance(event, str): # Simpler case
        #          final_response_text += event

        # If agent.chat() directly returns the final JSON string (less likely for streaming agents)
        # response = agent_instance.chat(query) 
        # final_response_text = response

        # This part is highly dependent on the ADK's `Agent.chat()` actual implementation.
        # Let's mock a direct call and assume it returns a JSON string for now for the tool.
        # In a real scenario, this tool would use ADK's mechanism to invoke another agent.
        # For now, we will directly call the sub-agent's TOOLS for simplicity,
        # as true agent-to-agent chat invocation via ADK needs ADK framework support.
        
        # --- SIMPLIFIED APPROACH: Orchestrator directly calls sub-agent's underlying Python tool functions ---
        # This bypasses the sub-agent's LLM for these tool calls, making the Orchestrator's LLM do more.
        # A true sub-agent delegation would involve the Orchestrator's LLM forming a query FOR the sub-agent.
        
        # For this example, let's make the orchestrator tools call the Python functions directly
        # that are also tools of the sub-agents. This is less "agentic" for delegation but simpler.
        # If we want true agent-to-agent, the tool would be:
        # async def _delegate_to_data_ingestion_agent_tool(query_for_ingestion_agent: str) -> str:
        #     return await _get_final_agent_response(data_ingestion_agent, query_for_ingestion_agent)

        # For now, the orchestrator's main tool `_orchestrate_reconciliation_tool`
        # will directly call the necessary Python functions from data_ingestion_agent.agent
        # and reconciliation_processing_agent.agent.
        # This means `_process_and_store_document_tool` and `_reconcile_from_db_by_numbers_tool` etc.
        # need to be importable if called directly.

        raise NotImplementedError("True agent-to-agent chat delegation needs specific ADK mechanism. "
                                  "The orchestrator will directly call underlying tool functions for now.")

    except Exception as e:
        print(f"Error calling sub-agent '{agent_instance.name}': {e}")
        return json.dumps({"status": "error", "error_message": f"Failed to communicate with {agent_instance.name}: {str(e)}"})
    # return final_response_text


# The previous `process_reconciliation_scenarios` is a good candidate for the orchestrator's main tool.
# It already calls the underlying Python functions that are now conceptually part of the sub-agents.
def _orchestrate_reconciliation_tool(
    invoice_file_path: Optional[str] = None, 
    po_file_path: Optional[str] = None,
    invoice_number_db: Optional[str] = None,
    po_number_db: Optional[str] = None
    # po_number_on_invoice_to_check is removed as reconciliation logic handles related_po_number
    ) -> dict:
    """
    TOOL (Orchestrator): Manages different vendor reconciliation scenarios by coordinating
    data ingestion (extraction & storage) and reconciliation sub-processes.
    This tool directly calls the necessary Python functions that would be tools of sub-agents.
    """
   
    from Data_ingestion_agent.agent import _process_and_store_document_tool as ingest_doc_tool
    from Reconciliation_agent.agent import _reconcile_from_db_by_numbers_tool, _reconcile_with_provided_data_tool, _perform_reconciliation_logic
    
    print(f"ORCHESTRATOR_TOOL: _orchestrate_reconciliation_tool called with: "
          f"inv_file='{invoice_file_path}', po_file='{po_file_path}', "
          f"inv_num_db='{invoice_number_db}', po_num_db='{po_number_db}'")

    final_result: Dict[str, Any] = {"scenario_details": []}
    invoice_data_for_reco: Optional[Dict[str, Any]] = None # This will hold the *full extraction object*
    po_data_for_reco: Optional[Dict[str, Any]] = None     # This will hold the *full extraction object*

    # --- "Data Ingestion" Phase ---
    if invoice_file_path:
        scenario_msg = f"Task: Process new invoice file: '{invoice_file_path}'"
        final_result["scenario_details"].append(scenario_msg)
        print(f"ORCHESTRATOR: {scenario_msg}")
        # Call DataIngestionAgent's capability
        ingestion_outcome = ingest_doc_tool(raw_document_file_path=invoice_file_path, document_type="invoice")
        final_result["invoice_ingestion_result"] = ingestion_outcome
        if ingestion_outcome.get("status") == "success":
            # For reconciliation, we need the *full extraction object* that was stored or returned
            # The ingest_doc_tool returns the extraction_result if store is successful
            # Let's re-fetch from DB to ensure we use the stored version for consistency
            stored_inv_num = ingestion_outcome.get("document_number")
            if stored_inv_num:
                invoice_data_for_reco = get_invoice_by_number(stored_inv_num) # From shared_services.database_manager
        else: # Ingestion error
            return {"status": "error", "error_message": f"Invoice ingestion failed: {ingestion_outcome.get('error_message')}", "details": final_result}
            
    elif invoice_number_db:
        scenario_msg = f"Task: Retrieve existing invoice '{invoice_number_db}' from DB."
        final_result["scenario_details"].append(scenario_msg)
        print(f"ORCHESTRATOR: {scenario_msg}")
        invoice_data_for_reco = get_invoice_by_number(invoice_number_db)
        if not invoice_data_for_reco:
            return {"status": "error", "error_message": f"Invoice '{invoice_number_db}' not found in DB.", "details": final_result}
        final_result["invoice_ingestion_result"] = {"status": "success", "message": "Retrieved from DB", 
                                                 "document_number": invoice_data_for_reco.get("data",{}).get("document_number")}
    
    if po_file_path:
        scenario_msg = f"Task: Process new PO file: '{po_file_path}'"
        final_result["scenario_details"].append(scenario_msg)
        print(f"ORCHESTRATOR: {scenario_msg}")
        ingestion_outcome = ingest_doc_tool(raw_document_file_path=po_file_path, document_type="purchase_order")
        final_result["po_ingestion_result"] = ingestion_outcome
        if ingestion_outcome.get("status") == "success":
            stored_po_num = ingestion_outcome.get("document_number")
            if stored_po_num:
                po_data_for_reco = get_po_by_number(stored_po_num)
        else: # Ingestion error
            return {"status": "error", "error_message": f"PO ingestion failed: {ingestion_outcome.get('error_message')}", "details": final_result}

    elif po_number_db: 
        scenario_msg = f"Task: Retrieve existing PO '{po_number_db}' from DB."
        final_result["scenario_details"].append(scenario_msg)
        print(f"ORCHESTRATOR: {scenario_msg}")
        po_data_for_reco = get_po_by_number(po_number_db)
        if not po_data_for_reco:
            return {"status": "error", "error_message": f"PO '{po_number_db}' not found in DB.", "details": final_result}
        final_result["po_ingestion_result"] = {"status": "success", "message": "Retrieved from DB",
                                              "document_number": po_data_for_reco.get("data",{}).get("document_number")}
            
    elif invoice_data_for_reco: # Invoice is available, try to find its related PO in DB
        inv_data_nested = invoice_data_for_reco.get("data", {})
        related_po_num_on_invoice = inv_data_nested.get("related_po_number")
        if related_po_num_on_invoice:
            scenario_msg = f"Task: Invoice data available. Finding related PO '{related_po_num_on_invoice}' in DB."
            final_result["scenario_details"].append(scenario_msg)
            print(f"ORCHESTRATOR: {scenario_msg}")
            po_data_for_reco = get_po_by_number(related_po_num_on_invoice)
            if po_data_for_reco:
                final_result["po_ingestion_result"] = {"status": "success", "message": f"Retrieved related PO '{related_po_num_on_invoice}' from DB",
                                                      "document_number": po_data_for_reco.get("data",{}).get("document_number")}
            else: # Related PO not found
                final_result["po_ingestion_result"] = {"status": "not_found", "message": f"Related PO '{related_po_num_on_invoice}' not found in DB."}
        else:
            scenario_msg = "Task: Invoice data available, but no related PO number found on it to search in DB."
            final_result["scenario_details"].append(scenario_msg)
            final_result["po_ingestion_result"] = {"status": "not_applicable", "message": scenario_msg}

    # --- "Reconciliation" Phase ---
    if invoice_data_for_reco and po_data_for_reco:
        # Ensure both are valid extraction objects before proceeding
        if invoice_data_for_reco.get("status") != "success" or po_data_for_reco.get("status") != "success":
            final_result["status"] = "error"
            final_result["error_message"] = "One or both documents for reconciliation have an error status from ingestion/retrieval."
            final_result["reconciliation_outcome"] = {"status": "not_performed", "reason": final_result["error_message"]}
            return final_result

        scenario_msg = "Task: Both invoice and PO data ready. Performing reconciliation."
        final_result["scenario_details"].append(scenario_msg)
        print(f"ORCHESTRATOR: {scenario_msg}")
        
        # Call ReconciliationAgent's capability (using the _perform_reconciliation_logic directly here for simplicity)
        # A true delegation would be:
        # reco_query = f"_reconcile_with_provided_data_tool: {{ \"invoice_data_json_str\": \"{json.dumps(invoice_data_for_reco)}\", \"po_data_json_str\": \"{json.dumps(po_data_for_reco)}\" }}"
        # reco_response_str = await _get_final_agent_response(reconciliation_processing_agent, reco_query)
        # reconciliation_output = json.loads(reco_response_str)
        
        reconciliation_output = _perform_reconciliation_logic(invoice_data_for_reco, po_data_for_reco)
        final_result["reconciliation_outcome"] = reconciliation_output
        
        if reconciliation_output.get("status") == "success":
            final_result["status"] = "success" 
            final_result["message"] = "Reconciliation process complete."
        else:
            final_result["status"] = "error"
            final_result["error_message"] = f"Reconciliation sub-process failed: {reconciliation_output.get('error_message')}"
            
    elif invoice_data_for_reco and not po_data_for_reco:
        final_result["status"] = "partial_success_invoice_only"
        final_result["message"] = "Invoice processed/found. Corresponding Purchase Order was not provided or found for reconciliation."
        final_result["scenario_details"].append(final_result["message"])
    elif po_data_for_reco and not invoice_data_for_reco:
        final_result["status"] = "partial_success_po_only"
        final_result["message"] = "Purchase Order processed/found. Corresponding Invoice was not provided or found for reconciliation."
        final_result["scenario_details"].append(final_result["message"])
    else: 
        final_result["status"] = "error"
        final_result["error_message"] = "Insufficient data: Neither invoice nor PO could be loaded or processed for reconciliation."
        final_result["scenario_details"].append(final_result["error_message"])
        
    return final_result


orchestrator_agent_instance = LlmAgent(
    name="vendor_reconciliation_orchestrator_agent", 
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=(
        "Main orchestrator AI agent for vendor reconciliation. It coordinates with data ingestion "
        "and reconciliation specialist agents to process user requests."
    ),
    instruction=(
        "You are the Vendor Reconciliation Orchestrator. Your job is to understand the user's request and manage the workflow by deciding which information to collect and then calling the `_orchestrate_reconciliation_tool`.\n\n"
        "**Interaction Flow:**\n"
        "1.  Greet the user and ask for their goal (e.g., upload new invoice, upload new PO, reconcile specific documents by number, reconcile new documents by file path).\n"
        "2.  Based on their goal, ask for the **specific pieces of information** needed by the `_orchestrate_reconciliation_tool` for that scenario. The tool can accept:\n"
        "    - `invoice_file_path` (string, optional): Full local path to a new invoice file.\n"
        "    - `po_file_path` (string, optional): Full local path to a new PO file.\n"
        "    - `invoice_number_db` (string, optional): Document number of an invoice already in the database.\n"
        "    - `po_number_db` (string, optional): Document number of a PO already in the database.\n"
        "3.  **Scenarios for the `_orchestrate_reconciliation_tool`:**\n"
        "    a.  **New Invoice & New PO:** Get `invoice_file_path` and `po_file_path`.\n"
        "    b.  **New Invoice, Existing PO:** Get `invoice_file_path` and `po_number_db`.\n"
        "    c.  **New PO, Existing Invoice:** Get `po_file_path` and `invoice_number_db`.\n"
        "    d.  **Both in DB:** Get `invoice_number_db` and `po_number_db`.\n"
        "    e.  **Upload/Store only Invoice:** Get `invoice_file_path`.\n"
        "    f.  **Upload/Store only PO:** Get `po_file_path`.\n"
        "4.  Once you have the necessary arguments for one of these scenarios, call `_orchestrate_reconciliation_tool` with ONLY those arguments. Do not pass null for arguments that are not relevant to the user's immediate request if they didn't provide them.\n"
        "5.  Present the ENTIRE JSON result from the `_orchestrate_reconciliation_tool` back to the user in a clear, summarized, human-readable format. Include all sub-statuses (ingestion, reconciliation outcome) and any error messages.\n\n"
        "**Example Clarification:** If user says 'reconcile PO 123', ask 'Is invoice 123 new (provide file path) or existing (provide invoice number)?'.\n"
        "Do NOT attempt to extract data or access the database yourself. The tool handles all that."
    ),
    tools=[
        _orchestrate_reconciliation_tool 
    ]
)

