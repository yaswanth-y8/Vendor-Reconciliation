
import json
import httpx 
from typing import Dict, Any, Optional, List
import traceback
import os # For environment variables for timeouts etc.


class Part:
    def __init__(self, text: Optional[str] = None, inline_data: Optional[Dict] = None):
        self.text = text; self.inline_data = inline_data
    def to_dict(self):
        d = {}; 
        if self.text: d["text"] = self.text
        if self.inline_data: d["inline_data"] = self.inline_data
        return d
class MessageSendParams:
    def __init__(self, parts: List[Part]): self.parts = parts
    def to_dict(self): return {"parts": [p.to_dict() for p in self.parts]}

class ADKChatMessage: # Structure that ADK /run_sse endpoint might expect for a chat turn
    def __init__(self, role: str, parts: List[Part]):
        self.role = role; self.parts = parts
    def to_dict(self): return {"role": self.role, "parts": [p.to_dict() for p in self.parts]}

class ADKRunRequestPayload: # Structure that ADK /run_sse endpoint might expect
    def __init__(self, app_name:str, session_id:str, user_id:str, contents: List[ADKChatMessage], tools_config=None):
        self.app_name = app_name 
        self.session_id = session_id
        self.user_id = user_id
        self.contents = contents 
        self.tools_config = tools_config 
    def to_dict(self):
        return {
            "app_name": self.app_name, "session_id": self.session_id, "user_id": self.user_id,
            "contents": [c.to_dict() for c in self.contents],
            "tools_config": self.tools_config
        }

class A2AResponse:
    def __init__(self, status: str, data: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None):
        self.status = status
        self.data = data 
        self.error_message = error_message
    def to_dict(self):
        return {"status": self.status, "data": self.data, "error_message": self.error_message}



class A2AClient:
    def __init__(self):
        self.agent_urls: Dict[str, str] = {} 
        self.http_client = httpx.AsyncClient(timeout=float(os.getenv("A2A_TIMEOUT", "60.0"))) # Timeout for A2A calls
        print("A2AClient initialized (using real httpx.AsyncClient).")

    def register_agent_url(self, agent_name: str, base_url: str):
        
        self.agent_urls[agent_name] = base_url.rstrip('/')
        print(f"A2AClient: Registered agent '{agent_name}' at base URL '{base_url}'")

    async def send_message_to_sub_agent(
        self, 
        target_agent_name: str, 
        query_for_sub_agent_llm: str, 
        
        sub_agent_adk_app_name: str, # e.g., "data_ingestion_agent.agent"
        session_id: str = "a2a_session", # Manage sessions if sub-agent is stateful
        user_id: str = "orchestrator"
    ) -> A2AResponse:
        """
        Sends a message (query) to a target sub-agent's ADK endpoint and
        attempts to get a structured JSON response from its tool execution.
        """
        base_url = self.agent_urls.get(target_agent_name)
        if not base_url:
            return A2AResponse(status="error", error_message=f"Target agent '{target_agent_name}' URL not registered.")


        adk_endpoint_url = f"{base_url}/run_sse" # Common ADK endpoint for LlmAgent interaction

        print(f"A2A_CLIENT: Sending A2A message to '{target_agent_name}' at '{adk_endpoint_url}' with query: '{query_for_sub_agent_llm}'")

        
        request_payload = ADKRunRequestPayload(
            app_name=sub_agent_adk_app_name, 
            session_id=session_id,
            user_id=user_id,
            contents=[ADKChatMessage(role="user", parts=[Part(text=query_for_sub_agent_llm)])]
        ).to_dict()

        try:
            http_response = await self.http_client.post(adk_endpoint_url, json=request_payload)
            
            response_text = http_response.text
            
            tool_output_dict = None
            for line in response_text.splitlines():
                if line.startswith("data:"):
                    try:
                        event_data_str = line[len("data:"):].strip()
                        event_json = json.loads(event_data_str)
                        
                        if "content" in event_json and "parts" in event_json["content"]:
                            for part in event_json["content"]["parts"]:
                                if "functionResponse" in part and "response" in part["functionResponse"]:
                                    tool_output_dict = part["functionResponse"]["response"]
                                    print(f"A2A_CLIENT: Extracted tool_output_dict from {target_agent_name}: {tool_output_dict}")
                                    break 
                            if tool_output_dict:
                                break 
                    except json.JSONDecodeError:
                        
                        continue
                    except Exception as e_parse:
                        print(f"A2A_CLIENT: Error parsing SSE event from {target_agent_name}: {e_parse} on line: {line}")


            if tool_output_dict:
                
                return A2AResponse(status="success", data=tool_output_dict)
            else:
                
                final_text = ""
                for line in response_text.splitlines():
                     if line.startswith("data:"):
                        event_data_str = line[len("data:"):].strip()
                        event_json = json.loads(event_data_str)
                        if "content" in event_json and "parts" in event_json["content"]:
                            for part in event_json["content"]["parts"]:
                                if "text" in part: final_text += part["text"]
                
                error_msg_from_subagent = f"Sub-agent '{target_agent_name}' did not return a clear tool response. Final text: '{final_text}'. Full HTTP status: {http_response.status_code}"
                print(f"A2A_CLIENT: {error_msg_from_subagent}")
                
                if http_response.status_code >= 400:
                     error_msg_from_subagent = f"Sub-agent '{target_agent_name}' HTTP error {http_response.status_code}. Response: {response_text[:500]}"

                return A2AResponse(status="error", error_message=error_msg_from_subagent)

        except httpx.TimeoutException:
            return A2AResponse(status="error", error_message=f"A2A HTTP request to '{target_agent_name}' timed out.")
        except httpx.RequestError as exc:
            return A2AResponse(status="error", error_message=f"A2A HTTP request to '{target_agent_name}' failed: {exc}")
        except Exception as e:
            print(f"A2A_CLIENT: Unexpected error during send_message to '{target_agent_name}': {e}")
            traceback.print_exc()
            return A2AResponse(status="error", error_message=f"Unexpected error calling '{target_agent_name}': {str(e)}")


a2a_client = A2AClient()