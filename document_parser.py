import os
import json
from typing import Dict, Any, List
import google.generativeai as genai
from PIL import Image 
import io
import re
import traceback 


API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME_FROM_ENV = os.getenv("MODEL_NAME", "gemini-1.5-flash-latest") 

if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
        print(f"SUCCESS (document_parser.py): google.generativeai configured with API key for model '{MODEL_NAME_FROM_ENV}'.")
    except Exception as e:
        print(f"ERROR (document_parser.py): Failed to configure google.generativeai: {e}")
        
else:
    print("CRITICAL WARNING (document_parser.py): GOOGLE_API_KEY not found in environment. Gemini calls will fail.")


def _get_mime_type(file_path: str) -> str:
    """Determines the MIME type based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf": return "application/pdf"
    elif ext == ".png": return "image/png"
    elif ext in [".jpg", ".jpeg"]: return "image/jpeg"
    elif ext == ".webp": return "image/webp"
    elif ext == ".heic": return "image/heic"
    elif ext == ".heif": return "image/heif"
    else:
        print(f"Warning: Unknown MIME type for extension {ext} in {file_path}. Attempting application/octet-stream.")
        return "application/octet-stream"

def _build_gemini_extraction_prompt(document_type: str) -> str:
    json_schema_description = """
    {
      "document_number": "string (invoice or receipt number)",
      "vendor_name": "string (name of the supplier or vendor)",
      "date": "string (document date, preferably YYYY-MM-DD, or as seen)",
      "total_amount": "float (the final total amount due or paid)",
      "subtotal": "float (amount before taxes, if available, otherwise null)",
      "tax_amount": "float (total tax amount, if available, otherwise null)",
      "line_items": [
        {
          "description": "string (item description)",
          "quantity": "integer (number of units, if available)",
          "unit_price": "float (price per unit, if available)",
          "line_total": "float (total price for this line item, if available)"
        }
      ]
    }
    """ 
    prompt = f"""
    You are an expert financial document parser. Analyze the content of the provided {document_type}.
    Extract the key information and structure it strictly according to the following JSON schema.
    If a field is not found or not applicable, use `null` for its value (except for `line_items` which should be an empty array [] if no items are found).
    Ensure all monetary amounts are extracted as numbers (float or integer), not strings with currency symbols.
    For dates, if possible, normalize to YYYY-MM-DD format. If not, provide the date as it appears.
    Line items are particularly important; extract as many as possible with their details. If quantity, unit_price, or line_total are not clearly separable for an item, you can use null for those sub-fields.

    JSON Schema to follow:
    ```json
    {json_schema_description}
    ```

    Now, please process the document and provide the extracted data in this JSON format.
    Output ONLY the JSON object. Do not include any other explanatory text before or after the JSON.
    """
    return prompt.strip()


def parse_document_with_gemini(file_path: str, document_type: str) -> Dict[str, Any]:
    """
    Uses a Gemini model to parse a document and extract structured data.
    """
    
    current_model_name = MODEL_NAME_FROM_ENV 
    print(f"GEMINI_PARSER: Processing document '{file_path}' as '{document_type}' with model '{current_model_name}'")

    if not API_KEY:
        return {"error": "GOOGLE_API_KEY not configured for Gemini parser. Cannot proceed."}
    if not current_model_name:
        return {"error": "MODEL_NAME not configured for Gemini parser. Cannot proceed."}

    generative_model_instance = None 
    try:
        
        generative_model_instance = genai.GenerativeModel(current_model_name)
        print(f"GEMINI_PARSER: Successfully initialized model instance for '{current_model_name}'")

        with open(file_path, "rb") as f:
            file_bytes = f.read()
        
        mime_type = _get_mime_type(file_path)
        
        if mime_type == "application/octet-stream" and not any(file_path.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"]):
             print(f"GEMINI_PARSER: Passing file {file_path} with generic MIME type {mime_type} to Gemini.")
           

        document_part = {"mime_type": mime_type, "data": file_bytes}
        prompt = _build_gemini_extraction_prompt(document_type)
        
        print(f"GEMINI_PARSER: Sending request to Gemini for {file_path}...")
        response = generative_model_instance.generate_content([prompt, document_part])

        
        if not response.parts: 
            print("GEMINI_PARSER: Gemini response had no parts or text.")
            error_message = "No content parts returned from Gemini."
            
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                error_message = f"Content generation blocked. Reason: {response.prompt_feedback.block_reason}."
                if response.prompt_feedback.safety_ratings:
                    error_message += f" Safety Ratings: {response.prompt_feedback.safety_ratings}"
            elif hasattr(response, 'candidates') and response.candidates and response.candidates[0].finish_reason.name != "STOP":
                error_message = f"Content generation finished with reason: {response.candidates[0].finish_reason.name}."

            print(f"GEMINI_PARSER: {error_message}")
            return {"error": error_message, "raw_response": str(response)} 

        
        extracted_json_str = ""
        try:
            extracted_json_str = response.text 
        except ValueError as ve: 
            print(f"GEMINI_PARSER: Could not directly get .text from response (ValueError: {ve}). Inspecting parts.")
            for part in response.parts:
                if hasattr(part, "text"): 
                    extracted_json_str += part.text
                else: 
                    print(f"GEMINI_PARSER: Encountered non-text part: {type(part)}")


        if not extracted_json_str.strip():
            print("GEMINI_PARSER: Extracted text from Gemini response is empty.")
            return {"error": "Empty text content returned from Gemini.", "raw_response": str(response)}

        print(f"GEMINI_PARSER: Raw response text snippet: {extracted_json_str[:300]}...")
        
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", extracted_json_str, re.MULTILINE | re.DOTALL)
        if json_match:
            json_str_to_parse = json_match.group(1).strip()
        else:
            json_str_to_parse = extracted_json_str.strip() 

        try:
            parsed_gemini_data = json.loads(json_str_to_parse)
            return parsed_gemini_data 
        except json.JSONDecodeError as json_e:
            print(f"GEMINI_PARSER: Failed to decode JSON from Gemini response: {json_e}")
            print(f"GEMINI_PARSER: String that failed parsing: '{json_str_to_parse}'")
            return {"error": "Gemini response was not valid JSON.", "raw_response": extracted_json_str}

    except Exception as e:
        print(f"GEMINI_PARSER: An unexpected error occurred in parse_document_with_gemini: {type(e).__name__} - {e}")
        print(traceback.format_exc())
        error_detail = f"Unexpected error during Gemini processing: {type(e).__name__} - {e}."
        
        if generative_model_instance is None:
             error_detail += f" Failed to initialize Gemini model '{current_model_name}'. Check API Key and model name."
        return {"error": error_detail}


def process_raw_document_to_json(raw_document_file_path: str, document_type: str) -> Dict[str, Any]:
    if not os.path.exists(raw_document_file_path):
        return {"status": "error", "error_message": f"Raw document file not found: {raw_document_file_path}"}

    print(f"PROCESSOR: Starting Gemini extraction for: {raw_document_file_path}")
    gemini_extracted_data = parse_document_with_gemini(raw_document_file_path, document_type)

    if "error" in gemini_extracted_data:
        return {
            "status": "error",
            "error_message": f"Gemini parsing failed: {gemini_extracted_data.get('error', 'Unknown Gemini error')}",
            "raw_gemini_response": gemini_extracted_data.get('raw_response') 
        }
    else:
        
        required_keys = ["document_number", "vendor_name", "date", "total_amount"] 
        missing_keys = [key for key in required_keys if key not in gemini_extracted_data or gemini_extracted_data[key] is None]
        if missing_keys:
            print(f"GEMINI_PARSER: Warning - Gemini response is missing or has null for required keys: {missing_keys}")
            
        
        return {
            "status": "success",
            "document_type": document_type,
            "data": {
                "document_number": gemini_extracted_data.get("document_number"),
                "vendor_name": gemini_extracted_data.get("vendor_name"),
                "date": gemini_extracted_data.get("date"),
                "total_amount": float(gemini_extracted_data.get("total_amount", 0.0) or 0.0),
                "subtotal": float(gemini_extracted_data.get("subtotal", 0.0) or 0.0),
                "tax_amount": float(gemini_extracted_data.get("tax_amount", 0.0) or 0.0),
                "line_items": gemini_extracted_data.get("line_items", []),
                "confidence_score": gemini_extracted_data.get("confidence_score", 0.85) 
            }
        }

