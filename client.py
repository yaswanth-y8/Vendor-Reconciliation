# a2a_comms/client.py
import json
import httpx # For simulating HTTP calls to agent endpoints
from typing import Dict, Any, Optional, List # Keep standard List for now


# In a real ADK project, you'd import these from a2a.types
class Part:
    def __init__(self, text: Optional[str] = None, inline_data: Optional[Dict] = None):
        self.text = text
        self.inline_data = inline_data
    def to_dict(self):
        d = {}
        if self.text: d["text"] = self.text
        if self.inline_data: d["inline_data"] = self.inline_data
        return d

class MessageSendParams:
    def __init__(self, parts: List[Part]):
        self.parts = parts
    def to_dict(self):
        return {"parts": [p.to_dict() for p in self.parts]}

class SendMessageRequest:
    def __init__(self, agent_id_or_url: str, message: MessageSendParams, # Add other params if needed
                 session_id: Optional[str] = None, user_id: Optional[str] = None):
        self.agent_id_or_url = agent_id_or_url
        self.message = message
        self.session_id = session_id
        self.user_id = user_id
    def to_dict(self):
        return {
            "target_agent": self.agent_id_or_url, # Simplified
            "message": self.message.to_dict(),
            "session_id": self.session_id,
            "user_id": self.user_id
        }

class SendMessageSuccessResponse: # Simplified
    def __init__(self, status: str, content: Optional[Dict[str, Any]] = None, message: Optional[str] = None):
        self.status = status # e.g., "success", "tool_executed"
        self.content = content # This would be the structured JSON result from the sub-agent's tool
        self.message = message # Or a textual summary from sub-agent's LLM
    def to_dict(self):
        return {"status": self.status, "content": self.content, "message": self.message}

class SendMessageErrorResponse: # Simplified
    def __init__(self, status: str, error_message: str):
        self.status = "error"
        self.error_message = error_message
    def to_dict(self):
        return {"status": self.status, "error_message": self.error_message}

# --- End Hypothetical A2A Types ---


class A2AClient:
    def __init__(self, agent_card_resolver: Optional[Any] = None):
        
        self.agent_urls = {}
        print("A2AClient initialized (mock).")

    def register_agent_url(self, agent_name: str, url: str):
        self.agent_urls[agent_name] = url
        print(f"A2AClient: Registered agent '{agent_name}' at URL '{url}'")

    

    async def send_message(self, request: SendMessageRequest) -> Dict[str, Any]:
        target_agent_name_for_mock = request.agent_id_or_url # Assume this is the agent's registered name
        target_url = self.agent_urls.get(target_agent_name_for_mock)

        print(f"A2A_CLIENT: Attempting to send message to agent '{target_agent_name_for_mock}' "
              f"(resolved URL: '{target_url}') " # Log the resolved URL
              f"with query text: '{request.message.parts[0].text if request.message.parts else 'No text'}'")

        # If we were making real HTTP calls, we'd use target_url.
        # For the mock, we use target_agent_name_for_mock to decide which Python function to call.
        
        if not target_url: # Check if the agent name was even registered
             return SendMessageErrorResponse(status="error", error_message=f"Target agent '{target_agent_name_for_mock}' not registered with A2AClient or URL not found.").to_dict()

        # --- MOCKING SUB-AGENT TOOL EXECUTION (using target_agent_name_for_mock) ---
        query_text_for_sub_agent = request.message.parts[0].text if request.message.parts else ""
        # ... (parsing tool_name_from_query and tool_args as before) ...
        try:
            tool_name_from_query, args_json_str = query_text_for_sub_agent.split(":", 1)
            tool_name_from_query = tool_name_from_query.strip()
            tool_args = json.loads(args_json_str.strip())
        except Exception as e:
            return SendMessageErrorResponse(status="error", error_message=f"Could not parse tool call from query: '{query_text_for_sub_agent}'. Error: {e}").to_dict()


        tool_response_content = None
        
        if target_agent_name_for_mock == "data_ingestion_specialist_agent": 
            from Data_ingestion_agent.agent import _ingest_and_store_document_tool
            if tool_name_from_query == "_ingest_and_store_document_tool":
                tool_response_content = _ingest_and_store_document_tool(**tool_args)
            
        
        elif target_agent_name_for_mock == "reconciliation_specialist_agent": 
            from Reconciliation_agent.agent import _perform_reconciliation_logic_tool
            if tool_name_from_query == "_perform_reconciliation_logic_tool":
                tool_response_content = _perform_reconciliation_logic_tool(**tool_args)
            
        else:
            return SendMessageErrorResponse(status="error", error_message=f"Mock A2A: Unknown target agent name '{target_agent_name_for_mock}' for direct tool call.").to_dict()

        if tool_response_content is None: # If tool name wasn't matched inside the if/elifs
             return SendMessageErrorResponse(status="error", error_message=f"Mock A2A: Tool '{tool_name_from_query}' not found for agent '{target_agent_name_for_mock}'.").to_dict()

        return SendMessageSuccessResponse(status="success_tool_executed", content=tool_response_content).to_dict()
# Global A2A client instance
a2a_client = A2AClient() 