import sqlite3
import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import re # For cleaning date strings

DB_FILE_NAME = "reconciliation_data.db"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, DB_FILE_NAME)

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """Creates the necessary tables if they don't already exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_number TEXT PRIMARY KEY,
            vendor_name TEXT,
            invoice_date TEXT, -- Store as YYYY-MM-DD TEXT for SQLite date functions
            total_amount REAL,
            related_po_number TEXT,
            full_extracted_data_json TEXT,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invoices_related_po
        ON invoices (related_po_number)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invoices_vendor_name
        ON invoices (vendor_name)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invoices_invoice_date
        ON invoices (invoice_date)
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_number TEXT PRIMARY KEY,
            vendor_name TEXT,
            po_date TEXT, -- Store as YYYY-MM-DD TEXT for SQLite date functions
            total_amount REAL,
            full_extracted_data_json TEXT,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_pos_vendor_name
        ON purchase_orders (vendor_name)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_pos_po_date
        ON purchase_orders (po_date)
    ''')

    conn.commit()
    conn.close()
    print(f"DB_MGR: Database '{DB_PATH}' initialized/checked successfully.")

# Call initialize_database when the module is loaded
initialize_database()

# --- DATE PARSING HELPER ---
def parse_and_format_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str or not isinstance(date_str, str):
        return None

    # Attempt to remove ordinal suffixes (st, nd, rd, th) and commas
    cleaned_date_str = date_str.lower()
    cleaned_date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", cleaned_date_str)
    cleaned_date_str = cleaned_date_str.replace(',', '') # Remove commas e.g. "May 26, 2025"

    # Define a list of date formats to try
    date_formats_to_try = [
        "%d %B %Y",  # e.g., "26 May 2025" / "26 may 2025"
        "%d %b %Y",  # e.g., "26 May 2025" (some locales might use abbreviated month) / "26 may 2025"
        "%B %d %Y",  # e.g., "May 26 2025" / "may 26 2025"
        "%b %d %Y",  # e.g., "May 26 2025" / "may 26 2025"
        "%Y-%m-%d",  # Already in desired format
        "%m/%d/%Y",  # e.g., "05/26/2025"
        "%d/%m/%Y",  # e.g., "26/05/2025"
        "%Y/%m/%d",  # e.g., "2025/05/26"
        "%b %d %Y",  # e.g., "jan 01 2023"
        "%B %d %Y",  # e.g., "january 01 2023"
    ]

    for fmt in date_formats_to_try:
        try:
            # Further clean specific to format if needed, e.g. for %B Day Year
            # For "May 26 2025", no further cleaning needed if comma already removed.
            dt_obj = datetime.strptime(cleaned_date_str.strip(), fmt)
            return dt_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue # Try next format
    
    print(f"DB_MGR: Warning - Could not parse date string '{date_str}' (cleaned: '{cleaned_date_str}') into YYYY-MM-DD. Storing as None.")
    return None # Return None if unparseable

def store_invoice_data(invoice_number: str, extracted_invoice_data: Dict[str, Any]) -> bool:
    if not invoice_number or not str(invoice_number).strip():
        print("DB_MGR: Error - Invoice number is empty or None. Cannot store invoice.")
        return False
    invoice_number_upper = str(invoice_number).strip().upper()
    data_to_insert = extracted_invoice_data.get("data", {})

    raw_invoice_date = data_to_insert.get("date")
    formatted_invoice_date = parse_and_format_date(raw_invoice_date)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO invoices
            (invoice_number, vendor_name, invoice_date, total_amount, related_po_number, full_extracted_data_json, stored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            invoice_number_upper,
            data_to_insert.get("vendor_name"),
            formatted_invoice_date, # Use the formatted date
            data_to_insert.get("total_amount"),
            str(data_to_insert.get("related_po_number","")).strip().upper() if data_to_insert.get("related_po_number") else None,
            json.dumps(extracted_invoice_data),
            datetime.now().isoformat()
        ))
        conn.commit()
        print(f"DB_MGR: Stored/Replaced Invoice '{invoice_number_upper}' with original date '{raw_invoice_date}' formatted as '{formatted_invoice_date}'.")
        return True
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error storing invoice '{invoice_number_upper}': {e}")
        return False
    finally:
        conn.close()

def store_po_data(po_number: str, extracted_po_data: Dict[str, Any]) -> bool:
    if not po_number or not str(po_number).strip():
        print("DB_MGR: Error - PO number is empty or None. Cannot store PO.")
        return False
    po_number_upper = str(po_number).strip().upper()
    data_to_insert = extracted_po_data.get("data", {})

    raw_po_date = data_to_insert.get("date")
    formatted_po_date = parse_and_format_date(raw_po_date)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO purchase_orders
            (po_number, vendor_name, po_date, total_amount, full_extracted_data_json, stored_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            po_number_upper,
            data_to_insert.get("vendor_name"),
            formatted_po_date, # Use the formatted date
            data_to_insert.get("total_amount"),
            json.dumps(extracted_po_data),
            datetime.now().isoformat()
        ))
        conn.commit()
        print(f"DB_MGR: Stored/Replaced PO '{po_number_upper}' with original date '{raw_po_date}' formatted as '{formatted_po_date}'.")
        return True
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error storing PO '{po_number_upper}': {e}")
        return False
    finally:
        conn.close()

# --- Existing GET functions (get_invoice_by_number, get_po_by_number, etc.) remain the same ---
def get_invoice_by_number(invoice_number: str) -> Optional[Dict[str, Any]]:
    if not invoice_number or not str(invoice_number).strip(): return None
    inv_num_upper = str(invoice_number).strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM invoices WHERE invoice_number = ?", (inv_num_upper,))
        row = cursor.fetchone()
        if row and row["full_extracted_data_json"]:
            print(f"DB_MGR: Found Invoice '{inv_num_upper}'.")
            return json.loads(row["full_extracted_data_json"])
        else:
            print(f"DB_MGR: Invoice '{inv_num_upper}' not found.")
            return None
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching invoice '{inv_num_upper}': {e}")
    except json.JSONDecodeError as je:
        print(f"DB_MGR: Error decoding JSON for invoice '{inv_num_upper}': {je}")
    finally:
        conn.close()
    return None

def get_po_by_number(po_number: str) -> Optional[Dict[str, Any]]:
    if not po_number or not str(po_number).strip(): return None
    po_num_upper = str(po_number).strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM purchase_orders WHERE po_number = ?", (po_num_upper,))
        row = cursor.fetchone()
        if row and row["full_extracted_data_json"]:
            print(f"DB_MGR: Found PO '{po_num_upper}'.")
            return json.loads(row["full_extracted_data_json"])
        else:
            print(f"DB_MGR: PO '{po_num_upper}' not found.")
            return None
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching PO '{po_num_upper}': {e}")
    except json.JSONDecodeError as je:
        print(f"DB_MGR: Error decoding JSON for PO '{po_num_upper}': {je}")
    finally:
        conn.close()
    return None

def get_invoice_by_related_po(po_number: str) -> Optional[Dict[str, Any]]:
    if not po_number or not str(po_number).strip():
        print("DB_MGR: Cannot search for invoice by empty related PO number.")
        return None
    related_po_num_upper = str(po_number).strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM invoices WHERE related_po_number = ?",
                       (related_po_num_upper,))
        row = cursor.fetchone()
        if row and row["full_extracted_data_json"]:
            invoice_data = json.loads(row["full_extracted_data_json"])
            invoice_num_found = invoice_data.get("data",{}).get("document_number", "UNKNOWN")
            print(f"DB_MGR: Found Invoice '{invoice_num_found}' related to PO '{related_po_num_upper}'.")
            return invoice_data
        else:
            print(f"DB_MGR: No Invoice found in DB that references PO '{related_po_num_upper}'.")
            return None
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching invoice by related PO '{related_po_num_upper}': {e}")
    except json.JSONDecodeError as je:
        print(f"DB_MGR: Error decoding JSON for invoice related to PO '{related_po_num_upper}': {je}")
    finally:
        conn.close()
    return None

def get_all_invoices() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []
    try:
        cursor.execute("SELECT full_extracted_data_json FROM invoices")
        rows = cursor.fetchall()
        for row in rows:
            if row["full_extracted_data_json"]:
                results.append(json.loads(row["full_extracted_data_json"]))
        return results
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching all invoices: {e}")
        return []
    finally:
        conn.close()

def get_all_purchase_orders() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []
    try:
        cursor.execute("SELECT full_extracted_data_json FROM purchase_orders")
        rows = cursor.fetchall()
        for row in rows:
            if row["full_extracted_data_json"]:
                results.append(json.loads(row["full_extracted_data_json"]))
        return results
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching all POs: {e}")
        return []
    finally:
        conn.close()

def clear_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM invoices")
        cursor.execute("DELETE FROM purchase_orders")
        conn.commit()
        print("DB_MGR: Database tables (invoices, purchase_orders) cleared.")
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error clearing database: {e}")
    finally:
        conn.close()

# --- NEW FUNCTIONS FOR DATABASE QUERY AGENT (These were already correct) ---

def get_documents_count_by_date_range(doc_type: str, start_date_str: str, end_date_str: str) -> int:
    """Gets the count of documents (invoices or purchase_orders) within a specified date range."""
    if doc_type not in ["invoice", "purchase_order"]:
        raise ValueError("Invalid doc_type. Must be 'invoice' or 'purchase_order'.")
    
    table_name = "invoices" if doc_type == "invoice" else "purchase_orders"
    date_column = "invoice_date" if doc_type == "invoice" else "po_date"
    
    try:
        datetime.strptime(start_date_str, "%Y-%m-%d")
        datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError:
        print(f"DB_MGR: Invalid date format for {start_date_str} or {end_date_str} for count. Expected YYYY-MM-DD.")
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    count = 0
    try:
        # Dates are stored as YYYY-MM-DD, so direct string comparison works
        query = f"SELECT COUNT(*) FROM {table_name} WHERE {date_column} >= ? AND {date_column} <= ?"
        cursor.execute(query, (start_date_str, end_date_str))
        result = cursor.fetchone()
        if result:
            count = result[0]
        print(f"DB_MGR: Counted {count} {doc_type}(s) between {start_date_str} and {end_date_str}.")
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error counting {doc_type} by date range: {e}")
    finally:
        conn.close()
    return count

def get_documents_count_by_vendor(doc_type: str, vendor_name: str) -> int:
    if doc_type not in ["invoice", "purchase_order"]:
        raise ValueError("Invalid doc_type. Must be 'invoice' or 'purchase_order'.")
    table_name = "invoices" if doc_type == "invoice" else "purchase_orders"
    conn = get_db_connection()
    cursor = conn.cursor()
    count = 0
    try:
        query = f"SELECT COUNT(*) FROM {table_name} WHERE vendor_name LIKE ?"
        cursor.execute(query, (f"%{vendor_name}%",))
        result = cursor.fetchone()
        if result:
            count = result[0]
        print(f"DB_MGR: Counted {count} {doc_type}(s) for vendor like '{vendor_name}'.")
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error counting {doc_type} by vendor: {e}")
    finally:
        conn.close()
    return count

def get_total_amount_by_vendor(doc_type: str, vendor_name: str) -> float:
    if doc_type not in ["invoice", "purchase_order"]:
        raise ValueError("Invalid doc_type. Must be 'invoice' or 'purchase_order'.")
    table_name = "invoices" if doc_type == "invoice" else "purchase_orders"
    conn = get_db_connection()
    cursor = conn.cursor()
    total_amount = 0.0
    try:
        query = f"SELECT SUM(total_amount) FROM {table_name} WHERE vendor_name LIKE ?"
        cursor.execute(query, (f"%{vendor_name}%",))
        result = cursor.fetchone()
        if result and result[0] is not None:
            total_amount = float(result[0])
        print(f"DB_MGR: Total amount for {doc_type}(s) from vendor like '{vendor_name}' is {total_amount:.2f}.")
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error summing {doc_type} amounts by vendor: {e}")
    except TypeError:
        print(f"DB_MGR: No amounts found to sum for {doc_type}(s) from vendor like '{vendor_name}'.")
    finally:
        conn.close()
    return total_amount

def _extract_data_field_from_json_row(row: sqlite3.Row) -> Optional[Dict[str, Any]]:
    if row and row["full_extracted_data_json"]:
        try:
            full_data = json.loads(row["full_extracted_data_json"])
            return full_data.get("data", {})
        except json.JSONDecodeError:
            print(f"DB_MGR: Warning - Could not decode JSON from row to extract 'data' field.")
            return {}
    return {}

def get_documents_by_vendor(doc_type: str, vendor_name: str, limit: int = 5) -> List[Dict[str, Any]]:
    if doc_type not in ["invoice", "purchase_order"]:
        raise ValueError("Invalid doc_type. Must be 'invoice' or 'purchase_order'.")
    table_name = "invoices" if doc_type == "invoice" else "purchase_orders"
    results = []
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = f"SELECT full_extracted_data_json FROM {table_name} WHERE vendor_name LIKE ? LIMIT ?"
        cursor.execute(query, (f"%{vendor_name}%", limit))
        rows = cursor.fetchall()
        for row in rows:
            data_field = _extract_data_field_from_json_row(row)
            if data_field:
                results.append(data_field)
        print(f"DB_MGR: Fetched {len(results)} {doc_type}(s) for vendor like '{vendor_name}' (limit {limit}).")
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching {doc_type} by vendor: {e}")
    finally:
        conn.close()
    return results

def get_documents_by_date_range(doc_type: str, start_date_str: str, end_date_str: str, limit: int = 5) -> List[Dict[str, Any]]:
    if doc_type not in ["invoice", "purchase_order"]:
        raise ValueError("Invalid doc_type. Must be 'invoice' or 'purchase_order'.")
    table_name = "invoices" if doc_type == "invoice" else "purchase_orders"
    date_column = "invoice_date" if doc_type == "invoice" else "po_date"
    try:
        datetime.strptime(start_date_str, "%Y-%m-%d")
        datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError:
        print(f"DB_MGR: Invalid date format for {start_date_str} or {end_date_str} for list. Expected YYYY-MM-DD.")
        return []
    results = []
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = f"SELECT full_extracted_data_json FROM {table_name} WHERE {date_column} >= ? AND {date_column} <= ? LIMIT ?"
        cursor.execute(query, (start_date_str, end_date_str, limit))
        rows = cursor.fetchall()
        for row in rows:
            data_field = _extract_data_field_from_json_row(row)
            if data_field:
                results.append(data_field)
        print(f"DB_MGR: Fetched {len(results)} {doc_type}(s) from {start_date_str} to {end_date_str} (limit {limit}).")
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching {doc_type} by date range: {e}")
    finally:
        conn.close()
    return results

