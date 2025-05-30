import os
import json
from typing import Dict, Any, List
import google.generativeai as genai
from PIL import Image
import io
import re
import traceback


API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME_FROM_ENV = os.getenv("MODEL_NAME", "gemini-2.0-flash") 



def _get_mime_type(file_path: str) -> str:
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
    doc_type_display = "document"
    if document_type.lower() == "invoice":
        doc_type_display = "invoice"
    elif document_type.lower() == "purchase_order":
        doc_type_display = "purchase order"
    
   
    base_schema_fields = """
      "document_number": "string (The main identifying number of this document, e.g., INV-123 for an invoice, or PO-ABC for a purchase order)",
      "vendor_name": "string (Name of the supplier, seller, or vendor)",
      "date": "string (Main date of the document, preferably YYYY-MM-DD)",
      "total_amount": "float (The final, grand total amount)",
      "subtotal": "float (Amount before taxes, if available, otherwise null)",
      "tax_amount": "float (Total tax amount, if available, otherwise null)",
      "line_items": [
        {
          "description": "string (Item or service description)",
          "quantity": "integer (Number of units, if available, otherwise null)",
          "unit_price": "float (Price per unit, if available, otherwise null)",
          "line_total": "float (Total price for this line item, if available, otherwise null)"
        }
      ]"""

    # Add type-specific fields and instructions
    specific_instructions = ""
    if document_type.lower() == "invoice":
        json_schema_description = f"""
    {{
      {base_schema_fields},
      "related_po_number": "string (If this INVOICE clearly references a Purchase Order number, extract that PO number here. Look for labels like 'PO Number', 'P.O. #', 'Order Ref', 'Customer PO'. If no PO number is referenced, this should be null.)"
    }}
        """
        specific_instructions = """
    **Specific Instructions for INVOICE (`related_po_number`):**
    - Carefully scan the invoice for any explicitly mentioned Purchase Order number.
    - Common labels for PO numbers include: "PO Number", "P.O. #", "Order No.", "Order Reference", "Customer PO", "Ref. PO".
    - If such a labeled PO number is found, extract its value into the `related_po_number` field.
    - If no Purchase Order number is clearly referenced on the invoice, set `related_po_number` to `null`.

    **Example for `related_po_number` extraction from an INVOICE:**
    If an invoice contains:
    `Customer P.O.: CUST-ORDER-XYZ-789`
    Then the JSON output should include:
    `"related_po_number": "CUST-ORDER-XYZ-789"`
        """
    elif document_type.lower() == "purchase_order":
        json_schema_description = f"""
    {{
      {base_schema_fields}
      // POs typically do not reference an invoice number.
      // If there's any other relevant reference number specific to POs (e.g. quote_number), it could be added here.
      // For now, no extra reference field specific to POs.
    }}
        """
        specific_instructions = """
    **Specific Instructions for PURCHASE ORDER:**
    - Focus on accurately extracting the PO's own `document_number` (which is the PO number).
    - Other fields like vendor, date, total, and line items are also important.
        """
    else: 
        json_schema_description = f"""
    {{
      {base_schema_fields}
    }}
        """

    prompt = f"""
    You are an expert financial document parser. Analyze the content of the provided {doc_type_display}.
    Extract the key information and structure it strictly according to the following JSON schema.
    If a field is not found or not applicable, use `null` for its value (except for `line_items` which should be an empty array `[]` if no items are found).
    Ensure all monetary amounts are extracted as numbers (float or integer), not strings with currency symbols.
    For dates, if possible, normalize to YYYY-MM-DD format. If not, provide the date as it appears.
    {specific_instructions}

    JSON Schema to follow:
    ```json
    {json_schema_description}
    ```

    Now, please process the document and provide the extracted data in this JSON format.
    Output ONLY the JSON object. Do not include any other explanatory text, markdown formatting characters like ```json, or ``` at the beginning or end of the JSON output itself. Just the raw, valid JSON.
    """
    return prompt.strip()


def parse_document_with_gemini(file_path: str, document_type: str) -> Dict[str, Any]:
    current_model_name = MODEL_NAME_FROM_ENV 
    print(f"GEMINI_PARSER: Processing document '{file_path}' as '{document_type}' with model '{current_model_name}'")

    if not API_KEY:
        return {"error": "GOOGLE_API_KEY not configured for Gemini parser. Cannot proceed."}
    if not current_model_name:
        return {"error": "MODEL_NAME not configured for Gemini parser. Cannot proceed."}

    generative_model_instance = None 
    try:
        generative_model_instance = genai.GenerativeModel(
            model_name=current_model_name,
        )
        print(f"GEMINI_PARSER: Successfully initialized model instance for '{current_model_name}'")

        with open(file_path, "rb") as f:
            file_bytes = f.read()
        
        mime_type = _get_mime_type(file_path)
        if mime_type == "application/octet-stream" and not any(file_path.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"]):
             print(f"GEMINI_PARSER: Passing file {file_path} with generic MIME type {mime_type} to Gemini as it's an unknown common type.")

        document_part = {"mime_type": mime_type, "data": file_bytes}
        prompt = _build_gemini_extraction_prompt(document_type) # This now generates type-specific prompt
        
        print(f"GEMINI_PARSER: Sending request to Gemini for {file_path}...")
        response = generative_model_instance.generate_content([prompt, document_part])

        extracted_json_str = ""
        if not response.parts:
            print("GEMINI_PARSER: Gemini response had no parts.")
            error_message = "No content parts returned from Gemini."
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                error_message = f"Content generation blocked. Reason: {response.prompt_feedback.block_reason}."
                if hasattr(response.prompt_feedback, 'safety_ratings') and response.prompt_feedback.safety_ratings:
                    error_message += f" Safety Ratings: {response.prompt_feedback.safety_ratings}"
            elif hasattr(response, 'candidates') and response.candidates and response.candidates[0].finish_reason.name != "STOP":
                 error_message = f"Content generation finished with reason: {response.candidates[0].finish_reason.name}."
            print(f"GEMINI_PARSER: {error_message}")
            return {"error": error_message, "raw_response": str(response)}

        try:
            extracted_json_str = response.text 
        except ValueError as ve:
            print(f"GEMINI_PARSER: Could not directly get .text from response (ValueError: {ve}). Inspecting parts.")
            for part in response.parts:
                if hasattr(part, "text"): extracted_json_str += part.text
                else: print(f"GEMINI_PARSER: Encountered non-text part: {type(part)}")
        
        if not extracted_json_str.strip():
            print("GEMINI_PARSER: Extracted text from Gemini response is empty.")
            return {"error": "Empty text content returned from Gemini.", "raw_response": str(response)}

        print(f"GEMINI_PARSER: Raw response text snippet: {extracted_json_str[:500]}...")
        
        json_str_to_parse = extracted_json_str.strip()
        if json_str_to_parse.startswith("```json"): json_str_to_parse = json_str_to_parse[7:]
        if json_str_to_parse.endswith("```"): json_str_to_parse = json_str_to_parse[:-3]
        json_str_to_parse = json_str_to_parse.strip()

        try:
            parsed_gemini_data = json.loads(json_str_to_parse)
            return parsed_gemini_data 
        except json.JSONDecodeError as json_e:
            print(f"GEMINI_PARSER: Failed to decode JSON from Gemini response: {json_e}")
            print(f"GEMINI_PARSER: String that failed parsing (len {len(json_str_to_parse)}): '{json_str_to_parse[:1000]}'")
            return {"error": "Gemini response was not valid JSON.", "raw_response": extracted_json_str}

    except Exception as e:
        print(f"GEMINI_PARSER: An unexpected error occurred in parse_document_with_gemini: {type(e).__name__} - {e}")
        print(traceback.format_exc())
        error_detail = f"Unexpected error during Gemini processing: {type(e).__name__} - {e}."
        if generative_model_instance is None: 
             error_detail += f" Failed to initialize Gemini model '{current_model_name}'. Check API Key and model name."
        return {"error": error_detail}

# ... process_raw_document_to_json function remains the same, but it will now pass the correct "purchase_order" type ...
# and the `gemini_extracted_data` will reflect the schema used for POs (i.e., no `related_invoice_number` unless you add it back for other reasons)
def process_raw_document_to_json(raw_document_file_path: str, document_type: str) -> Dict[str, Any]:
    if not os.path.exists(raw_document_file_path):
        return {"status": "error", "error_message": f"Raw document file not found: {raw_document_file_path}"}

    print(f"PROCESSOR: Starting Gemini extraction for: {raw_document_file_path} as type '{document_type}'") # Log the type
    gemini_extracted_data = parse_document_with_gemini(raw_document_file_path, document_type)

    if "error" in gemini_extracted_data:
        return {
            "status": "error",
            "error_message": f"Gemini parsing failed: {gemini_extracted_data.get('error', 'Unknown Gemini error')}",
            "raw_gemini_response": gemini_extracted_data.get('raw_response')
        }
    else:
        data_payload = {
            "document_number": gemini_extracted_data.get("document_number"),
            "vendor_name": gemini_extracted_data.get("vendor_name"),
            "date": gemini_extracted_data.get("date"),
            "total_amount": float(gemini_extracted_data.get("total_amount", 0.0) or 0.0),
            "subtotal": float(gemini_extracted_data.get("subtotal", 0.0) or 0.0),
            "tax_amount": float(gemini_extracted_data.get("tax_amount", 0.0) or 0.0),
            "line_items": gemini_extracted_data.get("line_items", []),
            "confidence_score": gemini_extracted_data.get("confidence_score", 0.85) 
        }
        # Add type-specific fields if they exist in Gemini's output based on the prompt
        if document_type.lower() == "invoice":
            data_payload["related_po_number"] = gemini_extracted_data.get("related_po_number")
    
        
        return {
            "status": "success",
            "document_type": document_type,
            "data": data_payload
        }

