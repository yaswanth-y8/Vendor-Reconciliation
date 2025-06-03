# data_ingestion_agent/agent.py
import os
import json
from typing import Dict, Any,List
from google.adk.agents.llm_agent import LlmAgent
# from google.adk import AgentCard # Hypothetical import from your ADK
# from a2a.types import Part # Hypothetical import from your ADK
# --- Path Setup & other imports (process_raw_document_to_json, store_invoice/po_data) ---
import sys
project_root_di = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root_di not in sys.path: sys.path.insert(0, project_root_di)
from document_parser import process_raw_document_to_json
from database_manager import store_invoice_data, store_po_data
import google.generativeai as genai

# ---- AgentCard Definition (Hypothetical based on your snippet) ----
# These would be dynamically determined or configured if agents run on different ports/hosts
INGESTION_AGENT_HOST = os.getenv("DATA_INGESTION_AGENT_HOST", "localhost")
INGESTION_AGENT_PORT = int(os.getenv("DATA_INGESTION_AGENT_PORT", 8001)) # Example port

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
# --- End Hypothetical AgentCard and related types ---
# Define capabilities and skills for this agent's AgentCard
ingestion_capability = AgentCapability(
    name="_ingest_and_store_document_tool",
    description="Extracts data from a document file and stores it."
    # Add input/output schemas if your ADK supports it for tool discovery
)
ingestion_skill = AgentSkill(
    name="Document Ingestion Skill",
    description="Handles processing and storage of financial documents.",
    capabilities=[ingestion_capability]
)

data_ingestion_agent_card = AgentCard(
    name="data_ingestion_specialist_agent", # Must match name used by orchestrator
    description="Specialized agent for uploading raw documents, extracting data, and storing them.",
    url=f"http://{INGESTION_AGENT_HOST}:{INGESTION_AGENT_PORT}/invoke", # ADK endpoint
    version="1.0.0",
    defaultInputModes=["text/plain", "application/json"], # What this agent can receive
    defaultOutputModes=["application/json"], # What this agent produces
    capabilities=[], # Top-level capabilities if any
    skills=[ingestion_skill]
)
# In a real ADK system, this card might be registered with a central resolver.
print(f"DATA_INGESTION_AGENT: Defined AgentCard: {json.dumps(data_ingestion_agent_card.to_dict(), indent=2)}")
# --- End AgentCard Definition ---


if not os.getenv("GOOGLE_API_KEY"):
    print("CRITICAL WARNING (DataIngestionAgent): GOOGLE_API_KEY not set.")
elif not getattr(genai, 'API_KEY', None) and os.getenv("GOOGLE_API_KEY"):
    try: genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    except Exception as e: print(f"Error configuring GenAI in DataIngestionAgent: {e}")


def _ingest_and_store_document_tool(raw_document_file_path: str, document_type: str) -> dict:
    # ... (Implementation is THE SAME as your last working version)
    print(f"DATA_INGESTION_TOOL: Processing file='{raw_document_file_path}', type='{document_type}'")
    if document_type.lower() not in ["invoice", "purchase_order"]: return {"status": "error", "error_message": "Invalid document_type."}
    extraction_result = process_raw_document_to_json(raw_document_file_path, document_type)
    if extraction_result.get("status") != "success": return {"status": "error", "error_message": f"Extraction failed: {extraction_result.get('error_message')}", "details": extraction_result }
    doc_data = extraction_result.get("data"); doc_number_raw = doc_data.get("document_number") if doc_data else None
    if not doc_number_raw: return {"status": "error", "error_message": "Doc number missing."}
    doc_number = str(doc_number_raw).strip().upper()
    if not doc_number: return {"status": "error", "error_message": "Doc number empty."}
    stored = False
    if document_type.lower() == "invoice": stored = store_invoice_data(doc_number, extraction_result)
    elif document_type.lower() == "purchase_order": stored = store_po_data(doc_number, extraction_result)
    if stored: return {"status": "success", "message": f"{document_type.capitalize()} '{doc_number}' stored.", "full_extraction_result": extraction_result }
    else: return {"status": "error", "error_message": f"Failed to store {document_type} '{doc_number}'.", "full_extraction_result": extraction_result}


# This is the agent instance for this module
data_ingestion_llm_agent = LlmAgent(
    name=data_ingestion_agent_card.name, # Use name from AgentCard
    model=os.getenv("ADK_MODEL", "gemini-1.5-flash-latest"),
    description=data_ingestion_agent_card.description,
    instruction=(
        "You are a Data Ingestion Specialist. You will receive a command from an Orchestrator Agent "
        "via an A2A message. This message will effectively be a request to call your tool.\n"
        "The Orchestrator's message will implicitly (or explicitly if formatted as a tool call) "
        "tell you to use your `_ingest_and_store_document_tool` and will provide "
        "`raw_document_file_path` and `document_type` as arguments.\n"
        "Your ONLY task is to call this tool with the provided arguments "
        "and return its complete JSON result. Do not add any conversational fluff or summaries. "
        "The Orchestrator expects the raw JSON output of your tool."
    ),
    tools=[_ingest_and_store_document_tool]
)

# If running this agent directly with `adk run data_ingestion_agent/agent.py`
root_agent = data_ingestion_llm_agent