# database_manager.py
import sqlite3
import json
import os
from typing import Dict, Any, Optional, List

DB_PATH = "reconciliation_data.db" 

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Invoices Table - keeps related_po_number
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_number TEXT PRIMARY KEY,
            vendor_name TEXT,
            invoice_date TEXT,
            total_amount REAL,
            related_po_number TEXT, 
            full_extracted_data_json TEXT,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Purchase Orders Table - removes related_invoice_number
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_number TEXT PRIMARY KEY,
            vendor_name TEXT,
            po_date TEXT,
            total_amount REAL,
            -- related_invoice_number TEXT, -- REMOVED
            full_extracted_data_json TEXT,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print(f"DB_MGR: Database '{DB_PATH}' initialized/checked (PO table updated).")

initialize_database()

# ... store_invoice_data remains the same as it correctly handles related_po_number ...
def store_invoice_data(invoice_number: str, extracted_invoice_data: Dict[str, Any]) -> bool:
    if not invoice_number: return False
    invoice_number_upper = invoice_number.strip().upper()
    data_to_store = extracted_invoice_data.get("data", {})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO invoices 
            (invoice_number, vendor_name, invoice_date, total_amount, related_po_number, full_extracted_data_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            invoice_number_upper,
            data_to_store.get("vendor_name"),
            data_to_store.get("date"), 
            data_to_store.get("total_amount"),
            data_to_store.get("related_po_number"), 
            json.dumps(extracted_invoice_data) 
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
    if not po_number:
        print("DB_MGR: Error - Cannot store PO without a PO number.")
        return False
        
    po_number_upper = po_number.strip().upper()
    data_to_store = extracted_po_data.get("data", {})

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Updated to remove related_invoice_number from VALUES
        cursor.execute('''
            INSERT OR REPLACE INTO purchase_orders 
            (po_number, vendor_name, po_date, total_amount, full_extracted_data_json)
            VALUES (?, ?, ?, ?, ?) 
        ''', (
            po_number_upper,
            data_to_store.get("vendor_name"),
            data_to_store.get("date"), 
            data_to_store.get("total_amount"),
            # data_to_store.get("related_invoice_number"), -- REMOVED
            json.dumps(extracted_po_data)
        ))
        conn.commit()
        print(f"DB_MGR: Stored/Replaced PO '{po_number_upper}'.")
        return True
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error storing PO '{po_number_upper}': {e}")
        return False
    finally:
        conn.close()

# ... get_invoice_by_number, get_po_by_number, get_all_*, clear_database remain the same ...
def get_invoice_by_number(invoice_number: str) -> Optional[Dict[str, Any]]:
    inv_num_upper = invoice_number.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM invoices WHERE invoice_number = ?", (inv_num_upper,))
        row = cursor.fetchone()
        if row:
            print(f"DB_MGR: Found Invoice '{inv_num_upper}'.")
            return json.loads(row["full_extracted_data_json"])
        else:
            print(f"DB_MGR: Invoice '{inv_num_upper}' not found.")
            return None
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching invoice '{inv_num_upper}': {e}")
        return None
    finally:
        conn.close()

def get_po_by_number(po_number: str) -> Optional[Dict[str, Any]]:
    po_num_upper = po_number.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM purchase_orders WHERE po_number = ?", (po_num_upper,))
        row = cursor.fetchone()
        if row:
            print(f"DB_MGR: Found PO '{po_num_upper}'.")
            return json.loads(row["full_extracted_data_json"])
        else:
            print(f"DB_MGR: PO '{po_num_upper}' not found.")
            return None
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching PO '{po_num_upper}': {e}")
        return None
    finally:
        conn.close()

def get_all_invoices() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM invoices")
        rows = cursor.fetchall()
        return [json.loads(row["full_extracted_data_json"]) for row in rows]
    except sqlite3.Error as e:
        print(f"DB_MGR: SQLite error fetching all invoices: {e}")
        return []
    finally:
        conn.close()

def get_all_purchase_orders() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT full_extracted_data_json FROM purchase_orders")
        rows = cursor.fetchall()
        return [json.loads(row["full_extracted_data_json"]) for row in rows]
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

