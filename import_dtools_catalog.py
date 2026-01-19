#!/usr/bin/env python3
"""
D-Tools Product Catalog Importer
================================
Imports the D-Tools product catalog CSV into MySQL for accurate
rack unit, BTU, wattage, and weight specifications.

Usage:
    python import_dtools_catalog.py "/path/to/DTools Products.csv"
"""

import csv
import sys
import os
from pathlib import Path

# Try to import MySQL connector
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("Warning: mysql-connector-python not installed. Will create SQLite fallback.")

# Try SQLite as fallback
import sqlite3

# Database configuration (same as product_specs.py)
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # Update if you have a password
    'database': 'av_products'
}

SQLITE_PATH = Path(__file__).parent / "dtools_catalog.db"


def parse_float(value: str) -> float:
    """Safely parse a float value from CSV."""
    if not value or value.strip() == '':
        return 0.0
    try:
        # Remove any non-numeric characters except . and -
        cleaned = ''.join(c for c in value if c.isdigit() or c in '.-')
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def parse_int(value: str) -> int:
    """Safely parse an integer value from CSV."""
    return int(parse_float(value))


def parse_bool(value: str) -> bool:
    """Parse Yes/No to boolean."""
    return value.strip().lower() in ('yes', 'true', '1', 'y')


def create_mysql_table(cursor):
    """Create the dtools_products table in MySQL."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dtools_products (
            id INT AUTO_INCREMENT PRIMARY KEY,
            brand VARCHAR(255),
            model VARCHAR(255),
            part_number VARCHAR(255),
            short_description TEXT,
            description TEXT,
            category VARCHAR(255),
            keywords TEXT,
            image_url TEXT,
            msrp DECIMAL(10,2),
            unit_cost DECIMAL(10,2),
            unit_price DECIMAL(10,2),
            taxable BOOLEAN,
            supplier VARCHAR(255),
            system VARCHAR(255),
            phase VARCHAR(255),
            height DECIMAL(10,4),
            width DECIMAL(10,4),
            depth DECIMAL(10,4),
            weight DECIMAL(10,4),
            rack_mounted BOOLEAN,
            rack_units INT,
            amps DECIMAL(10,4),
            volts DECIMAL(10,4),
            watts DECIMAL(10,4),
            btu DECIMAL(10,4),
            created_date DATETIME,
            modified_date DATETIME,
            UNIQUE KEY unique_part (brand, model, part_number)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    
    # Create index for faster lookups
    try:
        cursor.execute("CREATE INDEX idx_part_number ON dtools_products(part_number)")
    except:
        pass  # Index may already exist
    
    try:
        cursor.execute("CREATE INDEX idx_model ON dtools_products(model)")
    except:
        pass


def create_sqlite_table(cursor):
    """Create the dtools_products table in SQLite."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dtools_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            model TEXT,
            part_number TEXT,
            short_description TEXT,
            description TEXT,
            category TEXT,
            keywords TEXT,
            image_url TEXT,
            msrp REAL,
            unit_cost REAL,
            unit_price REAL,
            taxable INTEGER,
            supplier TEXT,
            system TEXT,
            phase TEXT,
            height REAL,
            width REAL,
            depth REAL,
            weight REAL,
            rack_mounted INTEGER,
            rack_units INTEGER,
            amps REAL,
            volts REAL,
            watts REAL,
            btu REAL,
            created_date TEXT,
            modified_date TEXT,
            UNIQUE(brand, model, part_number)
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_part_number ON dtools_products(part_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_model ON dtools_products(model)")


def import_to_mysql(csv_path: str) -> tuple[int, int]:
    """Import CSV to MySQL database."""
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    
    # Create database if it doesn't exist
    cursor.execute("CREATE DATABASE IF NOT EXISTS av_products")
    cursor.execute("USE av_products")
    
    create_mysql_table(cursor)
    
    imported = 0
    skipped = 0
    
    # Read and import CSV
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            try:
                cursor.execute("""
                    INSERT INTO dtools_products 
                    (brand, model, part_number, short_description, description,
                     category, keywords, image_url, msrp, unit_cost, unit_price,
                     taxable, supplier, system, phase, height, width, depth, weight,
                     rack_mounted, rack_units, amps, volts, watts, btu,
                     created_date, modified_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        short_description = VALUES(short_description),
                        description = VALUES(description),
                        category = VALUES(category),
                        rack_mounted = VALUES(rack_mounted),
                        rack_units = VALUES(rack_units),
                        amps = VALUES(amps),
                        volts = VALUES(volts),
                        watts = VALUES(watts),
                        btu = VALUES(btu),
                        height = VALUES(height),
                        width = VALUES(width),
                        depth = VALUES(depth),
                        weight = VALUES(weight),
                        modified_date = VALUES(modified_date)
                """, (
                    row.get('Brand', ''),
                    row.get('Model', ''),
                    row.get('Part Number', ''),
                    row.get('Short Description', ''),
                    row.get('Description', ''),
                    row.get('Category', ''),
                    row.get('Keywords', ''),
                    row.get('Image URL', ''),
                    parse_float(row.get('MSRP', '')),
                    parse_float(row.get('Unit Cost', '')),
                    parse_float(row.get('Unit Price', '')),
                    parse_bool(row.get('Taxable', '')),
                    row.get('Supplier', ''),
                    row.get('System', ''),
                    row.get('Phase', ''),
                    parse_float(row.get('Height', '')),
                    parse_float(row.get('Width', '')),
                    parse_float(row.get('Depth', '')),
                    parse_float(row.get('Weight', '')),
                    parse_bool(row.get('Rack Mounted', '')),
                    parse_int(row.get('Rack Units', '')),
                    parse_float(row.get('Amps', '')),
                    parse_float(row.get('Volts', '')),
                    parse_float(row.get('Watts', '')),
                    parse_float(row.get('BTU', '')),
                    row.get('Created Date', ''),
                    row.get('Modified Date', '')
                ))
                imported += 1
            except Exception as e:
                print(f"  Skipped row: {row.get('Model', 'unknown')} - {e}")
                skipped += 1
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return imported, skipped


def import_to_sqlite(csv_path: str) -> tuple[int, int]:
    """Import CSV to SQLite database (fallback)."""
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    
    create_sqlite_table(cursor)
    
    imported = 0
    skipped = 0
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO dtools_products 
                    (brand, model, part_number, short_description, description,
                     category, keywords, image_url, msrp, unit_cost, unit_price,
                     taxable, supplier, system, phase, height, width, depth, weight,
                     rack_mounted, rack_units, amps, volts, watts, btu,
                     created_date, modified_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row.get('Brand', ''),
                    row.get('Model', ''),
                    row.get('Part Number', ''),
                    row.get('Short Description', ''),
                    row.get('Description', ''),
                    row.get('Category', ''),
                    row.get('Keywords', ''),
                    row.get('Image URL', ''),
                    parse_float(row.get('MSRP', '')),
                    parse_float(row.get('Unit Cost', '')),
                    parse_float(row.get('Unit Price', '')),
                    1 if parse_bool(row.get('Taxable', '')) else 0,
                    row.get('Supplier', ''),
                    row.get('System', ''),
                    row.get('Phase', ''),
                    parse_float(row.get('Height', '')),
                    parse_float(row.get('Width', '')),
                    parse_float(row.get('Depth', '')),
                    parse_float(row.get('Weight', '')),
                    1 if parse_bool(row.get('Rack Mounted', '')) else 0,
                    parse_int(row.get('Rack Units', '')),
                    parse_float(row.get('Amps', '')),
                    parse_float(row.get('Volts', '')),
                    parse_float(row.get('Watts', '')),
                    parse_float(row.get('BTU', '')),
                    row.get('Created Date', ''),
                    row.get('Modified Date', '')
                ))
                imported += 1
            except Exception as e:
                print(f"  Skipped row: {row.get('Model', 'unknown')} - {e}")
                skipped += 1
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return imported, skipped


def lookup_product(model: str = None, part_number: str = None) -> dict:
    """
    Look up a product by model or part number.
    Returns dict with specs or None if not found.
    """
    # Try SQLite first (always available)
    if SQLITE_PATH.exists():
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if part_number:
            cursor.execute(
                "SELECT * FROM dtools_products WHERE part_number = ? OR model = ?",
                (part_number, part_number)
            )
        elif model:
            cursor.execute(
                "SELECT * FROM dtools_products WHERE model LIKE ? OR part_number LIKE ?",
                (f"%{model}%", f"%{model}%")
            )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
    
    # Try MySQL if available
    if MYSQL_AVAILABLE:
        try:
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            cursor = conn.cursor(dictionary=True)
            
            if part_number:
                cursor.execute(
                    "SELECT * FROM dtools_products WHERE part_number = %s OR model = %s",
                    (part_number, part_number)
                )
            elif model:
                cursor.execute(
                    "SELECT * FROM dtools_products WHERE model LIKE %s OR part_number LIKE %s",
                    (f"%{model}%", f"%{model}%")
                )
            
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if row:
                return row
        except:
            pass
    
    return None


def get_rack_specs(model: str = None, part_number: str = None) -> dict:
    """
    Get rack-relevant specs for a product.
    Returns dict with rack_units, watts, btu, weight or defaults.
    """
    product = lookup_product(model=model, part_number=part_number)
    
    if product:
        return {
            'rack_units': product.get('rack_units', 1) or 1,
            'watts': product.get('watts', 0) or 0,
            'btu': product.get('btu', 0) or 0,
            'weight': product.get('weight', 0) or 0,
            'rack_mounted': bool(product.get('rack_mounted', False)),
            'brand': product.get('brand', ''),
            'model': product.get('model', ''),
            'description': product.get('short_description', '')
        }
    
    # Return defaults if not found
    return {
        'rack_units': 1,
        'watts': 0,
        'btu': 0,
        'weight': 0,
        'rack_mounted': False,
        'brand': '',
        'model': model or part_number or '',
        'description': ''
    }


def print_stats():
    """Print database statistics."""
    if SQLITE_PATH.exists():
        conn = sqlite3.connect(SQLITE_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM dtools_products")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM dtools_products WHERE rack_mounted = 1")
        rack_mounted = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM dtools_products WHERE rack_units > 0")
        with_ru = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM dtools_products WHERE watts > 0")
        with_watts = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM dtools_products WHERE btu > 0")
        with_btu = cursor.fetchone()[0]
        
        conn.close()
        
        print("\n📊 Database Statistics:")
        print(f"   Total products:     {total:,}")
        print(f"   Rack-mountable:     {rack_mounted:,}")
        print(f"   With Rack Units:    {with_ru:,}")
        print(f"   With Wattage:       {with_watts:,}")
        print(f"   With BTU:           {with_btu:,}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python import_dtools_catalog.py <path_to_csv>")
        print("\nExample:")
        print('  python import_dtools_catalog.py "/Users/henryjohnson/Downloads/DTools Products.csv"')
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)
    
    print(f"📂 Importing D-Tools Product Catalog...")
    print(f"   Source: {csv_path}")
    
    # Try MySQL first, fall back to SQLite
    if MYSQL_AVAILABLE:
        try:
            print("   Target: MySQL (av_products.dtools_products)")
            imported, skipped = import_to_mysql(csv_path)
            print(f"\n✅ MySQL Import Complete!")
        except Exception as e:
            print(f"   MySQL failed: {e}")
            print("   Falling back to SQLite...")
            print(f"   Target: {SQLITE_PATH}")
            imported, skipped = import_to_sqlite(csv_path)
            print(f"\n✅ SQLite Import Complete!")
    else:
        print(f"   Target: SQLite ({SQLITE_PATH})")
        imported, skipped = import_to_sqlite(csv_path)
        print(f"\n✅ SQLite Import Complete!")
    
    print(f"   Imported: {imported:,} products")
    if skipped:
        print(f"   Skipped:  {skipped:,} rows (errors)")
    
    print_stats()
    
    # Test a lookup
    print("\n🔍 Testing lookups...")
    
    # Test with known rack equipment
    test_models = ['MDX 16', 'AN-110-SW-R-24', 'P5']
    for model in test_models:
        specs = get_rack_specs(model=model)
        if specs['rack_units'] > 0:
            print(f"   ✓ {specs['brand']} {specs['model']}: {specs['rack_units']}U, {specs['watts']}W, {specs['btu']} BTU")


if __name__ == "__main__":
    main()






