#!/usr/bin/env python3
"""
AV Rack Documentation Generator
Phase 1: Basic Rack Elevation PDF Generation

This script:
1. Reads a client proposal CSV
2. Looks up product details from MySQL Product Catalog (with OpenAI fallback)
3. Arranges equipment in rack (heavy at bottom, with vents distributed)
4. Generates a professional PDF rack elevation diagram

Usage:
    python generate_rack_docs.py <csv_file> [options]
    
Example:
    python generate_rack_docs.py /path/to/client_proposal.csv --project "Smith Residence" --output ./output
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

from csv_parser import parse_client_csv, get_unique_products_with_quantities, ProductFromCSV, get_rack_info_from_csv
from openai_client import get_openai_client
from rack_arranger import RackItem, RackItemType, arrange_rack, expand_quantities, print_rack_layout
from pdf_generator import generate_rack_pdf

# MySQL Database support (replaces Airtable)
try:
    from db_client import get_database, MYSQL_AVAILABLE
    DATABASE_AVAILABLE = MYSQL_AVAILABLE
except (ImportError, ValueError) as e:
    DATABASE_AVAILABLE = False
    print(f"ℹ️  MySQL Database not configured: {e}")

# Display name overrides for products with confusing part numbers
DISPLAY_NAME_OVERRIDES = {
    'pkg-macunlimited-3pfl-02': 'Savant Pro Host 5200',
    'pkg-macunlimited': 'Savant Pro Host 5200',
    'pkg-s2rem-40': 'Savant Smart Host',
    'pkg-s2rem': 'Savant Smart Host',
    'rck-5000': 'Savant Rack Mount Kit',
    'ssl-evomace-1yr': 'Savant License (1yr)',
    'ssc-0012': 'Savant Expansion Module',
}


def split_into_av_and_network_racks(rack_items: list[RackItem]) -> tuple[list[RackItem], list[RackItem]]:
    """
    Split rack items into AV equipment and Network equipment.
    
    Priority:
    1. Use Subsystem field from Airtable Brain if available
    2. Fall back to brand/model keyword matching
    
    AV Rack: Savant audio/control, Lutron, power conditioners for AV
    Network Rack: Ubiquiti, Pakedge, Araknis, network switches, routers
    
    Returns:
        (av_items, network_items)
    """
    av_items = []
    network_items = []
    
    # Keywords to identify network equipment (fallback if no Subsystem)
    network_brands = ['ubiquiti', 'pakedge', 'araknis', 'cisco', 'netgear', 'access networks']
    network_models = ['usw-', 'udm-', 'uap-', 'an-', 'ss42', 'switch', 'router', 'gateway']
    
    # Keywords to identify AV equipment (fallback if no Subsystem)
    av_brands = ['savant', 'lutron', 'sonance', 'james', 'anthem', 'marantz', 'denon', 
                 'crown', 'bowers', 'b&k', 'b & k', 'sonos', 'control4']
    av_models = ['pav-', 'ssc-', 'svr-', 'rck-', 'rmb-', 'cli-', 'pkg-', 'hqp', 'hqr', 
                'amp', 'receiver', 'processor']
    
    for item in rack_items:
        # First, check if Subsystem was set from Airtable Brain
        subsystem = getattr(item, 'subsystem', None) or ''
        subsystem_lower = subsystem.lower() if subsystem else ''
        
        if 'network' in subsystem_lower or 'net' in subsystem_lower:
            network_items.append(item)
            continue
        elif 'av' in subsystem_lower or 'audio' in subsystem_lower or 'video' in subsystem_lower:
            av_items.append(item)
            continue
        
        # Fallback: Use brand/model keywords
        brand_lower = item.brand.lower() if item.brand else ""
        model_lower = item.model.lower() if item.model else ""
        name_lower = item.name.lower() if item.name else ""
        
        # Check if it's network equipment
        is_network = (
            any(nb in brand_lower for nb in network_brands) or
            any(nm in model_lower for nm in network_models) or
            any(nm in name_lower for nm in network_models)
        )
        
        # Check if it's AV equipment
        is_av = (
            any(ab in brand_lower for ab in av_brands) or
            any(am in model_lower for am in av_models) or
            any(am in name_lower for am in av_models)
        )
        
        # Categorize - if both match, prefer AV (more common case)
        # If neither match, put in AV rack (better for power/misc items)
        if is_network and not is_av:
            network_items.append(item)
        else:
            av_items.append(item)
    
    return av_items, network_items


def is_clearly_not_rack_mountable(product) -> bool:
    """
    Quick filter to skip items that are obviously not rack-mountable
    based on name, category, or missing critical info.
    """
    # Must have at least a model or part number
    if not product.model and not product.part_number:
        return True
    
    # Check for non-rack keywords in name/category
    # Normalize strings - remove hidden/special characters that break matching
    import re
    def normalize(s):
        if not s:
            return ''
        # Remove non-ASCII characters and normalize
        return re.sub(r'[^\x00-\x7F]+', '', s).lower().strip()
    
    name = normalize(product.name)
    category = normalize(product.category)
    model = normalize(product.model)
    part_number = normalize(product.part_number)
    brand = normalize(product.brand)
    location = normalize(getattr(product, 'location', ''))
    
    # Check if item is assigned to a specific room (distributed equipment)
    # These go in local closets, not the main rack
    equipment_area_keywords = ['equipment closet', 'equipment room', 'systems:', 'mdf', 'idf', 'rack']
    room_indicators = ['kitchen', 'den', 'suite', 'bedroom', 'bathroom', 'living', 'dining', 
                       'office', 'garage', 'basement', 'attic', 'patio', 'pool', 'theater',
                       'media room', 'gym', 'wine', 'laundry', 'entry', 'foyer', 'hallway']
    
    # Equipment that ALWAYS goes in rack regardless of location assignment
    # (These are assigned to rooms for logical grouping, but physically in rack)
    always_rack_equipment = [
        'amplifier', 'amp', 'receiver', 'avr', 'processor', 'preamp',
        'sonos amp', 'denon', 'marantz avr', 'anthem', 'arcam',
        'sony str', 'straz', 'yamaha rx', 'onkyo',
        # Savant packages with rack-mount hosts
        'pkg-s2rem', 's2rem', 'rack mount smart host',
    ]
    is_always_rack = any(kw in name or kw in model or kw in category for kw in always_rack_equipment)
    
    # If location contains a room name but NOT an equipment area, it's distributed
    # UNLESS it's equipment that always goes in the rack
    is_room_location = any(room in location for room in room_indicators)
    is_equipment_area = any(eq in location for eq in equipment_area_keywords)
    
    if is_room_location and not is_equipment_area and not is_always_rack:
        return True  # Skip distributed equipment
    
    # ACCESSORY patterns - these are NEVER rack-mountable
    accessory_patterns = [
        'uacc-',           # Ubiquiti accessories (cables, connectors, HDDs)
        'sfp', 'sfp+', 'sfp28',  # SFP modules and cables
        '-hdd-',           # Hard drives (accessories)
        'uplink',          # Uplink cables
        '-cm-',            # Connector modules
        'rj45-mg',         # RJ45 connectors
        'data-sfp',        # SFP data cables
        'conn-',           # Connectors
        'data-lan',        # LAN cables
    ]
    if any(acc in model or acc in part_number for acc in accessory_patterns):
        return True  # Skip accessories
    
    # WiFi access points - mount on ceilings/walls, not racks
    wifi_ap_patterns = [
        'u6-', 'u7-',       # Ubiquiti U6/U7 series APs
        'uap-',             # Ubiquiti UniFi APs
        ' e7', '-e7',       # Ubiquiti E7 APs
        'e7 campus',        # Ubiquiti E7 Campus
        'wifi ap', 'wi-fi ap',
        # Ruckus APs - outdoor and indoor, all wall/ceiling mounted
        '9u1-t310',         # Ruckus T310 outdoor AP
        '9u1-t350',         # Ruckus T350 outdoor AP
        '9u1-r',            # Ruckus indoor APs (R510, R650, etc.)
        't310', 't350', 't610', 't710',  # Ruckus outdoor APs
        # Access Networks/Ruckus APs
        '901-r',            # Access Networks/Ruckus indoor APs
        'access point',
    ]
    model_check = f" {model} "  # Add spaces for word boundary
    if any(ap in model_check or ap in model or ap in part_number for ap in wifi_ap_patterns):
        return True  # Skip WiFi APs
    
    # Check for exact model matches for E7 APs
    if model.strip() in ['e7', 'e7 campus']:
        return True
    
    # Lutron lighting devices - ALL go in electrical panels, enclosures, or walls
    # None are standard 19" rack-mount - they use DIN rail
    lutron_non_rack = [
        'lqse-',      # Load controllers (electrical panel)
        'pdw-',       # Pico dimmers (wall)
        'pd8-', 'pd10-',  # Dimmers (wall)
        'qs-wlb',     # Wireless link bridge
        'hqr-',       # Repeaters
        'qsps-',      # Power supply
        'hwnw-kp',    # Keypads (wall)
        'ebb-',       # Enclosure back box
        'hqp',        # HomeWorks QS Processor (DIN rail, not rack-mount)
        # RadioRA 2 devices - ALL wall-mounted
        'rrd-pro',    # RadioRA 2 dimmers (wall box)
        'rrd-6',      # RadioRA 2 dimmers (wall box)
        'rrd-8',      # RadioRA 2 switches (wall box - like RRD-8ANS)
        'rr-aux',     # RadioRA 2 auxiliary repeaters (wall-mounted)
        'rr-main',    # RadioRA 2 main repeaters (wall-mounted)
        'rr-sel',     # RadioRA 2 select
        'rrd-w',      # RadioRA 2 wallbox devices
    ]
    if any(lut in model or lut in part_number for lut in lutron_non_rack):
        return True  # Skip Lutron - all are DIN rail or wall-mount
    
    # Software licenses, accessories, and non-physical items
    non_physical_items = [
        'ssl-',       # Savant software licenses
        '-1yr', '-2yr', '-3yr',  # Software subscriptions
        'license',
        'rck-',       # Rack mount kits (accessories, not equipment)
        'ssc-',       # Expansion modules/accessories
        'rmb-',       # Rack mount brackets
    ]
    if any(npi in model or npi in part_number for npi in non_physical_items):
        return True  # Skip non-physical items
    
    # Wall-mounted sensors, thermostats, and HVAC controllers
    climate_devices = [
        'cli-thfm',   # Savant climate/thermostat sensors
        'cli-8000',   # Savant climate controller (installs at HVAC unit)
        'thfm',       # Thermostat sensors
        'sensor',     # Generic sensors
        'thermostat',
        'hvac',
    ]
    if any(cd in model or cd in part_number for cd in climate_devices):
        return True  # Skip climate/HVAC devices
    
    # Rack itself and rack accessories/packages (not equipment IN the rack)
    rack_accessories = [
        'equipment rack',  # The rack itself
        'sa-20',           # Middle Atlantic shelf package
        'sa-10',           # Middle Atlantic shelf package
        'shelf',           # Shelves
        'caster',          # Casters
        'side panel',
        'door',
        'fan kit',
        # Strong rack packages - the rack itself, not equipment
        'sr-cust-',        # Strong custom rack packages
        'sr-rack',         # Strong racks
        'sr-fs-system',    # Strong FS Series rack systems
        '-pkg',            # Rack packages
        'rack system',     # Generic rack system
    ]
    if any(ra in model or ra in name for ra in rack_accessories):
        return True  # Skip rack structure items
    
    # Ring and doorbell devices - wall/door mounted, not rack
    doorbell_camera_devices = [
        'ring ',           # Ring doorbells/cameras
        '8ssxe',           # Ring Pro 2 doorbell
        '8spps',           # Ring spotlight camera
        '8sn1s',           # Ring stick up camera
        'doorbell',
        'video doorbell',
        'ring alarm',
        'ring cam',
    ]
    if any(dc in model or dc in name or dc in part_number for dc in doorbell_camera_devices):
        return True  # Skip Ring and doorbell devices
    
    # Vertical power strips - mount on SIDE of rack, not in front RU space
    vertical_power_strips = [
        'wb-800vps',       # WattBox vertical power strips
        '800vps',          # WattBox vertical power strips
        'vps-ipvm',        # WattBox VPS series
        'vertical power',
    ]
    if any(vps in model or vps in part_number for vps in vertical_power_strips):
        return True  # Skip vertical/side-mounted power strips
    
    # Network equipment brands - include main equipment (not accessories)
    network_brands = ['araknis', 'ubiquiti', 'cisco', 'netgear', 'pakedge', 'access networks', 'motu']
    if any(nb in brand for nb in network_brands):
        return False  # Keep network equipment (already filtered accessories above)
    
    # Networking category - ALWAYS include
    if 'networking' in category or 'switches' in category:
        return False
    
    skip_keywords = [
        'pre-wire', 'prewire', 'pre wire',
        'cable', 'wire ', ' wire', 'wiring',
        'in-wall', 'in-ceiling', 'in wall', 'in ceiling',
        'outdoor speaker', 'outdoor monitor',
        'screen', 'projector mount', 'tv mount',
        'wallplate', 'wall plate', 'faceplate',
        'keypad', 'dimmer',
        'sensor', 'slab sensor',
        'back box', 'backbox', 'junction',
        'allowance', 'labor', 'installation',
        # ICE cables - all are wire/cable products
        'ice cable', 'ice ', '14-2cs', '16-2cs', 'cat 6a', 'rg-6',
        # WirePath - keystone jacks, wallplates, structured wiring
        'wirepath', 'wp-cat', 'rj45-',
        # Carlon - electrical boxes
        'carlon', 'sc100a',
        # Projectors (ceiling mounted)
        'projector', 'vpl-', 'vplvw', 'epson',
        # Projection screens (motorized/fixed)
        'severtson', 'seymour', 'if169', '2f120',
        # Speakers and subwoofers (in-wall/in-ceiling/outdoor)
        'isw4', 'isw-4',           # B&W in-wall subwoofer
        'cwm7', 'cwm 7', 'cwm-7',  # B&W in-wall speakers
        'ccm',                      # B&W in-ceiling speakers (CCM 362, CCM 632, etc.)
        'am-1',                     # B&W outdoor speakers
        'marine',                   # B&K marine speakers
        'sa63', 'sa-63',           # James Loudspeaker subwoofer/speaker enclosures
        'sa250',                   # B&K amplifiers (standalone, not rack)
        # Triad Speakers (in-wall/in-ceiling)
        'triad', '44406', '44408',
        # Sonance ceiling/in-wall speakers
        'sonance', 'vp64', 'vpxt6', 'vp-64', 'vpxt-6',
        # Savant sensors
        'sst-temp', 'sst-',        # Savant temperature sensors
        'cli-slab', 'slab',        # Savant SLAB sensors
        # Lutron RD-RD (relay device, wall/panel mount)
        'rd-rd',
        # Brackets and mounts (not rack equipment)
        'pmk', 'bracket', 'mount',
        # iPort wall stations and cases (wall-mounted, not rack)
        'iport', 'luxe', 'wallstation', 'lx case',
        # Shade/window treatment pre-wire
        'shade', 'motorized window',
        # Marantz receiver (standalone, not rack-mount without kit)
        'marantz', 'sr6015',
        # Turntables (standalone, not rack equipment)
        'turntable', 'victrola',
        # Touch panels (wall-mounted)
        'itp-e',
    ]
    
    # Categories that are definitely not rack equipment
    skip_categories = [
        'speakers > in-wall', 'speakers > in-ceiling', 'speakers > outdoor',
        'projection screens', 'mounts', 'wire and cable',
        'lighting > keypads', 'lighting > dimmers', 'lighting > switches',
        'motorized window treatments',
    ]
    
    combined_text = f"{name} {category}"
    
    for keyword in skip_keywords:
        if keyword in combined_text:
            return True
    
    for skip_cat in skip_categories:
        if skip_cat in category:
            return True
    
    return False


def enrich_products_with_specs(products: list[ProductFromCSV], use_database: bool = True, use_ai: bool = True) -> list[RackItem]:
    """
    Get product specifications and create RackItems.
    
    Priority:
    1. D-Tools racks.db (fastest, most accurate)
    2. MySQL Product Catalog (if configured)
    3. OpenAI GPT-4 (fallback for products not in database)
    4. CSV defaults (last resort)
    """
    rack_items = []
    specs_lookup = {}
    products_needing_ai = []
    
    # Pre-filter: Skip obviously non-rack items
    filtered_products = []
    for product in products:
        if is_clearly_not_rack_mountable(product):
            print(f"  ⏭️  Pre-filter skip: {product.brand} {product.model or product.name}")
            continue
        filtered_products.append(product)
    
    products = filtered_products
    print(f"📦 {len(products)} products after pre-filter\n")
    
    # Step 0: Try D-Tools racks.db first (fastest, most accurate)
    products_not_in_dtools = []
    try:
        from import_dtools_products import get_equipment_specs
        print("📚 Looking up products in D-Tools catalog (racks.db)...")
        dtools_found = 0
        
        for product in products:
            model_num = product.part_number or product.model
            dtools_specs = get_equipment_specs(model=model_num, part_number=product.part_number)
            
            if dtools_specs and dtools_specs.get('rack_units', 0) > 0:
                lookup_key = f"{product.brand} {product.model}".strip().lower()
                # If we have rack_units > 0, it's rack-mountable regardless of the flag
                specs_lookup[lookup_key] = {
                    'rack_units': dtools_specs['rack_units'],
                    'weight': dtools_specs.get('weight', 5.0) or 5.0,
                    'btu': dtools_specs.get('btu', 0) or 0,
                    'depth': dtools_specs.get('depth', 0) or 0,
                    'is_rack_mountable': True,  # Has RU height = rack-mountable
                    'subsystem': '',
                }
                dtools_found += 1
                print(f"  📚 D-Tools: {product.brand} {product.model}: {dtools_specs['rack_units']}U, {dtools_specs.get('watts', 0)}W")
            else:
                products_not_in_dtools.append(product)
        
        print(f"\n✅ Found {dtools_found} products in D-Tools catalog")
        if products_not_in_dtools:
            print(f"⚠️  {len(products_not_in_dtools)} products not in D-Tools (will try MySQL/OpenAI)\n")
    except ImportError:
        print("ℹ️  D-Tools catalog not available, using MySQL/OpenAI")
        products_not_in_dtools = list(products)
    except Exception as e:
        print(f"⚠️  D-Tools lookup failed: {e}")
        products_not_in_dtools = list(products)
    
    # Step 1: Try MySQL Database for remaining products
    if use_database and DATABASE_AVAILABLE and products_not_in_dtools:
        try:
            db = get_database()
            print("✅ Connected to MySQL Product Catalog\n")
            
            print("🗄️  Looking up remaining products in MySQL...")
            db_found = 0
            missing_models = []
            
            for product in products_not_in_dtools:
                # Try to find in database by model number or part number
                model_num = product.part_number or product.model
                db_specs = db.get_rack_specs(model_num)
                
                if db_specs:
                    lookup_key = f"{product.brand} {product.model}".strip().lower()
                    specs_lookup[lookup_key] = db_specs
                    db_found += 1
                    
                    # Show subsystem if available
                    subsystem = db_specs.get('subsystem', '')
                    subsystem_str = f" [{subsystem}]" if subsystem else ""
                    print(f"  🗄️  DB: {product.brand} {product.model}: {db_specs.get('rack_units')}U, {db_specs.get('watts', 0)}W{subsystem_str}")
                else:
                    # Model not found in database - print warning
                    missing_models.append(model_num)
                    print(f"  ⚠️  Model [{model_num}] not found in database")
                    products_needing_ai.append(product)
            
            print(f"\n✅ Found {db_found} products in database")
            if missing_models:
                print(f"⚠️  {len(missing_models)} models not in database (will try OpenAI)\n")
            
        except Exception as e:
            print(f"⚠️  Database lookup failed: {e}")
            products_needing_ai = list(products_not_in_dtools)
    else:
        products_needing_ai = list(products_not_in_dtools)
        if use_database and not DATABASE_AVAILABLE and products_not_in_dtools:
            print("ℹ️  MySQL Database not configured, using OpenAI only")
    
    # Step 2: Use OpenAI for products not found in Airtable
    if use_ai and products_needing_ai:
        try:
            ai_client = get_openai_client()
            print("✅ Connected to OpenAI\n")
            
            # Prepare products for batch lookup
            product_dicts = [
                {
                    "brand": p.brand,
                    "model": p.model,
                    "category": p.category,
                    "name": p.name
                }
                for p in products_needing_ai
            ]
            
            print(f"📡 Sending {len(products_needing_ai)} products to GPT-4o...")
            ai_specs = ai_client.get_product_specs(product_dicts)
            
            # Merge AI specs into lookup
            for key, value in ai_specs.items():
                if key not in specs_lookup:
                    specs_lookup[key] = value
            
            print(f"✅ Received specs for {len(ai_specs)} products from OpenAI\n")
            
        except Exception as e:
            print(f"⚠️  Could not connect to OpenAI: {e}")
            print("   Using default values from CSV...")
    elif not use_ai:
        print("ℹ️  AI lookup disabled")
    
    # Step 3: Build rack items from specs
    for product in products:
        # Look up specs
        lookup_key = f"{product.brand} {product.model}".strip().lower()
        specs = specs_lookup.get(lookup_key, {})
        
        if specs:
            # Check if it's rack mountable
            if not specs.get('is_rack_mountable', True):
                print(f"  ⏭️  Skipping (not rack-mountable): {product.brand} {product.model}")
                continue
            
            rack_units_raw = specs.get('rack_units', 0)
            # Round up fractional rack units (can't have 0.5U in a real rack)
            import math
            rack_units = math.ceil(rack_units_raw) if rack_units_raw > 0 else 0
            
            if rack_units == 0:
                print(f"  ⏭️  Skipping (0U): {product.brand} {product.model}")
                continue
            
            source = specs.get('source', 'ai')
            source_icon = "📗" if source == 'airtable' else "🤖"
            
            # Apply display name override if available
            display_model = product.model
            model_key = (product.model or '').lower().strip()
            if model_key in DISPLAY_NAME_OVERRIDES:
                display_model = DISPLAY_NAME_OVERRIDES[model_key]
                print(f"  {source_icon} {product.brand} {display_model} (was {product.model}): {rack_units}U, {specs.get('weight', 0)}lbs, {specs.get('btu', 0)} BTU")
            else:
                print(f"  {source_icon} {product.brand} {product.model}: {rack_units}U, {specs.get('weight', 0)}lbs, {specs.get('btu', 0)} BTU")
            
            rack_item = RackItem(
                item_type=RackItemType.EQUIPMENT,
                name=product.name,
                brand=product.brand,
                model=display_model,
                rack_units=int(rack_units),
                weight=specs.get('weight', 10.0),
                btu=specs.get('btu', 0) or product.calculated_btu or 0,
                connections=specs.get('connections'),
                quantity=product.quantity,
                subsystem=specs.get('subsystem', '')  # AV or Network from Brain
            )
            rack_items.append(rack_item)
        else:
            # If OpenAI didn't return specs, it's likely not rack-mountable - skip it
            print(f"  ⏭️  Skipping (not in AI response): {product.brand} {product.model}")
    
    return rack_items


def estimate_rack_units(category: str) -> int:
    """Estimate rack units based on product category"""
    category_lower = category.lower()
    
    if 'receiver' in category_lower or 'surround' in category_lower:
        return 3  # AVRs are typically 3U
    elif 'amplifier' in category_lower or 'amp' in category_lower:
        return 2
    elif 'switch' in category_lower:
        return 1
    elif 'controller' in category_lower or 'processor' in category_lower:
        return 2
    elif 'power' in category_lower:
        return 2
    else:
        return 1  # Default to 1U


def estimate_weight(category: str) -> float:
    """Estimate weight based on product category"""
    category_lower = category.lower()
    
    if 'receiver' in category_lower or 'surround' in category_lower:
        return 25.0  # AVRs are heavy
    elif 'amplifier' in category_lower or 'amp' in category_lower:
        return 20.0
    elif 'power' in category_lower:
        return 12.0
    elif 'switch' in category_lower:
        return 5.0
    else:
        return 8.0  # Default


def estimate_btu(category: str) -> float:
    """Estimate BTU based on product category"""
    category_lower = category.lower()
    
    if 'receiver' in category_lower or 'surround' in category_lower:
        return 400
    elif 'amplifier' in category_lower or 'amp' in category_lower:
        return 600
    elif 'power' in category_lower:
        return 50
    elif 'switch' in category_lower:
        return 30
    else:
        return 100  # Default


def main():
    parser = argparse.ArgumentParser(
        description="Generate AV rack elevation documentation from client CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_rack_docs.py proposal.csv
  python generate_rack_docs.py proposal.csv --project "Smith Residence" --rack-size 42
  python generate_rack_docs.py proposal.csv --no-ai --output ./pdfs
        """
    )
    
    parser.add_argument(
        "csv_file",
        help="Path to client proposal CSV file"
    )
    
    parser.add_argument(
        "--project", "-p",
        default="AV System",
        help="Project name for documentation (default: 'AV System')"
    )
    
    parser.add_argument(
        "--company", "-c",
        default="Your Company",
        help="Company name for title block (default: 'Your Company')"
    )
    
    parser.add_argument(
        "--rack-size", "-r",
        type=int,
        default=42,
        help="Rack size in U (default: 42)"
    )
    
    parser.add_argument(
        "--output", "-o",
        default=".",
        help="Output directory for generated PDFs (default: current directory)"
    )
    
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip OpenAI lookup, use CSV defaults only"
    )
    
    parser.add_argument(
        "--no-database",
        action="store_true",
        help="Skip MySQL database lookup, use OpenAI only"
    )
    
    parser.add_argument(
        "--location",
        default=None,
        help="Filter products by location (default: include all locations, let AI filter rack-mountable)"
    )
    
    parser.add_argument(
        "--split-racks",
        action="store_true",
        help="Split equipment into separate AV and Network racks"
    )
    
    parser.add_argument(
        "--page-size",
        default="tabloid",
        choices=["letter", "tabloid", "arch_c", "arch_d"],
        help="PDF page size: letter (8.5x11), tabloid (11x17), arch_c (18x24), arch_d (24x36). Default: tabloid"
    )
    
    args = parser.parse_args()
    
    # Validate input file
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"❌ Error: CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Create output directory if needed
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*60)
    print("🔧 AV RACK DOCUMENTATION GENERATOR - Phase 1")
    print("="*60 + "\n")
    
    # Step 0: Detect racks from CSV
    print(f"📄 Reading CSV: {csv_path}")
    rack_info = get_rack_info_from_csv(str(csv_path))
    
    if rack_info['racks']:
        print(f"\n🗄️  Detected {rack_info['total_racks']} rack(s) in CSV:")
        for rack in rack_info['racks']:
            print(f"   • {rack.model}: {rack.size_u}U x{rack.quantity} ({rack.rack_type}) @ {rack.location}")
        
        # Use detected rack size unless user overrode it
        if args.rack_size == 42:  # Default wasn't changed
            args.rack_size = rack_info['default_size']
            print(f"\n   📐 Using detected rack size: {args.rack_size}U")
    else:
        print(f"\n   ℹ️  No rack enclosures found in CSV, using default: {args.rack_size}U")
    
    # Step 1: Parse CSV
    products = parse_client_csv(str(csv_path), equipment_location=args.location)
    products = get_unique_products_with_quantities(products)
    
    if not products:
        print(f"❌ No products found in '{args.location}' location.")
        print("   Check the CSV 'Location' column matches your filter.")
        sys.exit(1)
    
    print(f"   Found {len(products)} unique products for rack\n")
    
    # Step 2: Enrich with database and/or OpenAI
    print("🤖 Analyzing products...")
    rack_items = enrich_products_with_specs(
        products, 
        use_database=not args.no_database,
        use_ai=not args.no_ai
    )
    
    # Step 3: Expand quantities (each unit gets its own slot)
    rack_items = expand_quantities(rack_items)
    print(f"\n📦 Total items to rack: {len(rack_items)} units\n")
    
    # Calculate total U needed
    total_u_needed = sum(item.rack_units for item in rack_items)
    
    # Check if we should split racks (either by flag or auto-detect overflow)
    if args.split_racks or total_u_needed > (args.rack_size - 3):
        if total_u_needed > (args.rack_size - 3):
            print(f"⚠️  Equipment ({total_u_needed}U) exceeds rack capacity ({args.rack_size - 3}U available)")
            print("   Auto-splitting into AV and Network racks...\n")
        
        return generate_split_racks(
            rack_items, 
            args.rack_size, 
            args.project, 
            args.company, 
            output_dir,
            rack_info=rack_info,
            page_size=args.page_size
        )
    
    # Single rack mode
    print(f"🗄️  Arranging equipment in {args.rack_size}U rack...")
    layout = arrange_rack(rack_items, rack_size_u=args.rack_size)
    layout.project_name = args.project
    
    # Show text preview
    print_rack_layout(layout)
    
    # Generate PDF
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_project_name = args.project.replace(" ", "_").replace("/", "-")
    output_filename = f"Rack_Elevation_{safe_project_name}_{timestamp}.pdf"
    output_path = output_dir / output_filename
    
    print(f"\n📑 Generating PDF ({args.page_size.upper()}): {output_path}")
    generate_rack_pdf(
        layout=layout,
        output_path=str(output_path),
        project_name=args.project,
        company_name=args.company,
        revision="A",
        page_size=args.page_size
    )
    
    print(f"\n✅ SUCCESS! PDF generated: {output_path}")
    print(f"\n{'='*60}\n")
    
    return str(output_path)


def generate_split_racks(rack_items, rack_size, project, company, output_dir, rack_info=None, page_size="tabloid"):
    """Generate a single PDF with AV and Network racks on separate pages"""
    
    av_items, network_items = split_into_av_and_network_racks(rack_items)
    
    # Calculate if AV rack needs to be larger
    av_u = sum(item.rack_units for item in av_items)
    # Add estimated vents (roughly 1 vent per 3U of equipment)
    av_u_with_vents = av_u + (len(av_items) // 2)
    
    # Use detected rack sizes from CSV if available
    if rack_info and rack_info.get('av_rack_size'):
        av_rack_size = rack_info['av_rack_size']
        # But still allow scaling up if needed
        if av_u_with_vents > (av_rack_size - 4):
            av_rack_size = 48
    else:
        # Use 48U for AV if needed, otherwise use specified size
        av_rack_size = 48 if av_u_with_vents > (rack_size - 4) else rack_size
    
    # Network rack size - use detected or default
    if rack_info and rack_info.get('network_rack_size'):
        network_rack_size = rack_info['network_rack_size']
    else:
        network_rack_size = rack_size
    
    av_u = sum(item.rack_units for item in av_items)
    net_u = sum(item.rack_units for item in network_items)
    
    print(f"📊 Split Summary:")
    print(f"   🎵 AV Rack: {len(av_items)} items, {av_u}U")
    print(f"   🌐 Network Rack: {len(network_items)} items, {net_u}U\n")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_project_name = project.replace(" ", "_").replace("/", "-")
    
    # Collect all layouts for multi-page PDF
    layouts = []
    
    # Generate AV Rack layout
    if av_items:
        print(f"{'='*60}")
        print(f"🎵 AV RACK ({av_rack_size}U)")
        print(f"{'='*60}")
        
        av_layout = arrange_rack(av_items, rack_size_u=av_rack_size)
        av_layout.project_name = f"{project} - AV Rack ({av_rack_size}U)"
        print_rack_layout(av_layout)
        layouts.append(av_layout)
    
    # Generate Network Rack layout
    if network_items:
        print(f"\n{'='*60}")
        print(f"🌐 NETWORK RACK ({network_rack_size}U)")
        print(f"{'='*60}")
        
        net_layout = arrange_rack(network_items, rack_size_u=network_rack_size)
        net_layout.project_name = f"{project} - Network Rack ({network_rack_size}U)"
        print_rack_layout(net_layout)
        layouts.append(net_layout)
    
    # Generate single multi-page PDF
    output_filename = f"Rack_Elevation_{safe_project_name}_{timestamp}.pdf"
    output_path = output_dir / output_filename
    
    print(f"\n📑 Generating PDF ({page_size.upper()}, {len(layouts)} page(s)): {output_path}")
    generate_rack_pdf(
        layout=layouts,  # Pass list of layouts for multi-page
        output_path=str(output_path),
        project_name=project,
        company_name=company,
        revision="A",
        page_size=page_size
    )
    
    print(f"\n{'='*60}")
    print(f"✅ SUCCESS! Generated rack elevation PDF with {len(layouts)} page(s):")
    print(f"   📄 {output_path}")
    if av_items:
        print(f"      • Page 1: AV Rack ({av_rack_size}U) - {len(av_items)} items")
    if network_items:
        page_num = 2 if av_items else 1
        print(f"      • Page {page_num}: Network Rack ({network_rack_size}U) - {len(network_items)} items")
    print(f"{'='*60}\n")
    
    return str(output_path)


if __name__ == "__main__":
    main()

