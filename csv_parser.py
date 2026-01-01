"""
CSV Parser Module
Reads client proposal CSVs and extracts rack-mountable equipment
Supports multiple CSV formats from different clients
"""

import csv
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


@dataclass
class ProductFromCSV:
    """Represents a product parsed from the client's CSV"""
    name: str
    brand: str
    model: str
    category: str
    quantity: int
    location: str
    system: str
    description: str = ""
    calculated_btu: float = 0.0
    part_number: str = ""  # For alternative CSV format
    
    # These will be filled in from AI lookup
    rack_units: Optional[int] = None
    weight: Optional[float] = None
    btu: Optional[float] = None
    front_image_url: Optional[str] = None
    connections: Optional[dict] = None


@dataclass
class RackFromCSV:
    """Represents a rack found in the client's CSV"""
    model: str
    size_u: int
    quantity: int
    location: str
    rack_type: str = "AV"  # AV, Network, or General


def detect_csv_format(headers: List[str]) -> str:
    """Detect which CSV format we're dealing with"""
    headers_lower = [h.lower().strip() for h in headers]
    
    if 'brand' in headers_lower and 'model' in headers_lower:
        return 'standard'  # D-Tools/Portal style
    elif 'part number' in headers_lower and 'locationpath' in headers_lower:
        return 'si_avc'  # SI/AVC style
    else:
        return 'unknown'


def parse_client_csv(csv_path: str, equipment_location: Optional[str] = None) -> List[ProductFromCSV]:
    """
    Parse a client proposal CSV and extract products.
    Auto-detects CSV format and adapts accordingly.
    
    Args:
        csv_path: Path to the CSV file
        equipment_location: Filter to only include items with this location (None = include all)
    
    Returns:
        List of ProductFromCSV objects
    """
    products = []
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        csv_format = detect_csv_format(headers)
        
        print(f"📋 Detected CSV format: {csv_format}")
        
        if csv_format == 'si_avc':
            return parse_si_avc_format(csv_path, equipment_location)
        
        # Standard format parsing
        for row in reader:
            location = row.get('Location', '').strip()
            
            # Filter by equipment location if specified
            if equipment_location and location != equipment_location:
                continue
            
            # Skip items with zero or negative quantity
            try:
                quantity = int(row.get('Quantity', 0))
                if quantity <= 0:
                    continue
            except ValueError:
                continue
            
            # Parse BTU if present
            try:
                calculated_btu = float(row.get('Calculated_BTU', 0) or 0)
            except ValueError:
                calculated_btu = 0.0
            
            product = ProductFromCSV(
                name=row.get('Name', '').strip(),
                brand=row.get('Brand', '').strip(),
                model=row.get('Model', '').strip(),
                category=row.get('Category', '').strip(),
                quantity=quantity,
                location=location,
                system=row.get('System', '').strip(),
                description=row.get('Short Description', '').strip(),
                calculated_btu=calculated_btu
            )
            
            products.append(product)
    
    return products


def parse_si_avc_format(csv_path: str, equipment_location: Optional[str] = None) -> List[ProductFromCSV]:
    """
    Parse SI/AVC format CSV files.
    These have columns: Quantity, Part Number, Cost Price, Sell Price, TotalLaborHours, Time (hrs), Phase, LocationPath, System
    """
    products = []
    
    # Equipment closet keywords to look for in LocationPath
    equipment_keywords = ['equipment closet', 'equipment room', 'rack', 'av closet', 'network closet', 'mdf', 'idf']
    
    # Systems that typically contain rack-mounted equipment
    rack_systems = ['network & wifi', 'equipment racks', 'lighting control', 'hvac']
    
    # Try different encodings
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    file_content = None
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                file_content = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    if file_content is None:
        print("❌ Could not decode CSV file with any known encoding")
        return []
    
    import io
    f = io.StringIO(file_content)
    reader = csv.DictReader(f)
    
    for row in reader:
        location = row.get('LocationPath', '').strip()
        system = row.get('System', '').strip()
        part_number = row.get('Part Number', '').strip()
        
        # Skip empty part numbers or placeholder items
        if not part_number or part_number.startswith('~') or part_number in ['CABLE MODEM']:
            continue
        
        # Skip generic/placeholder items
        skip_prefixes = ['BRKT:', 'PLATE:', 'CONN-', 'DATA-', 'VIDEO-', 'AUDIO-', 'CONTROL -', 
                       'DEVICE -', 'NETWORK ', 'UI -', 'IP ', 'AMP-', 'SPEAKER ', 'INTERFACE -',
                       'SPACESAVER', 'CAT6', 'RG6', '14/', '16/', 'LUTRON-GRN']
        if any(part_number.upper().startswith(prefix.upper()) for prefix in skip_prefixes):
            continue
        
        # Filter by location if specified, otherwise look for equipment areas
        location_lower = location.lower()
        system_lower = system.lower()
        
        if equipment_location:
            if equipment_location.lower() not in location_lower:
                continue
        else:
            # Auto-detect equipment closet/rack locations
            is_equipment_area = any(kw in location_lower for kw in equipment_keywords)
            # Also check if it's in a system that typically has rack-mounted gear
            is_rack_system = any(rs in system_lower for rs in rack_systems)
            
            if not is_equipment_area and not is_rack_system:
                continue
        
        # Skip items with zero or negative quantity
        try:
            quantity = int(float(row.get('Quantity', 0) or 0))
            if quantity <= 0:
                continue
        except ValueError:
            continue
        
        # Extract brand from part number if possible
        brand = extract_brand_from_part_number(part_number)
        
        product = ProductFromCSV(
            name=part_number,
            brand=brand,
            model=part_number,
            category=system,
            quantity=quantity,
            location=location,
            system=system,
            description="",
            calculated_btu=0.0,
            part_number=part_number
        )
        
        products.append(product)
    
    return products


def extract_brand_from_part_number(part_number: str) -> str:
    """Try to extract brand from common part number patterns"""
    part_upper = part_number.upper()
    
    # Known brand prefixes
    brand_patterns = {
        'USW-': 'Ubiquiti',
        'UDM-': 'Ubiquiti',
        'UAP-': 'Ubiquiti',
        'UA-': 'Ubiquiti',
        'UACC-': 'Ubiquiti',
        'E7': 'Ubiquiti',
        'PAV-': 'Savant',
        'SSC-': 'Savant',
        'SVR-': 'Savant',
        'REM-': 'Savant',
        'SSL-': 'Savant',
        'RCK-': 'Savant',
        'LCB-': 'Savant',
        'PKG-': 'Savant',
        'CLI-': 'Savant',
        'PWR-': 'Savant',
        'RMB-': 'Savant',
        'WB-': 'WattBox',
        'OVRC-': 'WattBox',
        'HQP': 'Lutron',
        'HQR': 'Lutron',
        'LQSE-': 'Lutron',
        'PD8-': 'Lutron',
        'PD10-': 'Lutron',
        'PDW-': 'Lutron',
        'QS-': 'Lutron',
        'QSPS-': 'Lutron',
        'HW': 'Lutron',
        'QN': 'Samsung',
        'SA-': 'Middle Atlantic',
        'SS42': 'Pakedge',
        'AN-': 'Araknis',
        'BR1': 'Middle Atlantic',
        'IS8': 'James Loudspeaker',
        'IS-': 'James Loudspeaker',
        'SPL': 'Sonance',
        'BIJOU': 'Anthem',
        'RM-': 'Middle Atlantic',
        'PS': 'Sanus',
        'UB': 'Sanus',
        'OV': 'Origin Acoustics',
        'RZ': 'SunBrite',
    }
    
    for prefix, brand in brand_patterns.items():
        if part_upper.startswith(prefix.upper()):
            return brand
    
    return ""


def get_unique_products_with_quantities(products: List[ProductFromCSV]) -> List[ProductFromCSV]:
    """
    Consolidate duplicate products and sum their quantities.
    Useful when the same product appears multiple times in the CSV.
    """
    product_map = {}
    
    for product in products:
        # Use part_number if available, otherwise brand+model
        if product.part_number:
            key = product.part_number.lower()
        else:
            key = (product.brand.lower(), product.model.lower())
        
        if key in product_map:
            product_map[key].quantity += product.quantity
        else:
            product_map[key] = product
    
    return list(product_map.values())


def detect_racks_from_csv(csv_path: str) -> List[RackFromCSV]:
    """
    Detect rack(s) specified in the CSV file.
    
    Looks for entries that are racks themselves (not rack-mounted equipment).
    Common patterns:
    - Part numbers containing "RACK", "RK-", "ERK-", "SR-"
    - Model numbers like "ERK-4425", "RK-42", "SR-42-26"
    - Generic "EQUIPMENT RACK" entries
    
    Returns:
        List of RackFromCSV objects with detected size and quantity
    """
    racks = []
    
    # Keywords that identify a rack (not rack-mounted equipment)
    rack_keywords = ['equipment rack', 'av rack', 'network rack', 'server rack', 'data rack']
    
    # Model patterns that indicate racks with size info
    # Format: (pattern_prefix, typical brand)
    rack_model_patterns = {
        'ERK-': 'Middle Atlantic',      # ERK-4425 = 44U, 25" deep
        'SSRK-': 'Middle Atlantic',     # SSRK-42 = 42U slim
        'RK-': 'Middle Atlantic',       # RK-42 = 42U
        'SR-': 'Middle Atlantic',       # SR-42-26 = 42U, 26" deep
        'WRK-': 'Middle Atlantic',      # Wall-mount rack
        'CFR-': 'Middle Atlantic',      # CFR-12-18 = 12U
        'QUIK-': 'Middle Atlantic',     # Quick-frame
        'MRK-': 'Middle Atlantic',      # MRK series
        'AXS-': 'Middle Atlantic',      # AXS series
        '42U': 'Generic',
        '48U': 'Generic', 
        '24U': 'Generic',
        '18U': 'Generic',
        '12U': 'Generic',
        'RE42-': 'Chief',
        'CMS-': 'Chief',
    }
    
    # Try different encodings
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    file_content = None
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                file_content = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    if file_content is None:
        return []
    
    import io
    import re
    f = io.StringIO(file_content)
    reader = csv.DictReader(f)
    
    for row in reader:
        # Get relevant fields
        part_number = row.get('Part Number', row.get('Model', '')).strip()
        name = row.get('Name', part_number).strip()
        location = row.get('LocationPath', row.get('Location', '')).strip()
        system = row.get('System', row.get('Category', '')).strip()
        
        # Skip placeholder items (start with ~)
        if part_number.startswith('~') or name.startswith('~'):
            continue
        
        try:
            quantity = int(float(row.get('Quantity', 1) or 1))
        except ValueError:
            quantity = 1
        
        part_lower = part_number.lower()
        name_lower = name.lower()
        combined = f"{part_lower} {name_lower}"
        
        # Check if this is a rack (not rack-mounted equipment)
        is_rack = any(kw in combined for kw in rack_keywords)
        
        # Also check model patterns
        for pattern in rack_model_patterns.keys():
            if pattern.lower() in part_lower or pattern.lower() in name_lower:
                is_rack = True
                break
        
        if not is_rack:
            continue
        
        # Now try to determine the rack size
        size_u = 42  # Default to 42U if we can't determine
        
        # Try to extract size from model number
        # Patterns like: ERK-4425, RK-42, 42U, SR-42-26
        size_patterns = [
            r'(\d{2})U',           # 42U, 48U, etc.
            r'ERK-(\d{2})',        # ERK-44xx
            r'SSRK-(\d{2})',       # SSRK-42
            r'RK-(\d{2})',         # RK-42
            r'SR-(\d{2})',         # SR-42-26
            r'MRK-(\d{2})',        # MRK-44
            r'CFR-(\d{1,2})',      # CFR-12-18
            r'WRK-(\d{1,2})',      # WRK-8
            r'-(\d{2})[-\s]?[Uu]', # Generic -42U pattern
            r'(\d{2})[-\s]?[Rr][Uu]', # 42RU pattern
        ]
        
        for pattern in size_patterns:
            match = re.search(pattern, part_number, re.IGNORECASE)
            if not match:
                match = re.search(pattern, name, re.IGNORECASE)
            if match:
                extracted = int(match.group(1))
                # Sanity check - racks are typically 8-52U
                if 8 <= extracted <= 52:
                    size_u = extracted
                    break
        
        # Determine rack type based on location/system
        rack_type = "AV"  # Default
        if 'network' in location.lower() or 'network' in system.lower():
            rack_type = "Network"
        elif 'server' in location.lower() or 'data' in system.lower():
            rack_type = "Network"
        
        rack = RackFromCSV(
            model=part_number or name,
            size_u=size_u,
            quantity=quantity,
            location=location,
            rack_type=rack_type
        )
        racks.append(rack)
    
    return racks


def get_rack_info_from_csv(csv_path: str) -> dict:
    """
    Get rack configuration info from the CSV.
    
    Returns dict with:
        - racks: List of RackFromCSV objects found
        - total_racks: Total number of physical racks
        - av_rack_size: Size to use for AV rack (or None)
        - network_rack_size: Size to use for Network rack (or None)
        - default_size: Suggested default size if no racks found
    """
    racks = detect_racks_from_csv(csv_path)
    
    result = {
        'racks': racks,
        'total_racks': sum(r.quantity for r in racks),
        'av_rack_size': None,
        'network_rack_size': None,
        'default_size': 42  # Fallback default
    }
    
    if not racks:
        return result
    
    # Find the largest rack for default
    sizes = [r.size_u for r in racks]
    result['default_size'] = max(sizes)
    
    # Try to identify AV vs Network racks
    for rack in racks:
        if rack.rack_type == "Network" and result['network_rack_size'] is None:
            result['network_rack_size'] = rack.size_u
        elif rack.rack_type == "AV" and result['av_rack_size'] is None:
            result['av_rack_size'] = rack.size_u
        elif result['av_rack_size'] is None:
            # Default untyped racks to AV
            result['av_rack_size'] = rack.size_u
    
    return result


if __name__ == "__main__":
    # Test with the sample CSV
    import sys
    
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/henryjohnson/Desktop/clean_import_ready.csv"
    
    print(f"📄 Parsing CSV: {csv_path}")
    print("-" * 60)
    
    products = parse_client_csv(csv_path)
    products = get_unique_products_with_quantities(products)
    
    print(f"Found {len(products)} rack-mountable products:\n")
    
    for p in products:
        print(f"  • {p.brand} {p.model}")
        print(f"    Category: {p.category}")
        print(f"    Quantity: {p.quantity}")
        print(f"    BTU: {p.calculated_btu}")
        print()

