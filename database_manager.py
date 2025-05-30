import sqlite3
import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime 


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
    
    # Invoices Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_number TEXT PRIMARY KEY,
            vendor_name TEXT,
            invoice_date TEXT,
            total_amount REAL,
            related_po_number TEXT, -- For quick lookups if invoice references a PO
            full_extracted_data_json TEXT, -- Stores the entire JSON from extraction
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Create an index on related_po_number for faster lookups
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invoices_related_po
        ON invoices (related_po_number)
    ''')
    
    # Purchase Orders Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_number TEXT PRIMARY KEY,
            vendor_name TEXT,
            po_date TEXT,
            total_amount REAL,
            -- related_invoice_number TEXT, -- REMOVED as per standard PO practice
            full_extracted_data_json TEXT,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"DB_MGR: Database '{DB_PATH}' initialized/checked successfully.")

# Call initialize_database when the module is first imported
# This ensures tables and indexes are ready.
initialize_database()

def store_invoice_data(invoice_number: str, extracted_invoice_data: Dict[str, Any]) -> bool:
    """Stores extracted invoice data into the SQLite DB."""
    if not invoice_number or not str(invoice_number).strip():
        print("DB_MGR: Error - Invoice number is empty or None. Cannot store invoice.")
        return False
    
    invoice_number_upper = str(invoice_number).strip().upper()
    data_to_insert = extracted_invoice_data.get("data", {}) 
    
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
            data_to_insert.get("date"), 
            data_to_insert.get("total_amount"),
            str(data_to_insert.get("related_po_number","")).strip().upper() if data_to_insert.get("related_po_number") else None, # Ensure uppercase or None
            json.dumps(extracted_invoice_data), # Store the whole original extraction result
            datetime.now().isoformat()
        ))
        conn.commit()
        print(f"DB_MGR: Stored/Replaced Invoice '{invoice_number_upper}'.")
        return True
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error storing invoice '{invoice_number_upper}': {e}")
        return False
    finally:
        conn.close()

def store_po_data(po_number: str, extracted_po_data: Dict[str, Any]) -> bool:
    """Stores extracted purchase order data into the SQLite DB."""
    if not po_number or not str(po_number).strip():
        print("DB_MGR: Error - PO number is empty or None. Cannot store PO.")
        return False
        
    po_number_upper = str(po_number).strip().upper()
    data_to_insert = extracted_po_data.get("data", {})

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
            data_to_insert.get("date"), 
            data_to_insert.get("total_amount"),
            json.dumps(extracted_po_data),
            datetime.now().isoformat()
        ))
        conn.commit()
        print(f"DB_MGR: Stored/Replaced PO '{po_number_upper}'.")
        return True
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error storing PO '{po_number_upper}': {e}")
        return False
    finally:
        conn.close()

def get_invoice_by_number(invoice_number: str) -> Optional[Dict[str, Any]]:
    """Retrieves an invoice from the DB by its number. Returns the full stored JSON object."""
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
        return None
    except json.JSONDecodeError as je:
        print(f"DB_MGR: Error decoding JSON for invoice '{inv_num_upper}': {je}")
        return None 
    finally:
        conn.close()

def get_po_by_number(po_number: str) -> Optional[Dict[str, Any]]:
    """Retrieves a purchase order from the DB by its number. Returns the full stored JSON object."""
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
        return None
    except json.JSONDecodeError as je:
        print(f"DB_MGR: Error decoding JSON for PO '{po_num_upper}': {je}")
        return None
    finally:
        conn.close()

def get_invoice_by_related_po(po_number: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves an invoice from the DB by a PO number referenced ON THE INVOICE
    in its 'related_po_number' field. Returns the full stored JSON object of the invoice.
    """
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
        return None
    except json.JSONDecodeError as je:
        print(f"DB_MGR: Error decoding JSON for invoice related to PO '{related_po_num_upper}': {je}")
        return None
    finally:
        conn.close()


def get_all_invoices() -> List[Dict[str, Any]]:
    """Returns all stored invoices (as full JSON objects)."""
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
    """Returns all stored purchase orders (as full JSON objects)."""
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
    """Clears all data from the database tables (for testing)."""
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

