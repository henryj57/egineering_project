"""
Import Products to MySQL Database
Loads product specifications from CSV into the product_catalog table
"""

import csv
import sys
from pathlib import Path
from db_client import get_database


def import_from_csv(csv_path: str) -> int:
    """
    Import products from a CSV file.
    
    Expected CSV columns (flexible naming):
    - Brand / Manufacturer
    - Model / Model Number / Part Number
    - Name / Description / Product Name
    - Height (U) / Rack Units / RU / U
    - Watts / Power / Wattage
    - BTU (optional, calculated from Watts if missing)
    - Weight / Weight (lbs)
    - Subsystem / Category / Type (AV, Network, Power)
    """
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"❌ File not found: {csv_path}")
        return 0
    
    # Read CSV with flexible encoding
    encodings = ['utf-8', 'latin-1', 'cp1252']
    rows = []
    
    for encoding in encodings:
        try:
            with open(csv_file, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                break
        except UnicodeDecodeError:
            continue
    
    if not rows:
        print(f"❌ Could not read CSV file")
        return 0
    
    print(f"📄 Found {len(rows)} rows in CSV")
    
    # Connect to database
    db = get_database()
    db.initialize_schema()
    
    # Map CSV columns to database fields
    products = []
    for row in rows:
        product = {
            'brand': get_field(row, ['Brand', 'Manufacturer', 'Mfr', 'Make']),
            'model': get_field(row, ['Model', 'Model Number', 'Part Number', 'PartNumber', 'SKU']),
            'name': get_field(row, ['Name', 'Description', 'Product Name', 'ProductName', 'Title']),
            'part_number': get_field(row, ['Part Number', 'PartNumber', 'SKU', 'Item Number']),
            'height_u': parse_int(get_field(row, ['Height (U)', 'Rack Units', 'RU', 'U', 'Height', 'Size'])),
            'watts': parse_float(get_field(row, ['Watts', 'Power', 'Wattage', 'Power (W)', 'W'])),
            'btu': parse_float(get_field(row, ['BTU', 'BTU/hr', 'Heat'])),
            'weight': parse_float(get_field(row, ['Weight', 'Weight (lbs)', 'Weight (lb)', 'Lbs'])),
            'subsystem': categorize_subsystem(row),
            'is_rack_mountable': True,
            'category': get_field(row, ['Category', 'Type', 'System']),
            'notes': get_field(row, ['Notes', 'Comments', 'Description'])
        }
        
        # Skip rows without a model number
        if not product['model']:
            continue
        
        # Calculate BTU from Watts if not provided
        if not product['btu'] and product['watts']:
            product['btu'] = product['watts'] * 3.41
        
        products.append(product)
    
    # Import to database
    added = db.bulk_add_products(products)
    db.disconnect()
    
    return added


def get_field(row: dict, possible_names: list) -> str:
    """Get a field value from row using multiple possible column names"""
    for name in possible_names:
        # Try exact match
        if name in row and row[name]:
            return str(row[name]).strip()
        # Try case-insensitive match
        for key in row.keys():
            if key.lower() == name.lower() and row[key]:
                return str(row[key]).strip()
    return ''


def parse_int(value: str) -> int:
    """Parse integer from string, return 0 if invalid"""
    if not value:
        return 0
    try:
        # Handle values like "2U" or "2 U"
        cleaned = ''.join(c for c in value if c.isdigit() or c == '.')
        if cleaned:
            return int(float(cleaned))
    except (ValueError, TypeError):
        pass
    return 0


def parse_float(value: str) -> float:
    """Parse float from string, return 0.0 if invalid"""
    if not value:
        return 0.0
    try:
        cleaned = ''.join(c for c in value if c.isdigit() or c == '.')
        if cleaned:
            return float(cleaned)
    except (ValueError, TypeError):
        pass
    return 0.0


def categorize_subsystem(row: dict) -> str:
    """Determine if product is AV, Network, or Power based on various fields"""
    # Check explicit subsystem field
    subsystem = get_field(row, ['Subsystem', 'System', 'Category', 'Type', 'Department'])
    
    if subsystem:
        subsystem_lower = subsystem.lower()
        if any(kw in subsystem_lower for kw in ['network', 'net', 'switch', 'router', 'wifi']):
            return 'Network'
        if any(kw in subsystem_lower for kw in ['power', 'ups', 'pdu', 'surge']):
            return 'Power'
        if any(kw in subsystem_lower for kw in ['av', 'audio', 'video', 'control', 'lighting']):
            return 'AV'
    
    # Check brand for hints
    brand = get_field(row, ['Brand', 'Manufacturer']).lower()
    model = get_field(row, ['Model', 'Model Number']).lower()
    name = get_field(row, ['Name', 'Description']).lower()
    
    combined = f"{brand} {model} {name}"
    
    if any(kw in combined for kw in ['ubiquiti', 'unifi', 'cisco', 'netgear', 'aruba', 'pakedge', 'araknis']):
        return 'Network'
    if any(kw in combined for kw in ['apc', 'cyberpower', 'tripp', 'furman', 'panamax']):
        return 'Power'
    
    return 'AV'  # Default to AV


def add_sample_products():
    """Add some common AV products to get started"""
    
    sample_products = [
        # Savant products
        {'brand': 'Savant', 'model': 'SSC-0012-00', 'name': 'Smart Controller 12', 'height_u': 1, 'watts': 25, 'subsystem': 'AV'},
        {'brand': 'Savant', 'model': 'SSA-3220-00', 'name': 'Smart Audio Soundbar', 'height_u': 2, 'watts': 200, 'subsystem': 'AV'},
        {'brand': 'Savant', 'model': 'PAV-SHC1S-00', 'name': 'Host Controller', 'height_u': 1, 'watts': 15, 'subsystem': 'AV'},
        
        # Lutron products
        {'brand': 'Lutron', 'model': 'HQP7-2', 'name': 'HomeWorks QSX Processor', 'height_u': 2, 'watts': 50, 'subsystem': 'AV'},
        {'brand': 'Lutron', 'model': 'RR-MAIN-REP-WH', 'name': 'RadioRA Main Repeater', 'height_u': 1, 'watts': 10, 'subsystem': 'AV'},
        
        # Network equipment
        {'brand': 'Ubiquiti', 'model': 'USW-Pro-48-POE', 'name': 'UniFi Pro 48 PoE Switch', 'height_u': 1, 'watts': 700, 'subsystem': 'Network'},
        {'brand': 'Ubiquiti', 'model': 'UDM-Pro', 'name': 'Dream Machine Pro', 'height_u': 1, 'watts': 35, 'subsystem': 'Network'},
        {'brand': 'Araknis', 'model': 'AN-310-SW-24-POE', 'name': '310 Series 24-Port PoE Switch', 'height_u': 1, 'watts': 400, 'subsystem': 'Network'},
        
        # Audio
        {'brand': 'Sonance', 'model': 'DSP 8-130', 'name': '8-Channel DSP Amplifier', 'height_u': 2, 'watts': 1040, 'subsystem': 'AV'},
        {'brand': 'Marantz', 'model': 'SR8015', 'name': '11.2 Channel AV Receiver', 'height_u': 7, 'watts': 250, 'weight': 45, 'subsystem': 'AV'},
        
        # Power
        {'brand': 'Furman', 'model': 'M-8X2', 'name': 'Merit Series Power Conditioner', 'height_u': 1, 'watts': 15, 'subsystem': 'Power'},
        {'brand': 'APC', 'model': 'SMT1500RM2U', 'name': 'Smart-UPS 1500VA', 'height_u': 2, 'watts': 1000, 'weight': 65, 'subsystem': 'Power'},
    ]
    
    db = get_database()
    db.initialize_schema()
    
    added = db.bulk_add_products(sample_products)
    print(f"\n📦 Added {added} sample products to get you started!")
    
    db.disconnect()
    return added


if __name__ == "__main__":
    print("📥 Product Import Tool")
    print("=" * 50)
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        if arg == '--sample':
            add_sample_products()
        else:
            print(f"\nImporting from: {arg}")
            count = import_from_csv(arg)
            print(f"\n✅ Imported {count} products")
    else:
        print("\nUsage:")
        print("  python3 import_products.py <csv_file>    - Import from CSV")
        print("  python3 import_products.py --sample      - Add sample products")
        print("\n💡 Would you like to add sample products? Run:")
        print("   python3 import_products.py --sample")

