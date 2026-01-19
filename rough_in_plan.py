#!/usr/bin/env python3
"""
Rough-In Wiring Plan Generator
Creates electrician / low-voltage rough-in reference PDFs

Goal: Tell trades WHERE to run wire, HOW MANY, and TO WHERE
NOT a block diagram, NOT a schematic - a practical wiring plan
"""

import csv
import sys
import argparse
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, TABLOID
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# Import rack generation modules
try:
    from rack_arranger import RackLayout, RackItem, RackItemType, arrange_rack
    from csv_parser import parse_client_csv, get_unique_products_with_quantities
    HAS_RACK_MODULES = True
except ImportError:
    HAS_RACK_MODULES = False

# Import enrichment functions for actual rack specs
try:
    from generate_rack_docs import enrich_products_with_specs, split_into_av_and_network_racks
    HAS_ENRICHMENT = True
except ImportError:
    HAS_ENRICHMENT = False

# Import D-Tools catalog for accurate specs (try both import scripts)
HAS_DTOOLS_CATALOG = False
try:
    from import_dtools_products import get_equipment_specs as get_rack_specs
    HAS_DTOOLS_CATALOG = True
except ImportError:
    try:
        from import_dtools_catalog import get_rack_specs
        HAS_DTOOLS_CATALOG = True
    except ImportError:
        pass

try:
    import fitz  # PyMuPDF for floorplan background
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

# SVG icon support
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
    HAS_SVGLIB = True
except ImportError:
    HAS_SVGLIB = False

# =============================================================================
# RACK ITEM EXCLUSIONS AND DISPLAY NAME OVERRIDES
# (Same rules as generate_rack_docs.py for consistency)
# =============================================================================

# Items that should NOT appear in rack elevation (not rack-mounted)
RACK_EXCLUSION_PATTERNS = [
    # Rack structure itself
    'equipment rack', 'sa-20', 'sa-10', 'sr-cust-', 'sr-rack', '-pkg', 'sr-fs-system', 'rack system',
    # Accessories and non-physical items
    'rck-', 'ssl-', 'ssc-', 'rmb-', '-1yr', '-2yr', '-3yr', 'license',
    # Ubiquiti accessories
    'uacc-', '-hdd-', 'uplink', '-cm-', 'rj45-mg', 'data-sfp', 'conn-', 'data-lan',
    # WiFi APs (ceiling/wall mount)
    'e7', 'uap-', 'u6-', 'u7-',
    # Ruckus APs (ceiling/wall/outdoor mount)
    '9u1-t310', '9u1-t350', '9u1-r', 't310', 't350', 't610', 't710', '901-r',
    # Lutron RadioRA 2 (wall box devices, not rack-mount)
    'rrd-pro', 'rrd-6', 'rrd-8', 'rrd-w', 'rr-aux', 'rr-main', 'rr-sel', 'rd-rd',
    # Lutron HomeWorks/RadioRA (DIN rail, not 19" rack)
    'lqse-', 'pdw-', 'pd8-', 'pd10-', 'qs-wlb', 'hqr-', 'qsps-', 'hwnw-kp', 'ebb-', 'hqp',
    # Lutron cables (QSH-CBL = shade cable)
    'qsh-cbl', '-cbl-',
    # Climate devices (wall/HVAC mounted)
    'cli-thfm', 'cli-8000', 'thfm', 'thermostat', 'sst-temp', 'sst-', 'cli-slab', 'slab',
    # Vertical power strips (side-mounted)
    'wb-800vps', '800vps', 'vps-ipvm',
    # Ring and doorbell devices (wall/door mount)
    'ring ', '8ssxe', '8spps', '8sn1s', 'doorbell', 'ring alarm',
    # Cables and wiring (ICE Cable, etc.)
    'ice cable', 'ice ', '14-2cs', '16-2cs', 'cat 6a', 'rg-6', 'cable', 'wire',
    # WirePath - keystone jacks, wallplates, structured wiring
    'wirepath', 'wp-cat', 'rj45-',
    # Electrical boxes (Carlon, etc.)
    'carlon', 'sc100a', 'back box', 'junction',
    # Projectors (ceiling mounted) - include model numbers
    'projector', 'vpl-', 'vplvw', 'epson', 'ls12000', 'ls11000', 'ls10000',
    # Projector mounts (Strong, etc.)
    'sm-proj', 'proj-mount', 'projector mount',
    # Projection screens (motorized/fixed)
    'severtson', 'seymour', 'if169', '2f120', 'screen',
    # Speakers and subwoofers (in-wall/in-ceiling/outdoor - not rack mount)
    'isw4', 'isw-4', 'cwm7', 'cwm 7', 'cwm-7', 'ccm', 'am-1', 'marine',
    'sa63', 'sa-63', 'sa250',  # James Loudspeaker, B&K amp
    # Triad Speakers (in-wall/in-ceiling)
    'triad', '44406', '44408',
    # Sonance ceiling/in-wall speakers
    'sonance', 'vp64', 'vpxt6', 'vp-64', 'vpxt-6',
    # Brackets and mounts (not rack equipment)
    'pmk', 'bracket', 'mount',
    # iPort wall stations and cases (wall-mounted, not rack)
    'iport', 'luxe', 'wallstation', 'lx case',
    # Shade/window treatment pre-wire
    'shade', 'motorized window', 'pre-wire', 'prewire',
    # Marantz receiver (standalone, not rack-mount without kit)
    'marantz', 'sr6015',
    # Turntables (standalone, not rack equipment)
    'turntable', 'victrola',
    # Touch panels (wall-mounted)
    'itp-e',
]

# Display name overrides for confusing part numbers
DISPLAY_NAME_OVERRIDES = {
    'pkg-macunlimited-3pfl-02': 'Savant Pro Host 5200',
    'pkg-macunlimited': 'Savant Pro Host 5200',
    'pkg-s2rem-40': 'Savant Smart Host',
    'pkg-s2rem': 'Savant Smart Host',
}

def is_rack_excluded(model: str, part_number: str = "", name: str = "") -> bool:
    """Check if an item should be excluded from rack display"""
    model_lower = (model or '').lower()
    part_lower = (part_number or '').lower()
    name_lower = (name or '').lower()
    combined = f"{model_lower} {part_lower} {name_lower}"
    
    for pattern in RACK_EXCLUSION_PATTERNS:
        if pattern in combined:
            return True
    return False

def get_display_name(model: str) -> str:
    """Get friendly display name for a model number"""
    model_key = (model or '').lower().strip()
    return DISPLAY_NAME_OVERRIDES.get(model_key, model)

# Icon paths - map device types to SVG file names
ICON_PATH = Path(__file__).parent / "assets" / "icons"
DEVICE_ICONS = {
    'tv': 'TV.svg',
    'speaker': 'Speaker.svg',
    'subwoofer': 'Subwoofer.svg',
    'keypad': 'Keypad.svg',
    'camera': 'Camera.svg',
    'wap': 'WAP.svg',
    'touch_panel': 'TouchPanel.svg',
    'thermostat': 'Thermostat.svg',
    'video_rx': 'VideoRx.svg',
    # Distributed/local equipment (installed in room, not main rack)
    'bijou': 'VideoRx.svg',           # Bijou amplifiers - use video rx icon
    'local_amp': 'Speaker.svg',       # Use speaker icon for local amps
    'local_switch': 'WAP.svg',        # Use network icon for local switches
    'climate_sensor': 'Thermostat.svg',  # Climate sensors
    'hvac_controller': 'Thermostat.svg', # HVAC controllers
    'climate_ctrl': 'Thermostat.svg', # Use thermostat icon for climate controllers
}

# Display labels for device types
DEVICE_LABELS = {
    'tv': 'TV',
    'speaker': 'Speaker',
    'subwoofer': 'Subwoofer',
    'lcr_bar': 'LCR Bar',
    'keypad': 'Keypad',
    'keypad_wireless': 'Keypad (Wireless)',
    'camera': 'Camera',
    'wap': 'WiFi AP',
    'touch_panel': 'Touch Panel',
    'thermostat': 'Thermostat',
    'video_rx': 'Video Receiver',
    'local_amp': 'Local Amp (Bijou)',
    'local_switch': 'Local Switch',
    'climate_ctrl': 'Climate Controller',
}


# =============================================================================
# CONFIGURABLE WIRING ASSUMPTIONS (edit these defaults as needed)
# =============================================================================

WIRING_RULES = {
    # CAT6 runs per device type
    'tv_cat6': 2,              # TV locations: 2x CAT6 (network + spare)
    'keypad_cat6': 1,          # Keypads/controllers: 1x CAT6
    'touch_panel_cat6': 1,     # Touch panels: 1x CAT6
    'camera_cat6': 1,          # Security cameras: 1x CAT6
    'wap_cat6': 1,             # WiFi access points: 1x CAT6
    'video_rx_cat6': 1,        # IP video receivers: 1x CAT6
    'thermostat_cat6': 1,      # Thermostats: 1x CAT6
    
    # Distributed/local equipment (installed in room)
    'local_amp_cat6': 1,       # Local amp (Bijou): 1x CAT6 for network
    'local_switch_cat6': 2,    # Local switch: 2x CAT6 (uplink + spare)
    'climate_ctrl_cat6': 1,    # Climate controller: 1x CAT6
    
    # Speaker wire runs
    'speaker_wire_per_pair': 2,  # 2-conductor per speaker pair
    'subwoofer_wire': 1,         # Subwoofer runs
    
    # HDMI runs (only for local/short runs)
    'hdmi_local': 1,           # HDMI for local runs only
    
    # Control wiring
    'keypad_control_wire': 1,  # Low-voltage control to keypads
}

# =============================================================================
# ZONE MODE CONFIGURATION
# =============================================================================

ZONES = [
    {"name": "HEAD-END / RACK", "type": "headend", "color": "#2C3E50"},
    {"name": "VIDEO ENDPOINTS", "type": "endpoints", "color": "#3498DB"},
    {"name": "AUDIO ZONES", "type": "endpoints", "color": "#27AE60"},
    {"name": "LIGHTING CONTROL", "type": "systems", "color": "#F39C12"},
    {"name": "NETWORK & WIFI", "type": "systems", "color": "#E67E22"},
    {"name": "SECURITY / CCTV", "type": "systems", "color": "#E74C3C"},
    {"name": "ACCESS / INTERCOM", "type": "systems", "color": "#9B59B6"},
    {"name": "UNASSIGNED / TBD", "type": "fallback", "color": "#95A5A6"},
]

# Zone assignment keywords
ZONE_KEYWORDS = {
    "NETWORK & WIFI": [
        "switch", "router", "firewall", "ap", "wap", "wifi", "wi-fi", 
        "access point", "network", "ubiquiti", "unifi", "uap", "usw", "udm"
    ],
    "LIGHTING CONTROL": [
        "lutron", "homeworks", "keypad", "dimmer", "panel", "processor",
        "lighting control", "pico", "seetouch", "palladiom", "hqp", "hqr",
        "brkt:ctrl keypad", "brkt:ctrl wireless"
    ],
    "SECURITY / CCTV": [
        "camera", "nvr", "dvr", "cctv", "security", "surveillance",
        "doorbell", "protect", "brkt:cctv"
    ],
    "VIDEO ENDPOINTS": [
        "tv", "display", "projector", "receiver", "video rx", "balun",
        "ps65", "ps80", "ub32", "brkt:vid tv", "brkt:vid display", "samsung", "lg"
    ],
    "AUDIO ZONES": [
        "speaker", "subwoofer", "amp", "amplifier", "audio", "sonance",
        "origin", "james", "triad", "brkt:spk", "brkt:sub", "brkt:aud"
    ],
    "ACCESS / INTERCOM": [
        "door", "gate", "intercom", "entry", "doorbird", "2n"
    ],
}


def assign_zone(item_name: str, category: str = "", system: str = "") -> str:
    """Assign an item to a logical zone based on keywords"""
    combined = f"{item_name} {category} {system}".lower()
    
    for zone_name, keywords in ZONE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined:
                return zone_name
    
    return "UNASSIGNED / TBD"


# =============================================================================
# DEVICE IDENTIFICATION
# =============================================================================

# BRKT: entries are the actual rough-in locations in SI/AVC format CSVs
# Map BRKT: types to device types
BRKT_DEVICE_MAP = {
    # Video/Display locations
    'brkt:vid tv': 'tv',
    'brkt:vid display': 'tv',
    'brkt:vid projector': 'tv',
    # Speaker locations
    'brkt:spk round': 'speaker',
    'brkt:spk square': 'speaker',
    'brkt:spk rect': 'speaker',
    'brkt:spk lcr': 'speaker',  # LCR bar / soundbar
    'brkt:spk': 'speaker',
    'brkt:sub': 'subwoofer',
    'brkt:aud': 'speaker',
    # Network/WiFi locations
    'brkt:network wireless': 'wap',
    'brkt:network wap': 'wap',
    # Control locations
    'brkt:ctrl keypad': 'keypad',
    'brkt:ctrl touchpanel': 'touch_panel',
    'brkt:ctrl': 'keypad',  # Generic control
    # HVAC locations
    'brkt:hvac remote sensor': 'thermostat',
    'brkt:hvac thermostat': 'thermostat',
    # Security/Camera locations
    'brkt:cctv': 'camera',
    'brkt:security camera': 'camera',
    'brkt:doorbell': 'camera',
    'brkt:camera': 'camera',
}

# Device keywords for identification (fallback for non-BRKT entries)
# Use more specific patterns to avoid false matches (e.g., "catv" shouldn't match "tv")
DEVICE_KEYWORDS = {
    # TVs - use specific model patterns, not generic "tv"
    'tv': ['qn65', 'qn75', 'qn85', 'oled55', 'oled65', 'oled77',
           'sunbrite', 'veranda', 'terrace', 'samsung qn', 'lg oled', 'sony xr'],
    # Speakers - specific brands/models
    'speaker': ['sonance', 'origin acoustics', 'james loudspeaker', 'triad', 'kef', 
                'is8-', 'is6-', 'is4-', 'speakercraft', 'bowers'],
    # Keypads - specific models
    'keypad': ['pico-', 'seetouch', 'hybrid keypad', 'palladiom', 'sunnata', 
               'claro', 'diva', 'maestro', 'rrk-', 'rrd-'],
    # Cameras - specific models
    'camera': ['g4-dome', 'g4-pro', 'g5-', 'unifi protect', 'ava-', 'avigilon'],
    # WiFi APs - specific models (ceiling/wall mount)
    'wap': ['uap-', 'u6-pro', 'u6-lite', 'u6-lr', 'u7-', 'flexhd', 'nanohd', 'e7'],
    # Touch panels
    'touch_panel': ['touchpanel', 'wall display', 'crestron ts', 'savant touch'],
    # Video receivers (IP video)
    'video_rx': ['ps65-', 'ps80-', 'ub32-', 'sav-ps'],
    # Thermostats
    'thermostat': ['thermostat', 'nest-', 'ecobee', 'cli-thfm'],
    # Local/distributed amplifiers (not in main rack)
    'local_amp': ['bijou', 'nano-', 'sav-lpam'],
    # Local/distributed network switches (not in main rack)
    'local_switch': ['usw-pro-xg-8', 'usw-flex', 'usw-lite'],
    # Climate controllers (at HVAC unit)
    'climate_ctrl': ['cli-8000'],
}

# Cable/wire entries to skip (these are footage quantities, not device counts)
CABLE_PREFIXES = [
    'cat6:', 'cat6a:', 'cat5:', 'cat5e:', 'rg6:', 'rg6qs:', 'rg59:', 
    '14/2:', '16/2:', '18/2:', '14/4:', '16/4:', '18/4:', '22/', '24/',
    'coax:', 'hdmi:', 'fiber:', 'sdi:', 'dmx:', 'xlr:', 'optical:',
    'conn-', 'wp-', 'plate:', 'data-', 'video-', 'audio-', 'control -',
    '~', 'interface -', 'device -', 'network ', 'ip ', 'ui -',
]

# Part numbers that are placeholders, not actual equipment
SKIP_PART_NUMBERS = [
    'tv',  # Generic "TV" placeholder
    'display',  # Generic placeholder
    'speaker',  # Generic placeholder
    'keypad',  # Generic placeholder
]

# Items to skip (not rough-in related)
SKIP_KEYWORDS = [
    'rack', 'shelf', 'blank', 'vent', 'spacer', 'bolt', 'screw', 'remote',
    'programming', 'labor', 'installation', 'licence', 'license',
    'subscription', 'service', '~', 'equipment closet', 'closet', 'mdf', 'idf'
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class RoughInDevice:
    """A device that requires rough-in wiring"""
    name: str
    device_type: str  # tv, speaker, keypad, camera, wap, touch_panel, video_rx
    quantity: int = 1
    location: str = ""
    notes: str = ""


@dataclass
class RoomWiring:
    """Wiring requirements for a single room"""
    room_name: str
    room_number: str = ""
    devices: List[RoughInDevice] = field(default_factory=list)
    
    # Calculated cable counts
    cat6_count: int = 0
    speaker_wire_count: int = 0
    hdmi_count: int = 0
    control_wire_count: int = 0
    
    def calculate_cables(self):
        """Calculate total cable counts based on devices"""
        self.cat6_count = 0
        self.speaker_wire_count = 0
        self.hdmi_count = 0
        self.control_wire_count = 0
        
        for device in self.devices:
            qty = device.quantity
            dtype = device.device_type
            
            if dtype == 'tv':
                self.cat6_count += qty * WIRING_RULES['tv_cat6']
            elif dtype == 'keypad':
                self.cat6_count += qty * WIRING_RULES['keypad_cat6']
                self.control_wire_count += qty * WIRING_RULES['keypad_control_wire']
            elif dtype == 'touch_panel':
                self.cat6_count += qty * WIRING_RULES['touch_panel_cat6']
            elif dtype == 'camera':
                self.cat6_count += qty * WIRING_RULES['camera_cat6']
            elif dtype == 'wap':
                self.cat6_count += qty * WIRING_RULES['wap_cat6']
            elif dtype == 'video_rx':
                self.cat6_count += qty * WIRING_RULES['video_rx_cat6']
            elif dtype == 'thermostat':
                self.cat6_count += qty * WIRING_RULES['thermostat_cat6']
            elif dtype == 'speaker':
                self.speaker_wire_count += qty * WIRING_RULES['speaker_wire_per_pair']
            elif dtype == 'subwoofer':
                self.speaker_wire_count += qty * WIRING_RULES['subwoofer_wire']


@dataclass
class ZoneWiring:
    """Wiring requirements for a logical zone (zone mode)"""
    zone_name: str
    zone_type: str = "systems"  # headend, endpoints, systems, fallback
    zone_color: str = "#34495E"
    devices: List[RoughInDevice] = field(default_factory=list)
    
    # Calculated cable counts
    cat6_count: int = 0
    speaker_wire_count: int = 0
    control_wire_count: int = 0
    
    def calculate_cables(self):
        """Calculate total cable counts based on devices"""
        self.cat6_count = 0
        self.speaker_wire_count = 0
        self.control_wire_count = 0
        
        for device in self.devices:
            qty = device.quantity
            dtype = device.device_type
            
            if dtype == 'tv':
                self.cat6_count += qty * WIRING_RULES['tv_cat6']
            elif dtype == 'keypad':
                self.cat6_count += qty * WIRING_RULES['keypad_cat6']
                self.control_wire_count += qty * WIRING_RULES['keypad_control_wire']
            elif dtype == 'touch_panel':
                self.cat6_count += qty * WIRING_RULES['touch_panel_cat6']
            elif dtype == 'camera':
                self.cat6_count += qty * WIRING_RULES['camera_cat6']
            elif dtype == 'wap':
                self.cat6_count += qty * WIRING_RULES['wap_cat6']
            elif dtype == 'video_rx':
                self.cat6_count += qty * WIRING_RULES['video_rx_cat6']
            elif dtype == 'thermostat':
                self.cat6_count += qty * WIRING_RULES['thermostat_cat6']
            elif dtype == 'speaker':
                self.speaker_wire_count += qty * WIRING_RULES['speaker_wire_per_pair']
            elif dtype == 'subwoofer':
                self.speaker_wire_count += qty * WIRING_RULES['subwoofer_wire']
    
    def calculate_cables(self):
        """Calculate total cable counts based on devices"""
        self.cat6_count = 0
        self.speaker_wire_count = 0
        self.hdmi_count = 0
        self.control_wire_count = 0
        
        for device in self.devices:
            qty = device.quantity
            dtype = device.device_type
            
            if dtype == 'tv':
                self.cat6_count += qty * WIRING_RULES['tv_cat6']
            elif dtype == 'keypad':
                self.cat6_count += qty * WIRING_RULES['keypad_cat6']
                self.control_wire_count += qty * WIRING_RULES['keypad_control_wire']
            elif dtype == 'touch_panel':
                self.cat6_count += qty * WIRING_RULES['touch_panel_cat6']
            elif dtype == 'camera':
                self.cat6_count += qty * WIRING_RULES['camera_cat6']
            elif dtype == 'wap':
                self.cat6_count += qty * WIRING_RULES['wap_cat6']
            elif dtype == 'video_rx':
                self.cat6_count += qty * WIRING_RULES['video_rx_cat6']
            elif dtype == 'thermostat':
                self.cat6_count += qty * WIRING_RULES['thermostat_cat6']
            elif dtype == 'speaker':
                # Speakers: each speaker needs a wire run
                self.speaker_wire_count += qty * WIRING_RULES['speaker_wire_per_pair']
            elif dtype == 'subwoofer':
                # Subwoofer runs
                self.speaker_wire_count += qty * WIRING_RULES['subwoofer_wire']


# =============================================================================
# CSV PARSING
# =============================================================================

def identify_device_type(name: str, part_number: str = "") -> Optional[str]:
    """Identify what type of rough-in device this is"""
    part_lower = part_number.lower().strip()
    name_lower = name.lower().strip()
    combined = f"{part_lower} {name_lower}"
    
    # Skip cable/wire entries (these are footage quantities like "150,CAT6:DAT")
    for prefix in CABLE_PREFIXES:
        if part_lower.startswith(prefix.lower()):
            return None
    
    # Skip generic placeholder part numbers
    if part_lower in SKIP_PART_NUMBERS:
        return None
    
    # Check skip keywords
    for skip in SKIP_KEYWORDS:
        if skip.lower() in combined:
            return None
    
    # Check for BRKT: entries first (these are the actual rough-in locations)
    for brkt_pattern, device_type in BRKT_DEVICE_MAP.items():
        if brkt_pattern in part_lower or brkt_pattern in name_lower:
            return device_type
    
    # Fallback: Check device keywords for actual equipment part numbers
    # Only match if the keyword appears at start of a word (more precise)
    for device_type, keywords in DEVICE_KEYWORDS.items():
        for kw in keywords:
            # Use word boundary matching to avoid partial matches like "catv" matching "tv"
            pattern = r'\b' + re.escape(kw.lower())
            if re.search(pattern, combined):
                return device_type
    
    return None


def parse_location(location_path: str) -> Tuple[str, str]:
    """
    Parse location path into room number and room name
    e.g., "1st Level: 102 - Kitchen" -> ("102", "Kitchen")
    e.g., "Exterior: 001 - Exterior" -> ("001", "Exterior")
    e.g., "Systems: Network & WiFi" -> ("", "Network & WiFi")
    """
    if not location_path:
        return ("", "Unknown")
    
    # Handle "Level: Room" format (SI/AVC style)
    # Pattern: "1st Level: 102 - Kitchen" or "Exterior: 001 - Exterior"
    match = re.search(r':\s*(\d+[A-Za-z]?)\s*-\s*(.+)$', location_path)
    if match:
        room_num = match.group(1).strip()
        room_name = match.group(2).strip()
        # Remove any sub-location after >
        if '>' in room_name:
            room_name = room_name.split('>')[0].strip()
        return (room_num, room_name)
    
    # Handle "Systems: Name" format
    if ':' in location_path:
        parts = location_path.split(':')
        if len(parts) >= 2:
            area = parts[0].strip()
            name = parts[1].strip()
            if '>' in name:
                name = name.split('>')[0].strip()
            return ("", f"{area}: {name}")
    
    # Fallback: try simple "Number Name" format
    match = re.match(r'^(\d+)\s*(.+)$', location_path.strip())
    if match:
        return (match.group(1), match.group(2).strip())
    
    return ("", location_path.strip())


def parse_csv_for_rough_in(csv_path: str) -> Dict[str, RoomWiring]:
    """
    Parse CSV and extract rough-in wiring requirements per room
    """
    rooms: Dict[str, RoomWiring] = {}
    
    # Try multiple encodings
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
        print("❌ Could not decode CSV file")
        return rooms
    
    import io
    reader = csv.DictReader(io.StringIO(file_content))
    
    for row in reader:
        # Get location and part info
        location_path = row.get('LocationPath', row.get('Location', '')).strip()
        part_number = row.get('Part Number', row.get('Model', '')).strip()
        name = row.get('Name', part_number).strip()
        system = row.get('System', row.get('Category', '')).strip()
        
        # Get quantity
        try:
            quantity = int(float(row.get('Quantity', 1) or 1))
            if quantity <= 0:
                continue
        except ValueError:
            quantity = 1
        
        # Skip rack/closet equipment (head-end equipment, not room rough-in)
        location_lower = location_path.lower()
        if any(x in location_lower for x in ['equipment closet', 'equipment room', 'av closet', 
                                              'network closet', 'server room', 'mdf', 'idf', 
                                              'rack room', 'mechanical']):
            continue
        
        # Identify device type
        device_type = identify_device_type(name, part_number)
        if device_type is None:
            continue
        
        # Parse room info
        room_number, room_name = parse_location(location_path)
        room_key = f"{room_number} {room_name}".strip()
        
        if not room_key or room_key == "Unknown":
            continue
        
        # Create or update room
        if room_key not in rooms:
            rooms[room_key] = RoomWiring(
                room_name=room_name,
                room_number=room_number
            )
        
        # Add device (don't aggregate - each unique part_number counts once)
        # Use part_number as unique identifier to prevent duplicates
        existing = next((d for d in rooms[room_key].devices 
                        if d.name == name[:30] and d.device_type == device_type), None)
        if existing:
            # Same exact item, just increment quantity
            existing.quantity += quantity
        else:
            # New device entry
            rooms[room_key].devices.append(RoughInDevice(
                name=name[:30],  # Truncate for display
                device_type=device_type,
                quantity=quantity,
                location=location_path
            ))
    
    # Calculate cable requirements for each room
    for room in rooms.values():
        room.calculate_cables()
    
    return rooms


def parse_csv_for_zones(csv_path: str) -> Dict[str, ZoneWiring]:
    """
    Parse CSV and extract rough-in wiring requirements by logical zone.
    Used when room data is missing or --mode zone is specified.
    """
    zones: Dict[str, ZoneWiring] = {}
    
    # Initialize zones from config
    for zone_config in ZONES:
        if zone_config["type"] != "headend":  # Skip head-end, it's drawn separately
            zones[zone_config["name"]] = ZoneWiring(
                zone_name=zone_config["name"],
                zone_type=zone_config["type"],
                zone_color=zone_config["color"]
            )
    
    # Try multiple encodings
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
        print("❌ Could not decode CSV file")
        return zones
    
    import io
    reader = csv.DictReader(io.StringIO(file_content))
    
    for row in reader:
        # Get part info
        part_number = row.get('Part Number', row.get('Model', '')).strip()
        name = row.get('Name', part_number).strip()
        system = row.get('System', row.get('Category', '')).strip()
        location = row.get('LocationPath', row.get('Location', '')).strip()
        
        # Get quantity
        try:
            quantity = int(float(row.get('Quantity', 1) or 1))
            if quantity <= 0:
                continue
        except ValueError:
            quantity = 1
        
        # Identify device type
        device_type = identify_device_type(name, part_number)
        if device_type is None:
            continue
        
        # Assign to zone based on keywords
        zone_name = assign_zone(part_number, system, location)
        
        # Ensure zone exists
        if zone_name not in zones:
            zone_name = "UNASSIGNED / TBD"
        
        # Add device to zone
        existing = next((d for d in zones[zone_name].devices 
                        if d.device_type == device_type), None)
        if existing:
            existing.quantity += quantity
        else:
            zones[zone_name].devices.append(RoughInDevice(
                name=name[:30],
                device_type=device_type,
                quantity=quantity,
                location=location
            ))
    
    # Calculate cable requirements for each zone
    for zone in zones.values():
        zone.calculate_cables()
    
    # Remove empty zones
    zones = {k: v for k, v in zones.items() if v.devices}
    
    return zones


# =============================================================================
# PDF GENERATION
# =============================================================================

class RoughInPlanGenerator:
    """Generates the rough-in wiring plan PDF"""
    
    def __init__(self, project_name: str = "Sample Residence", 
                 page_size=landscape(TABLOID), mode: str = "room"):
        self.project_name = project_name
        self.page_size = page_size
        self.width, self.height = page_size
        self.mode = mode  # "room" or "zone"
        
        # Layout settings - electrician friendly (larger fonts, clearer)
        self.margin = 0.5 * inch
        self.header_height = 1.0 * inch
        self.footer_height = 0.5 * inch
        
        # Room/Zone box settings
        self.room_box_w = 2.6 * inch
        self.room_box_h = 1.6 * inch
        self.room_gap_x = 0.3 * inch
        self.room_gap_y = 0.4 * inch
        
        # Zone box settings (slightly larger for zone mode)
        self.zone_box_w = 2.8 * inch
        self.zone_box_h = 1.8 * inch
        self.zone_gap_x = 0.4 * inch
        self.zone_gap_y = 0.5 * inch
        
        # Head-end box
        self.headend_w = 2.8 * inch
        self.headend_h = 1.0 * inch
        
        # Colors (minimal, professional)
        self.color_headend = colors.HexColor('#2C3E50')  # Dark blue-gray
        self.color_room = colors.HexColor('#34495E')     # Slate gray
        self.color_cable = colors.HexColor('#7F8C8D')    # Medium gray
        self.color_cat6 = colors.HexColor('#3498DB')     # Blue
        self.color_speaker = colors.HexColor('#27AE60')  # Green
        self.color_hdmi = colors.HexColor('#E74C3C')     # Red
        self.color_control = colors.HexColor('#9B59B6')  # Purple
        
        # Pre-load icons
        self.icons = {}
        self._load_icons()
    
    def _load_icons(self):
        """Pre-load SVG icon paths for device types"""
        if not HAS_SVGLIB:
            print("⚠️ svglib not available, using text fallback for icons")
            return
        
        for device_type, icon_file in DEVICE_ICONS.items():
            icon_path = ICON_PATH / icon_file
            if icon_path.exists():
                # Store the path, not the drawing (to avoid mutation issues)
                self.icons[device_type] = str(icon_path)
    
    def _draw_icon_and_text(self, c, x: float, y: float, device_type: str, 
                           label: str, qty: int, icon_size: float = 12):
        """Draw an icon with text label. Falls back to bullet if icon unavailable."""
        text_x = x + 10  # Default offset for bullet
        icon_drawn = False
        
        # Try to draw SVG icon
        if device_type in self.icons and HAS_SVGLIB:
            try:
                # Load fresh drawing each time to avoid mutation
                icon_path = self.icons[device_type]
                drawing = svg2rlg(icon_path)
                
                if drawing and drawing.width > 0 and drawing.height > 0:
                    # Calculate scale
                    scale = icon_size / max(drawing.width, drawing.height)
                    
                    # Apply scale to the drawing
                    drawing.width = icon_size
                    drawing.height = icon_size
                    drawing.scale(scale, scale)
                    
                    # Render the icon
                    renderPDF.draw(drawing, c, x, y - 3)
                    text_x = x + icon_size + 6
                    icon_drawn = True
            except Exception as e:
                # Silent fallback
                pass
        
        # Fallback to bullet if icon didn't render
        if not icon_drawn:
            c.drawString(x, y, "•")
            text_x = x + 10
        
        # Draw the label text
        c.drawString(text_x, y, f"{label} ({qty})")
    
    def generate(self, rooms: Dict[str, RoomWiring], output_path: str,
                 floorplan_path: Optional[str] = None):
        """Generate the rough-in plan PDF"""
        
        c = canvas.Canvas(output_path, pagesize=self.page_size)
        
        # Draw background floorplan if provided
        if floorplan_path and HAS_FITZ:
            self._draw_floorplan_background(c, floorplan_path)
        
        # Draw header
        self._draw_header(c)
        
        # Calculate usable area (leave space at bottom for centered legend)
        usable_y_top = self.height - self.header_height - self.margin
        usable_y_bottom = self.footer_height + 1.8 * inch  # Space for legend at bottom
        
        # Head-end box position at top center
        headend_x = (self.width - self.headend_w) / 2
        headend_y = usable_y_top - self.headend_h - 0.2 * inch
        
        # Calculate grid for rooms
        room_list = list(rooms.items())
        num_rooms = len(room_list)
        
        if num_rooms == 0:
            c.setFont("Helvetica", 14)
            c.drawCentredString(self.width / 2, self.height / 2,
                               "No rough-in devices found in CSV")
            self._draw_headend_box(c, headend_x, headend_y)
        else:
            # Calculate grid dimensions - more columns for better fit
            cols = min(5, num_rooms)  # Max 5 columns
            rows = (num_rooms + cols - 1) // cols
            
            # Available space for rooms (below head-end with gap for lines)
            homerun_gap = 1.0 * inch  # Space between head-end and rooms for lines
            room_area_top = headend_y - homerun_gap
            room_area_height = room_area_top - usable_y_bottom
            
            # Calculate actual spacing
            total_room_width = cols * self.room_box_w + (cols - 1) * self.room_gap_x
            start_x = (self.width - total_room_width) / 2
            
            row_height = self.room_box_h + self.room_gap_y
            total_rows_height = rows * row_height
            
            # Start rooms from top of room area, working down
            start_y = room_area_top - self.room_box_h
            
            # First, draw all homerun lines (behind everything)
            for idx, (room_key, room) in enumerate(room_list):
                col = idx % cols
                row = idx // cols
                
                x = start_x + col * (self.room_box_w + self.room_gap_x)
                y = start_y - row * row_height
                
                # Draw homerun line to head-end
                self._draw_homerun(c, x + self.room_box_w / 2, 
                                  y + self.room_box_h,
                                  headend_x + self.headend_w / 2,
                                  headend_y,
                                  room)
            
            # Then draw head-end box (on top of lines)
            self._draw_headend_box(c, headend_x, headend_y)
            
            # Finally draw room boxes (on top of lines)
            for idx, (room_key, room) in enumerate(room_list):
                col = idx % cols
                row = idx // cols
                
                x = start_x + col * (self.room_box_w + self.room_gap_x)
                y = start_y - row * row_height
                
                self._draw_room_box(c, x, y, room_key, room)
        
        # Draw legend
        self._draw_legend(c)
        
        # Draw footer
        self._draw_footer(c)
        
        c.save()
        print(f"✅ Generated: {output_path}")
        return output_path
    
    def generate_zones(self, zones: Dict[str, ZoneWiring], output_path: str):
        """Generate the rough-in plan PDF in zone mode"""
        
        c = canvas.Canvas(output_path, pagesize=self.page_size)
        
        # Draw header with zone mode indicator
        self._draw_header(c, zone_mode=True)
        
        # Calculate usable area
        usable_y_top = self.height - self.header_height - self.margin
        usable_y_bottom = self.footer_height + 1.6 * inch  # Space for legend
        
        # Head-end box position at top center
        headend_x = (self.width - self.headend_w) / 2
        headend_y = usable_y_top - self.headend_h - 0.2 * inch
        
        # Calculate grid for zones
        zone_list = list(zones.items())
        num_zones = len(zone_list)
        
        if num_zones == 0:
            c.setFont("Helvetica", 14)
            c.drawCentredString(self.width / 2, self.height / 2,
                               "No rough-in devices found in CSV")
            self._draw_headend_box(c, headend_x, headend_y)
        else:
            # Calculate grid dimensions - fewer columns for larger zone boxes
            cols = min(4, num_zones)
            rows = (num_zones + cols - 1) // cols
            
            # Available space for zones
            homerun_gap = 0.8 * inch
            zone_area_top = headend_y - homerun_gap
            
            # Calculate spacing
            total_zone_width = cols * self.zone_box_w + (cols - 1) * self.zone_gap_x
            start_x = (self.width - total_zone_width) / 2
            
            row_height = self.zone_box_h + self.zone_gap_y
            start_y = zone_area_top - self.zone_box_h
            
            # First, draw all homerun lines (behind everything)
            for idx, (zone_name, zone) in enumerate(zone_list):
                col = idx % cols
                row = idx // cols
                
                x = start_x + col * (self.zone_box_w + self.zone_gap_x)
                y = start_y - row * row_height
                
                # Draw zone homerun line
                self._draw_zone_homerun(c, x + self.zone_box_w / 2, 
                                       y + self.zone_box_h,
                                       headend_x + self.headend_w / 2,
                                       headend_y,
                                       zone)
            
            # Draw head-end box
            self._draw_headend_box(c, headend_x, headend_y)
            
            # Draw zone boxes
            for idx, (zone_name, zone) in enumerate(zone_list):
                col = idx % cols
                row = idx // cols
                
                x = start_x + col * (self.zone_box_w + self.zone_gap_x)
                y = start_y - row * row_height
                
                self._draw_zone_box(c, x, y, zone)
        
        # Draw legend
        self._draw_legend(c)
        
        # Draw zone mode footer with disclaimer
        self._draw_footer(c, zone_mode=True)
        
        c.save()
        print(f"✅ Generated (Zone Mode): {output_path}")
        return output_path
    
    def _draw_zone_box(self, c, x: float, y: float, zone: ZoneWiring):
        """Draw a zone box with aggregated device counts"""
        # Box background
        c.setFillColor(colors.HexColor('#F8F9FA'))
        zone_color = colors.HexColor(zone.zone_color)
        c.setStrokeColor(zone_color)
        c.setLineWidth(2)
        c.roundRect(x, y, self.zone_box_w, self.zone_box_h, 6, fill=1, stroke=1)
        
        # Zone header bar
        header_h = 24
        c.setFillColor(zone_color)
        c.roundRect(x, y + self.zone_box_h - header_h, self.zone_box_w, header_h, 
                   6, fill=1, stroke=0)
        c.rect(x, y + self.zone_box_h - header_h, self.zone_box_w, header_h / 2, 
               fill=1, stroke=0)
        
        # Zone name
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.white)
        c.drawCentredString(x + self.zone_box_w / 2, y + self.zone_box_h - 17, 
                           zone.zone_name)
        
        # Device list with icons
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont("Helvetica", 9)
        
        line_y = y + self.zone_box_h - header_h - 16
        line_height = 14
        
        # Aggregate devices by type
        device_summary = defaultdict(int)
        for device in zone.devices:
            device_summary[device.device_type] += device.quantity
        
        device_labels = {
            'tv': 'TV / Display',
            'speaker': 'Speakers',
            'subwoofer': 'Subwoofer',
            'keypad': 'Keypads',
            'camera': 'Cameras',
            'wap': 'WiFi AP',
            'touch_panel': 'Touch Panel',
            'video_rx': 'Video Rx',
            'thermostat': 'Thermostat',
        }
        
        for device_type, qty in device_summary.items():
            label = device_labels.get(device_type, device_type.title())
            self._draw_icon_and_text(c, x + 8, line_y, device_type, label, qty, icon_size=11)
            line_y -= line_height
            
            if line_y < y + 10:
                break
    
    def _draw_zone_homerun(self, c, zone_x, zone_y, head_x, head_y, zone: ZoneWiring):
        """Draw homerun line from zone to head-end with cable labels"""
        c.setStrokeColor(colors.HexColor(zone.zone_color))
        c.setLineWidth(1.5)
        c.setDash([4, 2])
        
        # Draw path
        mid_y = (zone_y + head_y) / 2 + 15
        c.line(zone_x, zone_y, zone_x, mid_y)
        c.line(zone_x, mid_y, head_x, mid_y)
        c.line(head_x, mid_y, head_x, head_y)
        
        c.setDash([])
        
        # Cable label
        labels = []
        if zone.cat6_count > 0:
            labels.append(f"CAT6 ({zone.cat6_count})")
        if zone.speaker_wire_count > 0:
            labels.append(f"SPK ({zone.speaker_wire_count})")
        if zone.control_wire_count > 0:
            labels.append(f"CTRL ({zone.control_wire_count})")
        
        if labels:
            label_text = " + ".join(labels)
            label_x = zone_x + 8
            label_y = zone_y + 12
            
            c.setFont("Helvetica-Bold", 7)
            text_width = c.stringWidth(label_text, "Helvetica-Bold", 7)
            
            c.setFillColor(colors.white)
            c.rect(label_x - 2, label_y - 2, text_width + 4, 10, fill=1, stroke=0)
            
            c.setFillColor(colors.HexColor(zone.zone_color))
            c.drawString(label_x, label_y, label_text)
    
    def _draw_header(self, c, zone_mode: bool = False, subtitle: str = None):
        """Draw the title header"""
        # Title
        c.setFont("Helvetica-Bold", 24)
        c.setFillColor(colors.black)
        title = f"{self.project_name} — Rough-In Wiring Plan"
        c.drawCentredString(self.width / 2, self.height - 0.5 * inch, title)
        
        # Subtitle
        c.setFont("Helvetica", 14)
        c.setFillColor(colors.HexColor('#555555'))
        if subtitle:
            sub_text = subtitle
        else:
            sub_text = "Electrician / Low-Voltage Rough-In Reference"
            if zone_mode:
                sub_text += " (Zone View)"
        c.drawCentredString(self.width / 2, self.height - 0.8 * inch, sub_text)
        
        # Divider line
        c.setStrokeColor(colors.HexColor('#CCCCCC'))
        c.setLineWidth(1)
        c.line(self.margin, self.height - self.header_height,
               self.width - self.margin, self.height - self.header_height)
    
    def _draw_headend_box(self, c, x, y):
        """Draw the rack/head-end box (simple version)"""
        # Box
        c.setFillColor(self.color_headend)
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.roundRect(x, y, self.headend_w, self.headend_h, 8, fill=1, stroke=1)
        
        # Label
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(colors.white)
        c.drawCentredString(x + self.headend_w / 2, y + self.headend_h / 2 + 10,
                           "RACK / HEAD-END")
        
        c.setFont("Helvetica", 10)
        c.drawCentredString(x + self.headend_w / 2, y + self.headend_h / 2 - 8,
                           "All Homeruns Terminate Here")
        
        # Down arrow indicator
        arrow_x = x + self.headend_w / 2
        arrow_y = y - 5
        c.setStrokeColor(colors.black)
        c.setLineWidth(1)
        c.line(arrow_x, y, arrow_x, arrow_y)
        c.line(arrow_x - 5, arrow_y + 8, arrow_x, arrow_y)
        c.line(arrow_x + 5, arrow_y + 8, arrow_x, arrow_y)
    
    def _draw_rack_elevation(self, c, x: float, y: float, width: float, height: float) -> Dict[str, Tuple[float, float]]:
        """
        Draw a simplified rack elevation showing equipment categories.
        Returns dict mapping category to connection point (x, y).
        """
        # Rack categories with colors
        rack_sections = [
            {"name": "NETWORK\nSwitches/Router", "color": "#E67E22", "types": ["wap", "thermostat"]},
            {"name": "VIDEO\nMatrix/Receivers", "color": "#3498DB", "types": ["tv", "video_rx"]},
            {"name": "AUDIO\nAmplifiers", "color": "#27AE60", "types": ["speaker", "subwoofer"]},
            {"name": "CONTROL\nProcessor", "color": "#9B59B6", "types": ["keypad", "touch_panel"]},
            {"name": "SECURITY\nNVR/Cameras", "color": "#E74C3C", "types": ["camera"]},
        ]
        
        # Draw rack frame
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.setFillColor(colors.HexColor('#1a1a1a'))
        c.roundRect(x, y, width, height, 4, fill=1, stroke=1)
        
        # Draw rack title
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + width / 2, y + height - 12, "EQUIPMENT RACK")
        
        # Calculate section dimensions
        title_h = 18
        section_h = (height - title_h) / len(rack_sections)
        section_w = width - 10
        section_x = x + 5
        
        connection_points = {}
        
        for idx, section in enumerate(rack_sections):
            section_y = y + height - title_h - (idx + 1) * section_h
            
            # Section background
            c.setFillColor(colors.HexColor(section["color"]))
            c.roundRect(section_x, section_y, section_w, section_h - 3, 3, fill=1, stroke=0)
            
            # Section label
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 7)
            lines = section["name"].split("\n")
            for i, line in enumerate(lines):
                c.drawCentredString(section_x + section_w / 2, 
                                   section_y + section_h / 2 - 4 + (len(lines) - 1 - i) * 8, 
                                   line)
            
            # Store connection point (left side of section)
            conn_y = section_y + section_h / 2
            for device_type in section["types"]:
                connection_points[device_type] = (x, conn_y)
            
            # Also store by section name for zone mode
            section_key = section["name"].split("\n")[0].lower()
            connection_points[section_key] = (x, conn_y)
        
        return connection_points
    
    def generate_with_rack(self, rooms: Dict[str, RoomWiring], output_path: str):
        """Generate rough-in plan with integrated rack elevation"""
        
        c = canvas.Canvas(output_path, pagesize=self.page_size)
        
        # Draw header
        self._draw_header(c)
        
        # Calculate usable area
        usable_y_top = self.height - self.header_height - self.margin
        usable_y_bottom = self.footer_height + 1.6 * inch
        
        # Rack elevation dimensions (centered at top)
        rack_w = 1.8 * inch
        rack_h = 2.2 * inch
        rack_x = (self.width - rack_w) / 2
        rack_y = usable_y_top - rack_h - 0.1 * inch
        
        # Draw rack elevation and get connection points
        connection_points = self._draw_rack_elevation(c, rack_x, rack_y, rack_w, rack_h)
        
        # Calculate grid for rooms
        room_list = list(rooms.items())
        num_rooms = len(room_list)
        
        if num_rooms == 0:
            c.setFont("Helvetica", 14)
            c.drawCentredString(self.width / 2, self.height / 2,
                               "No rough-in devices found in CSV")
        else:
            # Grid layout
            cols = min(5, num_rooms)
            rows = (num_rooms + cols - 1) // cols
            
            homerun_gap = 0.6 * inch
            room_area_top = rack_y - homerun_gap
            
            total_room_width = cols * self.room_box_w + (cols - 1) * self.room_gap_x
            start_x = (self.width - total_room_width) / 2
            
            row_height = self.room_box_h + self.room_gap_y
            start_y = room_area_top - self.room_box_h
            
            # Draw homerun lines first (to appropriate rack sections)
            for idx, (room_key, room) in enumerate(room_list):
                col = idx % cols
                row = idx // cols
                
                room_x = start_x + col * (self.room_box_w + self.room_gap_x)
                room_y = start_y - row * row_height
                
                self._draw_rack_homerun(c, room_x + self.room_box_w / 2,
                                       room_y + self.room_box_h,
                                       rack_x, rack_y, rack_w, rack_h,
                                       room, connection_points)
            
            # Draw room boxes
            for idx, (room_key, room) in enumerate(room_list):
                col = idx % cols
                row = idx // cols
                
                room_x = start_x + col * (self.room_box_w + self.room_gap_x)
                room_y = start_y - row * row_height
                
                self._draw_room_box(c, room_x, room_y, room_key, room)
        
        # Draw legend
        self._draw_legend(c)
        
        # Draw footer
        self._draw_footer(c)
        
        c.save()
        print(f"✅ Generated (with Rack): {output_path}")
        return output_path
    
    def _draw_rack_homerun(self, c, room_x: float, room_y: float, 
                          rack_x: float, rack_y: float, rack_w: float, rack_h: float,
                          room: RoomWiring, connection_points: Dict):
        """Draw homerun lines from room to specific rack equipment"""
        
        # Determine which rack sections this room connects to
        device_types = set()
        for device in room.devices:
            device_types.add(device.device_type)
        
        # Map device types to connection categories
        connections = []
        
        if any(t in device_types for t in ['wap', 'thermostat']):
            if 'wap' in connection_points:
                connections.append(('network', connection_points['wap'], self.color_cat6, room.cat6_count))
        
        if any(t in device_types for t in ['tv', 'video_rx']):
            if 'tv' in connection_points:
                cat6_for_video = sum(WIRING_RULES.get(f'{t}_cat6', 0) * 
                                    sum(d.quantity for d in room.devices if d.device_type == t)
                                    for t in ['tv', 'video_rx'] if t in device_types)
                connections.append(('video', connection_points['tv'], self.color_cat6, cat6_for_video))
        
        if any(t in device_types for t in ['speaker', 'subwoofer']):
            if 'speaker' in connection_points:
                connections.append(('audio', connection_points['speaker'], self.color_speaker, room.speaker_wire_count))
        
        if any(t in device_types for t in ['keypad', 'touch_panel']):
            if 'keypad' in connection_points:
                ctrl_count = sum(d.quantity for d in room.devices if d.device_type in ['keypad', 'touch_panel'])
                connections.append(('control', connection_points['keypad'], self.color_control, ctrl_count))
        
        if 'camera' in device_types:
            if 'camera' in connection_points:
                cam_count = sum(d.quantity for d in room.devices if d.device_type == 'camera')
                connections.append(('security', connection_points['camera'], self.color_hdmi, cam_count))
        
        # Draw connection lines
        for idx, (conn_type, (target_x, target_y), color, count) in enumerate(connections):
            if count <= 0:
                continue
                
            c.setStrokeColor(color)
            c.setLineWidth(1.2)
            c.setDash([3, 2])
            
            # Offset for multiple lines from same room
            offset = (idx - len(connections) / 2) * 8
            
            # Route: room -> up -> horizontal -> to rack section
            mid_y = (room_y + target_y) / 2 + offset
            
            c.line(room_x + offset, room_y, room_x + offset, mid_y)
            c.line(room_x + offset, mid_y, target_x, mid_y)
            c.line(target_x, mid_y, target_x, target_y)
            
            c.setDash([])
            
            # Small label near room
            if count > 0:
                c.setFont("Helvetica", 6)
                label = f"{count}"
                c.setFillColor(colors.white)
                c.circle(room_x + offset, room_y + 8, 6, fill=1, stroke=0)
                c.setFillColor(color)
                c.drawCentredString(room_x + offset, room_y + 6, label)
    
    def generate_dual_rack(self, rooms: Dict[str, RoomWiring], csv_path: str, output_path: str, rack_size_override: int = None):
        """
        Generate rough-in plan with ACTUAL detailed rack elevations.
        Uses the SYSTEM column from CSV to determine connections.
        Creates a TREE-BRANCH layout: Rack = trunk, Rooms = branches.
        
        Args:
            rack_size_override: Optional manual rack size (in U). If None, detected from CSV.
        """
        if not HAS_RACK_MODULES:
            print("❌ Rack modules not available. Using simple rack view instead.")
            return self.generate_with_rack(rooms, output_path)
        
        from generate_rack_docs import split_into_av_and_network_racks
        
        # Parse CSV to get systems by room AND device details
        systems_by_room = self._parse_csv_for_systems(csv_path)
        devices_by_room = self._parse_csv_for_devices(csv_path)
        
        c = canvas.Canvas(output_path, pagesize=self.page_size)
        
        # Parse CSV and get rack equipment
        products = parse_client_csv(csv_path)
        products = get_unique_products_with_quantities(products)
        
        # ENRICH PRODUCTS with specs - D-Tools catalog first, then OpenAI/MySQL fallback
        rack_items = []
        dtools_found = 0
        
        if HAS_DTOOLS_CATALOG:
            print("📚 Looking up equipment specs in D-Tools catalog...")
            for p in products:
                # Skip excluded items (same rules as rack elevation)
                if is_rack_excluded(p.model, getattr(p, 'part_number', ''), p.name):
                    continue
                
                # Try D-Tools catalog lookup by model or part number
                specs = get_rack_specs(model=p.model, part_number=p.model)
                
                if specs and specs.get('rack_units', 0) > 0:
                    dtools_found += 1
                    # Apply display name override
                    display_model = get_display_name(p.model)
                    
                    item = RackItem(
                        name=p.name or specs.get('description', display_model),
                        brand=specs.get('brand', p.brand or ''),
                        model=display_model,
                        rack_units=specs['rack_units'],
                        weight=specs.get('weight', 5.0) or 5.0,
                        btu=specs.get('btu', 0) or 0,
                        item_type=RackItemType.EQUIPMENT,
                        quantity=p.quantity
                    )
                    rack_items.append(item)
            print(f"✅ Found {dtools_found} items with D-Tools specs")
        
        # If D-Tools didn't find enough, try OpenAI/MySQL enrichment
        if len(rack_items) < 5 and HAS_ENRICHMENT:
            print("📡 Looking up additional equipment specs (OpenAI/MySQL)...")
            try:
                enriched_items = enrich_products_with_specs(products, use_database=True, use_ai=True)
                # Only add items we don't already have from D-Tools
                existing_models = {item.model.lower() for item in rack_items}
                for item in enriched_items:
                    # Skip excluded items
                    if is_rack_excluded(item.model, '', item.name):
                        continue
                    if item.model.lower() not in existing_models:
                        # Apply display name override
                        item.model = get_display_name(item.model)
                        rack_items.append(item)
                print(f"✅ Total: {len(rack_items)} rack-mountable items with specs")
            except Exception as e:
                print(f"⚠️ Enrichment failed: {e}. Using D-Tools results only.")
        
        # Fallback if nothing worked
        if not rack_items:
            print("⚠️ No specs found. Using defaults from CSV.")
            for p in products:
                if p.rack_units is None or p.rack_units <= 0:
                    continue
                item = RackItem(
                    name=p.name or p.model,
                    brand=p.brand or "",
                    model=p.model or p.name,
                    rack_units=p.rack_units,
                    weight=p.weight or 5.0,
                    btu=p.btu or 0,
                    item_type=RackItemType.EQUIPMENT,
                    quantity=p.quantity
                )
                rack_items.append(item)
        
        # Detect rack size from CSV (like generate_rack_docs.py does) or use override
        if rack_size_override:
            detected_rack_size = rack_size_override
            print(f"🗄️  Using override rack size: {detected_rack_size}U")
        else:
            try:
                from csv_parser import get_rack_info_from_csv
                rack_info = get_rack_info_from_csv(csv_path)
                if rack_info and isinstance(rack_info, dict):
                    # Use av_rack_size or default_size from the dictionary
                    detected_rack_size = rack_info.get('av_rack_size') or rack_info.get('default_size') or 42
                elif rack_info:
                    detected_rack_size = 42
                else:
                    detected_rack_size = 42
                print(f"🗄️  Detected rack size: {detected_rack_size}U")
            except Exception as e:
                print(f"⚠️  Could not detect rack size: {e}, using 42U")
                detected_rack_size = 42
        
        # Calculate total RU needed
        total_ru = sum(item.rack_units * item.quantity for item in rack_items)
        print(f"📦 Total equipment: {len(rack_items)} items, {total_ru}U")
        
        # Create single combined rack layout using DETECTED rack size
        combined_layout = arrange_rack(rack_items, rack_size_u=detected_rack_size) if rack_items else None
        
        # All systems go to the single rack
        all_systems = {'Video', 'Audio', 'Lighting Control', 'Automation & Control', 'HVAC', 
                       'Power Quality', 'Equipment Racks & Power Quality', 'Network & WiFi', 'CCTV'}
        
        # ========== SINGLE PAGE: COMBINED RACK ==========
        if combined_layout:
            self._draw_tree_branch_page(c, combined_layout, systems_by_room, devices_by_room,
                                        f"EQUIPMENT RACK ({detected_rack_size}U)", all_systems, is_av=True)
        
        c.save()
        print(f"✅ Generated (Single Rack - Combined): {output_path}")
        return output_path
    
    def _parse_csv_for_systems(self, csv_path: str) -> Dict[str, Dict[str, int]]:
        """
        Parse CSV and return systems by room.
        Counts actual devices (BRKT: entries) and power equipment.
        Returns: {room_name: {system_name: device_count}}
        """
        import csv
        
        systems_by_room = defaultdict(lambda: defaultdict(int))
        
        # Power equipment part numbers to include
        power_keywords = ['WB-', 'WATTBOX', 'UPS', 'IP SMART POWER', 'SA-20', 
                          'POWER CONDITIONER', 'SURGE', 'PDU']
        
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Support both LocationPath (SI-AVC format) and Location (standard format)
                        location = row.get('LocationPath', '').strip() or row.get('Location', '').strip()
                        system = row.get('System', '').strip() or row.get('Category', '').strip()
                        part_num = row.get('Part Number', row.get('Model', '')).strip().upper()
                        name = row.get('Name', '').strip()
                        qty = int(float(row.get('Quantity', 1) or 1))
                        
                        if not location:
                            continue
                        
                        # Count if:
                        # 1. Has BRKT: prefix (device brackets)
                        # 2. Is Power Quality/Equipment Racks system with power equipment
                        # 3. Is an actual speaker/device (for non-BRKT format CSVs)
                        is_device = part_num.startswith('BRKT:')
                        is_power = ('POWER' in system.upper() or 'EQUIPMENT RACKS' in system.upper()) and \
                                   any(kw in part_num for kw in power_keywords)
                        
                        # For non-BRKT CSVs, identify devices by category/name
                        is_speaker = any(x in name.lower() or x in system.lower() for x in ['speaker', 'ccm', 'cwm', 'isw', 'am-1', 'james', 'bowers', 'sonance'])
                        is_av_device = 'av system' in system.lower() or 'audio' in system.lower() or 'video' in system.lower()
                        is_lighting = 'lighting' in system.lower() or 'lutron' in name.lower()
                        is_climate = 'climate' in system.lower() or 'hvac' in system.lower() or 'thermostat' in name.lower()
                        is_network = 'network' in system.lower() or 'ruckus' in name.lower() or 'access networks' in name.lower()
                        is_security = 'security' in system.lower() or 'camera' in name.lower() or 'ring' in name.lower()
                        
                        if not is_device and not is_power and not is_speaker and not is_av_device and not is_lighting and not is_climate and not is_network and not is_security:
                            continue
                        
                        # Skip placeholder entries
                        if part_num.startswith('~'):
                            continue
                        
                        # Skip cables and wiring
                        if any(x in name.lower() for x in ['cable', 'wire', 'ice cable', 'prewire']):
                            continue
                        
                        # Extract room name (after the colon if present)
                        if ': ' in location:
                            room = location.split(': ', 1)[1]
                        else:
                            room = location
                        
                        # Map to system category
                        if is_speaker or is_av_device:
                            mapped_system = 'Audio' if is_speaker else 'Video'
                        elif is_lighting:
                            mapped_system = 'Lighting Control'
                        elif is_climate:
                            mapped_system = 'HVAC'
                        elif is_network:
                            mapped_system = 'Network & WiFi'
                        elif is_security:
                            mapped_system = 'CCTV'
                        else:
                            mapped_system = system
                        
                        systems_by_room[room][mapped_system] += qty
                break
            except UnicodeDecodeError:
                continue
        
        return systems_by_room
    
    def _parse_csv_for_devices(self, csv_path: str) -> Dict[str, Dict[str, int]]:
        """
        Parse CSV and return SPECIFIC DEVICE TYPES by room.
        Returns: {room_name: {device_type: count}}
        
        Device types: tv, speaker, subwoofer, lcr_bar, keypad, wap, camera, thermostat,
                      bijou (room amplifiers), local_switch (PoE switches in rooms), etc.
        """
        import csv
        import re
        
        devices_by_room = defaultdict(lambda: defaultdict(int))
        
        # Map BRKT: part numbers to device types
        brkt_to_device = {
            'BRKT:VID TV': 'tv',
            'BRKT:SPK ROUND': 'speaker',
            'BRKT:SPK LCR BAR': 'lcr_bar',
            'BRKT:SUB': 'subwoofer',
            'BRKT:CTRL KEYPAD': 'keypad',
            'BRKT:CTRL WIRELESS': 'keypad_wireless',
            'BRKT:NETWORK WIRELESS': 'wap',
            'BRKT:HVAC REMOTE SENSOR': 'thermostat',
            'BRKT:CCTV CAMERA': 'camera',
            'BRKT:AXS INTERCOM': 'intercom',
        }
        
        # Map actual EQUIPMENT models to device types (for distributed equipment)
        # These are items that go IN ROOMS, not in the main rack
        equipment_to_device = {
            # Bijou amplifiers - go in rooms for local audio
            'bijou': 'bijou',
            'pav-bijou': 'bijou',
            
            # Local PoE switches - distributed in rooms
            'usw-pro-xg-8-poe': 'local_switch',
            
            # Climate sensors - in rooms
            'cli-thfm': 'climate_sensor',
            'thfm': 'climate_sensor',
            
            # HVAC controller - at HVAC unit location
            'cli-8000': 'hvac_controller',
            
            # WiFi Access Points - these need to be distributed
            'e7': 'wap',
            'e7 campus': 'wap_outdoor',
        }
        
        # Collect WiFi APs that are listed under "Systems" to redistribute
        # Only count actual E7/E7 CAMPUS devices, not "NETWORK WAP" placeholders
        wifi_aps_to_distribute = {'indoor': 0, 'outdoor': 0}
        
        def normalize(s):
            """Remove non-ASCII and normalize"""
            if not s:
                return ''
            return re.sub(r'[^\x00-\x7F]+', '', s).lower().strip()
        
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        
        # First pass: collect all devices and count WiFi APs under "Systems"
        all_real_rooms = set()  # Track actual rooms (not "Systems:")
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Support both LocationPath (SI-AVC format) and Location (standard format)
                        location = row.get('LocationPath', '').strip() or row.get('Location', '').strip()
                        part_num = row.get('Part Number', row.get('Model', '')).strip()
                        name = row.get('Name', '').strip()
                        category = row.get('Category', '').strip()
                        part_num_upper = part_num.upper()
                        part_num_lower = normalize(part_num)
                        name_lower = normalize(name)
                        qty = int(float(row.get('Quantity', 1) or 1))
                        
                        if not location:
                            continue
                        
                        # Extract room name
                        if ': ' in location:
                            room = location.split(': ', 1)[1]
                        else:
                            room = location
                        
                        room_lower = room.lower()
                        
                        # Track real rooms (not Systems or Equipment)
                        if not room_lower.startswith('network') and not room_lower.startswith('lighting') and \
                           not room_lower.startswith('hvac') and not room_lower.startswith('cctv') and \
                           'equipment' not in room_lower:
                            all_real_rooms.add(room)
                        
                        # Check for WiFi APs under "Systems" - collect for redistribution
                        if 'systems' in location.lower() or 'network' in room_lower:
                            if 'e7 campus' in part_num_lower:
                                wifi_aps_to_distribute['outdoor'] += qty
                                continue
                            elif 'e7' in part_num_lower and 'campus' not in part_num_lower:
                                wifi_aps_to_distribute['indoor'] += qty
                                continue
                        
                        # Skip "Equipment" locations - those go in rack
                        if any(kw in room_lower for kw in ['equipment closet', 'equipment room', 'mdf', 'idf']):
                            continue
                        
                        # 1. Check BRKT: entries (bracket/placeholder devices)
                        if part_num_upper.startswith('BRKT:'):
                            device_type = brkt_to_device.get(part_num_upper, None)
                            if device_type:
                                devices_by_room[room][device_type] += qty
                            continue
                        
                        # 2. Check for ACTUAL EQUIPMENT in rooms (Bijou, PoE switches, etc.)
                        # Use Part Number since this CSV format doesn't have a Model column
                        matched = False
                        for pattern, device_type in equipment_to_device.items():
                            if pattern in part_num_lower:
                                # Skip WiFi APs here - we'll distribute them separately
                                if device_type in ['wap', 'wap_outdoor']:
                                    continue
                                devices_by_room[room][device_type] += qty
                                matched = True
                                break
                        
                        if matched:
                            continue
                        
                        # 3. Fallback: Identify devices by name/category (for non-BRKT CSVs)
                        # Skip cables, wires, and accessories
                        if any(x in name_lower for x in ['cable', 'wire', 'prewire', 'pre-wire', 'box', 'carlon', 'keystone']):
                            continue
                        
                        # Check category for speaker types
                        category_lower = category.lower() if category else ''
                        
                        # Speakers by category (most reliable)
                        if 'speaker' in category_lower or 'lcr' in category_lower:
                            if 'sub' in name_lower or 'sub' in category_lower:
                                devices_by_room[room]['subwoofer'] += qty
                            else:
                                devices_by_room[room]['speaker'] += qty
                            continue
                        
                        # Speakers by brand/model (B&W, James, Sonance, Triad, Episode, etc.)
                        speaker_brands = ['ccm', 'cwm', 'isw4', 'am-1', 'james loudspeaker', 'sonance', 
                                         'origin', 'triad', 'kef', 'episode', 'vp64', 'vpxt', '44406', '44408']
                        if any(x in name_lower or x in part_num_lower for x in speaker_brands):
                            # Subwoofers
                            if 'isw' in name_lower or 'sub' in name_lower or 'sub' in category_lower:
                                devices_by_room[room]['subwoofer'] += qty
                            else:
                                devices_by_room[room]['speaker'] += qty
                            continue
                        
                        # Bowers & Wilkins speakers specifically
                        if 'bowers' in name_lower or 'b & w' in name_lower or 'b&w' in name_lower:
                            if 'isw' in name_lower:
                                devices_by_room[room]['subwoofer'] += qty
                            else:
                                devices_by_room[room]['speaker'] += qty
                            continue
                        
                        # Keypads and dimmers (Lutron)
                        if any(x in name_lower for x in ['keypad', 'dimmer', 'switch', 'pico', 'seetouch']) and 'lutron' in name_lower:
                            devices_by_room[room]['keypad'] += qty
                            continue
                        
                        # Thermostats and climate sensors
                        if any(x in name_lower for x in ['thermostat', 'sensor', 'sst-temp', 'climate']):
                            devices_by_room[room]['thermostat'] += qty
                            continue
                        
                        # Ring doorbells/cameras
                        if 'ring' in name_lower and any(x in name_lower for x in ['doorbell', 'camera', '8ssxe']):
                            devices_by_room[room]['camera'] += qty
                            continue
                        
                        # WiFi APs (Ruckus, Access Networks)
                        if any(x in name_lower for x in ['ruckus', 'access networks', '901-r', '9u1-t']):
                            devices_by_room[room]['wap'] += qty
                            continue
                        
                break
            except UnicodeDecodeError:
                continue
        
        # Distribute WiFi APs based on COVERAGE ZONES, not individual rooms
        # Ubiquiti E7: ~2,500-3,000 sq ft indoor coverage
        # E7 Campus: Extended outdoor coverage
        # Best practice: Central locations covering multiple rooms
        
        indoor_count = wifi_aps_to_distribute['indoor']
        outdoor_count = wifi_aps_to_distribute['outdoor']
        
        if indoor_count > 0 or outdoor_count > 0:
            # COVERAGE ZONE placement strategy (not per-room)
            # Each zone covers multiple adjacent rooms
            
            # Indoor coverage zones - strategic central locations
            # Format: (zone_name, rooms_it_covers, ap_location_description)
            # Ubiquiti E7 covers ~2,500-3,000 sq ft - place in central locations
            indoor_zones = [
                # 1st Floor zones (3 APs for main living areas)
                ('1st Floor - Kitchen/Dining', ['kitchen'], 'Central - covers Kitchen, Dining'),
                ('1st Floor - Great Room', ['great room'], 'Central - covers Great Room, Entry'),
                ('1st Floor - Den/Office', ['den'], 'Hallway - covers Den, Office'),
                # 2nd Floor zones (3 APs)
                ('2nd Floor - Primary Wing', ['primary suite'], 'Hallway - covers Primary Suite, Bath, Sunroom'),
                ('2nd Floor - Secondary Wing', ['junior suite'], 'Hallway - covers Junior Suite'),
                ('2nd Floor - Balcony/Hall', ['balcony'], '2nd Floor - covers Balcony, central hall'),
                # Lower Level (1 AP)
                ('Lower Level', ['gym'], 'Lower Level - covers Gym area'),
            ]
            
            # Outdoor zones (E7 Campus)
            outdoor_zones = [
                ('Exterior - Front', ['exterior'], 'Front exterior/driveway'),
                ('Exterior - Pool', ['pool house'], 'Pool house/backyard'),
            ]
            
            # Create WiFi coverage entries (these are ZONES, not rooms)
            # But we need to attach them to a representative room for the diagram
            assigned_indoor = 0
            assigned_rooms = set()
            
            for zone_name, covered_rooms, location_desc in indoor_zones:
                if assigned_indoor >= indoor_count:
                    break
                
                # Find the best representative room for this zone
                representative_room = None
                for covered in covered_rooms:
                    for real_room in all_real_rooms:
                        if covered in real_room.lower() and real_room not in assigned_rooms:
                            representative_room = real_room
                            break
                    if representative_room:
                        break
                
                if representative_room:
                    # Mark this room as having WiFi coverage (the AP covers this zone)
                    devices_by_room[representative_room]['wap'] = 1
                    assigned_indoor += 1
                    assigned_rooms.add(representative_room)
            
            # Distribute outdoor APs to coverage zones
            assigned_outdoor = 0
            for zone_name, covered_rooms, location_desc in outdoor_zones:
                if assigned_outdoor >= outdoor_count:
                    break
                
                representative_room = None
                for covered in covered_rooms:
                    for real_room in all_real_rooms:
                        if covered in real_room.lower() and real_room not in assigned_rooms:
                            representative_room = real_room
                            break
                    if representative_room:
                        break
                
                if representative_room:
                    devices_by_room[representative_room]['wap_outdoor'] = 1
                    assigned_outdoor += 1
                    assigned_rooms.add(representative_room)
        
        # Remove the "Network & WiFi" system entry since we've distributed APs
        if 'Network & WiFi' in devices_by_room:
            del devices_by_room['Network & WiFi']
        
        return devices_by_room
    
    def _draw_tree_branch_page(self, c, layout: 'RackLayout', 
                                systems_by_room: Dict[str, Dict[str, int]],
                                devices_by_room: Dict[str, Dict[str, int]],
                                rack_title: str, relevant_systems: set, is_av: bool):
        """
        Draw a CENTER RACK layout:
        - Rack in the CENTER (the trunk)
        - Rooms on LEFT and RIGHT sides (branches)
        - Clear, non-overlapping connection lines
        """
        
        # Draw header
        subtitle = "Audio / Video / Control" if is_av else "Network / WiFi / Security"
        self._draw_header(c, subtitle=f"{subtitle} — Wiring Diagram")
        
        # Layout dimensions
        usable_y_top = self.height - self.header_height - 0.15 * inch
        usable_y_bottom = self.footer_height + 0.3 * inch
        usable_height = usable_y_top - usable_y_bottom
        
        # RACK IN CENTER - narrower to give more cable space
        rack_w = 1.5 * inch
        rack_h = usable_height - 0.2 * inch
        rack_x = (self.width - rack_w) / 2
        rack_y = usable_y_bottom + 0.1 * inch
        
        # Draw the rack and get equipment connection points by system
        system_connection_points = self._draw_rack_with_system_labels(
            c, rack_x, rack_y, rack_w, rack_h, layout, rack_title, is_av)
        
        # Filter rooms that have relevant systems
        # Add Network & WiFi system to rooms that have distributed WiFi APs
        relevant_rooms = []
        
        # Get rooms with WiFi APs from devices_by_room
        rooms_with_wifi = set()
        for room_name, devices in devices_by_room.items():
            if devices.get('wap', 0) > 0 or devices.get('wap_outdoor', 0) > 0:
                rooms_with_wifi.add(room_name)
        
        for room_name, systems in systems_by_room.items():
            # Skip the "Network & WiFi" system grouping - APs are distributed to rooms
            if room_name.lower() == 'network & wifi':
                continue
            
            room_systems = {s: cnt for s, cnt in systems.items() if s in relevant_systems}
            
            # Add Network & WiFi system for rooms that have WiFi APs
            for wifi_room in rooms_with_wifi:
                if wifi_room.lower() in room_name.lower() or room_name.lower() in wifi_room.lower():
                    # Add 1 CAT6 for the WiFi AP
                    wifi_count = devices_by_room[wifi_room].get('wap', 0) + devices_by_room[wifi_room].get('wap_outdoor', 0)
                    if wifi_count > 0:
                        room_systems['Network & WiFi'] = wifi_count
                    break
            
            if room_systems:
                relevant_rooms.append((room_name, room_systems))
        
        if not relevant_rooms:
            c.setFont("Helvetica", 12)
            c.setFillColor(colors.gray)
            c.drawString(rack_x + rack_w + 0.5 * inch, rack_y + rack_h / 2, 
                        "No devices for this rack type")
            self._draw_footer(c)
            return
        
        # Split rooms into LEFT and RIGHT sides
        num_rooms = len(relevant_rooms)
        left_rooms = relevant_rooms[:num_rooms // 2 + num_rooms % 2]
        right_rooms = relevant_rooms[num_rooms // 2 + num_rooms % 2:]
        
        # Calculate room dimensions to FIT on page
        max_rooms_per_side = max(len(left_rooms), len(right_rooms))
        
        # Calculate room height to fit all rooms - MUCH LARGER for readability
        available_height = usable_height - 0.2 * inch
        room_h = min(2.0 * inch, (available_height - 0.05 * inch * max_rooms_per_side) / max_rooms_per_side)
        room_h = max(1.4 * inch, room_h)  # Minimum height further increased
        
        room_w = 2.4 * inch  # Slightly narrower to give cable space
        gap_y = 0.1 * inch
        
        # LEFT SIDE rooms - positioned at left margin
        left_area_x = self.margin * 0.5  # Pull back further left
        for idx, (room_name, room_systems) in enumerate(left_rooms):
            room_x = left_area_x
            room_y = usable_y_top - (idx + 1) * (room_h + gap_y)
            
            # Skip if would go off page
            if room_y < usable_y_bottom:
                continue
            
            room_devices = devices_by_room.get(room_name, {})
            
            # Draw connection - line goes RIGHT to rack
            self._draw_simple_connection(c, room_x + room_w, room_y + room_h / 2,
                                         rack_x, room_systems, system_connection_points,
                                         idx, is_left=True)
            
            self._draw_room_systems_box(c, room_x, room_y, room_w, room_h,
                                        room_name, room_systems, room_devices)
        
        # RIGHT SIDE rooms - MAXIMUM space for cable routing
        right_area_x = rack_x + rack_w + 0.8 * inch  # More gap from rack
        for idx, (room_name, room_systems) in enumerate(right_rooms):
            room_x = right_area_x + 1.8 * inch  # MAXIMUM space for connection lines
            room_y = usable_y_top - (idx + 1) * (room_h + gap_y)
            
            # Skip if would go off page
            if room_y < usable_y_bottom:
                continue
            
            room_devices = devices_by_room.get(room_name, {})
            
            # Draw connection - line goes LEFT to rack
            self._draw_simple_connection(c, room_x, room_y + room_h / 2,
                                         rack_x + rack_w, room_systems, system_connection_points,
                                         idx, is_left=False)
            
            self._draw_room_systems_box(c, room_x, room_y, room_w, room_h,
                                        room_name, room_systems, room_devices)
        
        # Draw legend at bottom
        self._draw_system_legend(c, is_av)
        
        # Draw footer
        self._draw_footer(c)
    
    def _draw_simple_connection(self, c, room_edge_x: float, room_y: float,
                                 rack_edge_x: float, room_systems: Dict[str, int],
                                 system_connection_points: Dict[str, Tuple[float, float]],
                                 room_idx: int, is_left: bool):
        """Draw simple, clear connection lines from room to rack"""
        
        system_colors = {
            'Video': colors.HexColor('#3498DB'),
            'Audio': colors.HexColor('#27AE60'),
            'Lighting Control': colors.HexColor('#F1C40F'),
            'Automation & Control': colors.HexColor('#9B59B6'),
            'HVAC': colors.HexColor('#1ABC9C'),
            'Network & WiFi': colors.HexColor('#E67E22'),
            'CCTV': colors.HexColor('#E74C3C'),
            'Power Quality': colors.HexColor('#C0392B'),
            'Equipment Racks & Power Quality': colors.HexColor('#C0392B'),
        }
        
        system_cable_labels = {
            'Video': 'CAT6', 'Audio': 'SPK', 'Lighting Control': 'CTRL',
            'Automation & Control': 'CAT6', 'HVAC': 'CAT6',
            'Network & WiFi': 'CAT6', 'CCTV': 'CAT6',
            'Power Quality': 'PWR', 'Equipment Racks & Power Quality': 'PWR',
        }
        
        num_systems = len(room_systems)
        
        # Sort systems to draw in consistent order (prevents random overlap)
        system_order = ['Audio', 'Video', 'Lighting Control', 'Network & WiFi', 'CCTV', 'HVAC', 'Automation & Control', 'Power Quality']
        sorted_systems = sorted(room_systems.items(), key=lambda x: system_order.index(x[0]) if x[0] in system_order else 99)
        
        for idx, (system, count) in enumerate(sorted_systems):
            if system not in system_connection_points:
                continue
            
            color = system_colors.get(system, colors.gray)
            cable_label = system_cable_labels.get(system, 'WIRE')
            
            # For Network & WiFi, alternate between the two PoE switches
            if system == 'Network & WiFi' and 'Network & WiFi 2' in system_connection_points:
                # Alternate based on room index - distribute load between switches
                if room_idx % 2 == 0:
                    target_x, target_y = system_connection_points[system]
                else:
                    target_x, target_y = system_connection_points['Network & WiFi 2']
            else:
                target_x, target_y = system_connection_points[system]
            
            # IMPROVED: Each system gets its own dedicated vertical channel
            # Stagger lines vertically from room center
            base_offset = (idx - num_systems / 2) * 25  # Tighter at room
            line_y = room_y + base_offset
            
            c.setStrokeColor(color)
            c.setLineWidth(2.0)
            c.setDash([])
            
            if is_left:
                # Room on LEFT - line goes right to rack
                # Each SYSTEM TYPE gets its own vertical channel
                system_channel = system_order.index(system) if system in system_order else idx
                mid_x = rack_edge_x - 0.3 * inch - (system_channel * 18) - (room_idx * 5)
                
                c.line(room_edge_x, line_y, mid_x, line_y)
                c.line(mid_x, line_y, mid_x, target_y)
                c.line(mid_x, target_y, rack_edge_x, target_y)
            else:
                # Room on RIGHT - line goes left to rack
                # Moved another 0.25" closer to rack (now very close)
                system_channel = system_order.index(system) if system in system_order else idx
                mid_x = rack_edge_x + 0.05 * inch + (system_channel * 16) + (room_idx * 5)
                
                c.line(room_edge_x, line_y, mid_x, line_y)
                c.line(mid_x, line_y, mid_x, target_y)
                c.line(mid_x, target_y, rack_edge_x, target_y)
            
            # Label in the middle of horizontal segment
            label_x = (room_edge_x + mid_x) / 2
            label_y = line_y
            
            label_text = f"{cable_label} ({count})"
            text_width = len(label_text) * 6 + 8
            
            c.setFillColor(colors.white)
            c.setStrokeColor(color)
            c.setLineWidth(1.5)
            c.roundRect(label_x - text_width/2, label_y - 8, text_width, 16, 4, fill=1, stroke=1)
            
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(label_x, label_y - 4, label_text)
    
    def _draw_rack_with_system_labels(self, c, x: float, y: float, width: float, height: float,
                                       layout, title: str, is_av: bool) -> Dict[str, Tuple[float, float]]:
        """Draw rack with ACTUAL EQUIPMENT from layout, return connection points by SYSTEM type"""
        
        # Check if we have actual equipment
        has_real_equipment = False
        if layout and layout.items:
            # Check if we have any actual equipment items (not just vents)
            for item in layout.items:
                if item.item_type == RackItemType.EQUIPMENT:
                    has_real_equipment = True
                    break
        
        # If we have real equipment, draw the actual rack elevation
        if has_real_equipment and layout:
            return self._draw_actual_rack(c, x, y, width, height, layout, title, is_av)
        else:
            # Fall back to simplified sections
            return self._draw_simplified_rack(c, x, y, width, height, title, is_av)
    
    def _draw_actual_rack(self, c, x: float, y: float, width: float, height: float,
                          layout, title: str, is_av: bool = True) -> Dict[str, Tuple[float, float]]:
        """Draw the ACTUAL rack with real equipment positions"""
        
        rack_size_u = layout.rack_size_u
        u_height = height / rack_size_u
        
        # Rack frame
        c.setFillColor(colors.HexColor('#1a1a1a'))
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.rect(x, y, width, height, fill=1, stroke=1)
        
        # Title
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(x + width / 2, y + height + 8, title)
        
        # U numbers on left
        c.setFont("Helvetica", 5)
        c.setFillColor(colors.gray)
        for u in range(1, rack_size_u + 1, 4):
            u_y = y + (u - 1) * u_height + u_height / 2
            c.drawRightString(x - 3, u_y - 2, f"{u}U")
        
        # Rails
        rail_w = 4
        c.setFillColor(colors.HexColor('#333333'))
        c.rect(x + 2, y, rail_w, height, fill=1, stroke=0)
        c.rect(x + width - rail_w - 2, y, rail_w, height, fill=1, stroke=0)
        
        # System colors
        system_colors = {
            'Video': colors.HexColor('#3498DB'),
            'Audio': colors.HexColor('#27AE60'),
            'Lighting Control': colors.HexColor('#F1C40F'),
            'Automation & Control': colors.HexColor('#9B59B6'),
            'HVAC': colors.HexColor('#1ABC9C'),
            'Network & WiFi': colors.HexColor('#E67E22'),
            'CCTV': colors.HexColor('#E74C3C'),
            'Power Quality': colors.HexColor('#C0392B'),
        }
        
        system_connection_points = {}
        
        for item in layout.items:
            item_y = y + (item.position_u - 1) * u_height
            item_h = item.rack_units * u_height
            
            name_lower = f"{item.brand} {item.model} {item.name}".lower()
            
            if item.item_type == RackItemType.EQUIPMENT:
                # Determine which system this equipment serves
                if any(kw in name_lower for kw in ['video', 'matrix', 'ps65', 'ps80', 'svr', 'ub32', 'hdmi']):
                    system = 'Video'
                elif any(kw in name_lower for kw in ['amp', 'sonance', 'crown', 'audio', 'dsp', 'sipa', 'aom']):
                    system = 'Audio'
                elif any(kw in name_lower for kw in ['lutron', 'hqp', 'hqr', 'lighting', 'dimmer']):
                    system = 'Lighting Control'
                elif any(kw in name_lower for kw in ['wattbox', 'wb-', 'ups', 'power', 'pdu', 'surge']):
                    system = 'Power Quality'
                elif any(kw in name_lower for kw in ['savant', 'control', 'ssc', 'pkg-', 'automation', 'cli-']):
                    system = 'Automation & Control'
                elif any(kw in name_lower for kw in ['hvac', 'thermostat', 'climate']):
                    system = 'HVAC'
                elif any(kw in name_lower for kw in ['switch', 'router', 'ubiquiti', 'unifi', 'poe', 'network', 'udm']):
                    system = 'Network & WiFi'
                elif any(kw in name_lower for kw in ['nvr', 'camera', 'protect', 'cctv', 'security']):
                    system = 'CCTV'
                else:
                    system = 'Automation & Control' if is_av else 'Network & WiFi'
                
                fill_color = system_colors.get(system, colors.HexColor('#34495E'))
                
                # Store connection point on right side
                # For Network & WiFi, we want to show MULTIPLE switches
                if system == 'Network & WiFi':
                    # Track multiple network connection points for multiple switches
                    if 'Network & WiFi' not in system_connection_points:
                        system_connection_points['Network & WiFi'] = (x + width, item_y + item_h / 2)
                    # Also store alternate connection point for second switch
                    if 'usw' in name_lower and '24' in name_lower:
                        if 'Network & WiFi 2' not in system_connection_points:
                            system_connection_points['Network & WiFi 2'] = (x + width, item_y + item_h / 2)
                        else:
                            # Update main to first, keep second as alternate
                            pass
                elif system not in system_connection_points:
                    system_connection_points[system] = (x + width, item_y + item_h / 2)
                
            elif item.item_type in (RackItemType.VENT_1U, RackItemType.VENT_2U):
                fill_color = colors.HexColor('#444444')
            else:
                fill_color = colors.HexColor('#333333')
            
            # Draw equipment
            inset = 8
            c.setFillColor(fill_color)
            c.setStrokeColor(colors.HexColor('#222222'))
            c.setLineWidth(0.5)
            c.rect(x + inset, item_y + 1, width - 2 * inset, item_h - 2, fill=1, stroke=1)
            
            # Label
            if item.item_type == RackItemType.EQUIPMENT:
                c.setFillColor(colors.white)
                font_size = max(5, min(7, int(item_h / 2.2)))
                c.setFont("Helvetica-Bold", font_size)
                
                label = f"{item.brand} {item.model}"
                max_chars = int((width - 2 * inset) / (font_size * 0.5))
                if len(label) > max_chars:
                    label = label[:max_chars-2] + ".."
                
                c.drawCentredString(x + width / 2, item_y + item_h / 2 - font_size / 3, label)
        
        return system_connection_points
    
    def _draw_simplified_rack(self, c, x: float, y: float, width: float, height: float,
                               title: str, is_av: bool) -> Dict[str, Tuple[float, float]]:
        """Draw simplified rack showing system sections (fallback when no specs available)"""
        
        # Rack frame
        c.setFillColor(colors.HexColor('#2C3E50'))
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.roundRect(x, y, width, height, 6, fill=1, stroke=1)
        
        # Title
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(x + width / 2, y + height + 8, title)
        
        # Draw SYSTEM SECTIONS
        if is_av:
            sections = [
                ('VIDEO', colors.HexColor('#3498DB'), 'IP Video Distribution'),
                ('AUDIO', colors.HexColor('#27AE60'), 'Amplifiers & DSP'),
                ('CONTROL', colors.HexColor('#9B59B6'), 'Automation Controller'),
                ('LIGHTING', colors.HexColor('#F1C40F'), 'Lighting Processor'),
                ('POWER', colors.HexColor('#C0392B'), 'Power & UPS'),
            ]
        else:
            sections = [
                ('NETWORK', colors.HexColor('#E67E22'), 'Switches & Router'),
                ('SECURITY', colors.HexColor('#E74C3C'), 'NVR & Cameras'),
                ('WIFI', colors.HexColor('#3498DB'), 'Access Points'),
            ]
        
        num_sections = len(sections)
        section_h = (height - 20) / num_sections
        section_w = width - 12
        section_x = x + 6
        
        system_connection_points = {}
        
        for idx, (name, color, description) in enumerate(sections):
            section_y = y + height - 10 - (idx + 1) * section_h
            
            c.setFillColor(color)
            c.setStrokeColor(colors.HexColor('#1a1a1a'))
            c.setLineWidth(1)
            c.roundRect(section_x, section_y, section_w, section_h - 4, 4, fill=1, stroke=1)
            
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(section_x + section_w / 2, section_y + section_h / 2 + 2, name)
            
            c.setFont("Helvetica", 6)
            c.drawCentredString(section_x + section_w / 2, section_y + section_h / 2 - 8, description)
            
            conn_y = section_y + section_h / 2
            
            if name == 'VIDEO':
                system_connection_points['Video'] = (x + width, conn_y)
            elif name == 'AUDIO':
                system_connection_points['Audio'] = (x + width, conn_y)
            elif name == 'CONTROL':
                system_connection_points['Automation & Control'] = (x + width, conn_y)
                system_connection_points['HVAC'] = (x + width, conn_y)
            elif name == 'LIGHTING':
                system_connection_points['Lighting Control'] = (x + width, conn_y)
            elif name == 'POWER':
                system_connection_points['Power Quality'] = (x + width, conn_y)
                system_connection_points['Equipment Racks & Power Quality'] = (x + width, conn_y)
            elif name == 'NETWORK':
                system_connection_points['Network & WiFi'] = (x + width, conn_y)
            elif name == 'SECURITY':
                system_connection_points['CCTV'] = (x + width, conn_y)
            elif name == 'WIFI':
                system_connection_points['Network & WiFi'] = (x + width, conn_y)
        
        return system_connection_points
    
    def _calculate_cable_callouts(self, room_systems: Dict[str, int], 
                                   room_devices: Dict[str, int] = None) -> Dict[str, Dict[str, int]]:
        """
        Calculate cable requirements per destination based on SPECIFIC DEVICES.
        
        Returns: {destination: {cable_type: count}}
        
        Cable Rules (Industry Standard):
        - TV/Display: CAT6 (2) per display → AV Rack
        - Speaker: SPK (1) per speaker → AV Rack
        - Subwoofer: SPK (1) per sub → AV Rack
        - LCR Bar: SPK (1) per bar → AV Rack
        - Keypad: CTRL (1) per keypad → Lighting Control
        - Camera: CAT6 (1) per camera → Network Rack
        - WiFi AP: CAT6 (1) per AP → Network Rack
        - HVAC Sensor: CAT6 (1) per sensor → AV Rack
        """
        cables = {
            'To AV Rack': defaultdict(int),
            'To Network Rack': defaultdict(int),
            'Lighting': defaultdict(int),
        }
        
        # Use device-level data if available (more accurate)
        if room_devices:
            for device_type, count in room_devices.items():
                if device_type == 'tv':
                    # TV/Display: CAT6 (2) per display
                    cables['To AV Rack']['CAT6'] += count * 2
                
                elif device_type in ('speaker', 'lcr_bar'):
                    # Speakers: SPK (1) per speaker
                    cables['To AV Rack']['SPK'] += count
                
                elif device_type == 'subwoofer':
                    # Subwoofer: SPK (1) per sub
                    cables['To AV Rack']['SPK'] += count
                
                elif device_type in ('keypad', 'keypad_wireless'):
                    # Keypads: CTRL (1) per keypad
                    cables['Lighting']['CTRL'] += count
                
                elif device_type in ('camera', 'intercom'):
                    # Cameras: CAT6 (1) per camera
                    cables['To Network Rack']['CAT6'] += count
                
                elif device_type == 'wap':
                    # WiFi APs: CAT6 (1) per AP
                    cables['To Network Rack']['CAT6'] += count
                
                elif device_type == 'thermostat':
                    # HVAC sensors: CAT6 (1) per sensor
                    cables['To AV Rack']['CAT6'] += count
        else:
            # Fall back to system-level calculation
            for system, count in room_systems.items():
                if system == 'Video':
                    cables['To AV Rack']['CAT6'] += count * 2
                elif system == 'Audio':
                    cables['To AV Rack']['SPK'] += count
                elif system == 'Lighting Control':
                    cables['Lighting']['CTRL'] += count
                elif system == 'CCTV':
                    cables['To Network Rack']['CAT6'] += count
                elif system == 'Network & WiFi':
                    cables['To Network Rack']['CAT6'] += count
                elif system == 'Automation & Control':
                    cables['To AV Rack']['CAT6'] += count
                elif system == 'HVAC':
                    cables['To AV Rack']['CAT6'] += count
        
        # Remove empty destinations
        return {dest: dict(types) for dest, types in cables.items() if types}
    
    def _draw_room_systems_box(self, c, x: float, y: float, w: float, h: float,
                                room_name: str, room_systems: Dict[str, int],
                                room_devices: Dict[str, int] = None):
        """Draw room box with SPECIFIC DEVICE TYPES and cable callouts - COMPACT VERSION"""
        
        # Box background
        c.setFillColor(colors.white)
        c.setStrokeColor(self.color_room)
        c.setLineWidth(1.5)
        c.roundRect(x, y, w, h, 4, fill=1, stroke=1)
        
        # Room header - compact
        header_h = 14
        c.setFillColor(self.color_room)
        c.roundRect(x, y + h - header_h, w, header_h, 4, fill=1, stroke=0)
        c.rect(x, y + h - header_h, w, header_h / 2, fill=1, stroke=0)
        
        # Room name - fit to width
        display_name = room_name[:24] if len(room_name) > 24 else room_name
        font_size = 7 if len(display_name) < 16 else 6
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(colors.white)
        c.drawCentredString(x + w / 2, y + h - header_h + 4, display_name.upper())
        
        # Calculate available space for content
        content_top = y + h - header_h - 4
        content_bottom = y + 6  # Increased bottom padding
        available_height = content_top - content_bottom
        
        # Determine how many items we can show - allow more lines with larger boxes
        line_h = 11  # Slightly larger line height for readability
        max_device_lines = int((available_height * 0.55) / line_h)  # 55% for devices
        max_cable_lines = int((available_height * 0.35) / line_h)   # 35% for cables
        
        max_device_lines = max(3, min(6, max_device_lines))  # Allow up to 6 device lines
        max_cable_lines = max(2, min(4, max_cable_lines))     # Allow up to 4 cable lines
        
        line_y = content_top - 2
        
        # Device type display names (short versions) - maps device_type to (display_label, icon_key)
        device_display = {
            'tv': ('TV', 'tv'),
            'speaker': ('Spkr', 'speaker'),
            'subwoofer': ('Sub', 'subwoofer'),
            'lcr_bar': ('LCR', 'speaker'),
            'keypad': ('Keypad', 'keypad'),
            'keypad_wireless': ('WL Keypad', 'keypad'),
            'wap': ('WiFi', 'wap'),
            'camera': ('Cam', 'camera'),
            'intercom': ('Intercom', 'camera'),
            'thermostat': ('HVAC', 'thermostat'),
            # DISTRIBUTED EQUIPMENT (in rooms, not main rack)
            'bijou': ('Bijou Amp', 'bijou'),
            'local_switch': ('PoE Switch', 'local_switch'),
            'climate_sensor': ('Climate Sens', 'climate_sensor'),
            'hvac_controller': ('HVAC Ctrl', 'hvac_controller'),
            'wap_outdoor': ('WiFi (Outdoor)', 'wap'),
        }
        
        # Show device types WITH SVG ICONS
        c.setFont("Helvetica", 6)
        c.setFillColor(colors.HexColor('#333333'))
        
        if room_devices:
            items_shown = 0
            for device_type, count in room_devices.items():
                if items_shown >= max_device_lines:
                    break
                
                display_info = device_display.get(device_type, (device_type[:6].title(), 'keypad'))
                label = display_info[0]
                icon_key = display_info[1]
                
                # Use SVG icon drawing method with compact size
                self._draw_icon_and_text(c, x + 4, line_y, icon_key, label, count, icon_size=8)
                line_y -= line_h
                items_shown += 1
        else:
            # Fallback: show systems (map to icons)
            system_to_icon = {
                'Video': 'tv',
                'Audio': 'speaker',
                'Lighting Control': 'keypad',
                'Automation & Control': 'keypad',
                'HVAC': 'thermostat',
                'Network & WiFi': 'wap',
                'CCTV': 'camera',
            }
            for system, count in list(room_systems.items())[:max_device_lines]:
                short_name = system.replace(' Control', '').replace(' & WiFi', '')[:8]
                icon_key = system_to_icon.get(system, 'keypad')
                self._draw_icon_and_text(c, x + 4, line_y, icon_key, short_name, count, icon_size=8)
                line_y -= line_h
        
        # Divider line before cable callouts
        line_y -= 3
        c.setStrokeColor(colors.HexColor('#CCCCCC'))
        c.setLineWidth(0.5)
        c.line(x + 4, line_y, x + w - 4, line_y)
        line_y -= 5
        
        # CABLE CALLOUTS - Single section with bounds checking
        cable_callouts = self._calculate_cable_callouts(room_systems, room_devices)
        
        if cable_callouts and line_y > content_bottom + 15:
            c.setFont("Helvetica-Bold", 6)
            c.setFillColor(colors.HexColor('#1a1a1a'))
            c.drawString(x + 4, line_y, "Rough-In Cabling:")
            line_y -= 9
            
            c.setFont("Helvetica", 5)
            c.setFillColor(colors.HexColor('#333333'))
            
            cables_shown = 0
            for destination, cable_types in cable_callouts.items():
                # Stop if we're running out of space
                if line_y < content_bottom or cables_shown >= max_cable_lines:
                    break
                
                cable_str = ", ".join([f"{ct}({n})" for ct, n in cable_types.items()])
                
                # Short destination names
                if destination == "To AV Rack":
                    dest_label = "→ Rack"
                elif destination == "To Network Rack":
                    dest_label = "→ Network"
                elif destination == "Lighting Control" or destination == "Lighting":
                    dest_label = "→ Lighting"
                else:
                    dest_label = f"→ {destination[:8]}"
                
                label = f"• {dest_label}: {cable_str}"
                c.drawString(x + 4, line_y, label[:32])  # Truncate to fit
                line_y -= 8
                cables_shown += 1
        # If no callouts or no space, skip the section
    
    def _draw_tree_connections(self, c, room_x: float, room_y: float, room_h: float,
                                room_systems: Dict[str, int], 
                                system_connection_points: Dict[str, Tuple[float, float]],
                                rack_right_x: float):
        """Draw CLEARLY SEPARATED connection lines - no overlapping"""
        
        system_colors = {
            'Video': colors.HexColor('#3498DB'),      # Blue
            'Audio': colors.HexColor('#27AE60'),      # Green
            'Lighting Control': colors.HexColor('#F1C40F'),  # Yellow
            'Automation & Control': colors.HexColor('#9B59B6'),  # Purple
            'HVAC': colors.HexColor('#1ABC9C'),       # Teal
            'Network & WiFi': colors.HexColor('#E67E22'),    # Orange
            'CCTV': colors.HexColor('#E74C3C'),       # Red
            'Power Quality': colors.HexColor('#C0392B'),
            'Equipment Racks & Power Quality': colors.HexColor('#C0392B'),
        }
        
        # Cable type labels for each system
        system_cable_labels = {
            'Video': 'CAT6',
            'Audio': 'SPK',
            'Lighting Control': 'CTRL',
            'Automation & Control': 'CAT6',
            'HVAC': 'CAT6',
            'Network & WiFi': 'CAT6',
            'CCTV': 'CAT6',
            'Power Quality': 'PWR',
            'Equipment Racks & Power Quality': 'PWR',
        }
        
        # Line styles to differentiate (in addition to colors)
        line_styles = [
            [],           # Solid
            [6, 3],       # Dashed
            [2, 2],       # Dotted
            [8, 2, 2, 2], # Dash-dot
            [4, 4],       # Medium dash
        ]
        
        num_systems = len(room_systems)
        
        for idx, (system, count) in enumerate(room_systems.items()):
            if system not in system_connection_points:
                continue
            
            color = system_colors.get(system, colors.gray)
            cable_label = system_cable_labels.get(system, 'WIRE')
            target_x, target_y = system_connection_points[system]
            line_style = line_styles[idx % len(line_styles)]
            
            # Start from LEFT side of room box
            start_x = room_x
            # WIDELY stagger vertically along the left edge - 20px apart
            start_y = room_y + room_h - 15 - (idx * 20)
            
            c.setStrokeColor(color)
            c.setLineWidth(2.5)  # Thicker lines
            c.setDash(line_style)
            
            # Calculate routing path - WIDE spacing between channels (25px apart)
            channel_x = rack_right_x + 0.2 * inch + (idx * 25)
            
            # Draw the 3-segment path
            # Segment 1: Horizontal from room to channel
            c.line(start_x, start_y, channel_x, start_y)
            
            # Segment 2: Vertical from room level to rack equipment level
            c.line(channel_x, start_y, channel_x, target_y)
            
            # Segment 3: Horizontal to rack
            c.line(channel_x, target_y, target_x, target_y)
            
            c.setDash([])  # Reset for arrow
            
            # Draw arrow at rack end
            arrow_size = 6
            c.setFillColor(color)
            arrow = c.beginPath()
            arrow.moveTo(target_x, target_y)
            arrow.lineTo(target_x + arrow_size, target_y - arrow_size/2)
            arrow.lineTo(target_x + arrow_size, target_y + arrow_size/2)
            arrow.close()
            c.drawPath(arrow, fill=1, stroke=0)
            
            # LARGE LABEL on the vertical portion - stagger labels vertically too
            label_x = channel_x
            # Stagger label positions to avoid overlap
            label_offset = 30 * (idx % 3) - 30
            label_y = (start_y + target_y) / 2 + label_offset
            
            # Large white background pill for label
            label_text = f"{cable_label} ({count})"
            text_width = len(label_text) * 6 + 10
            c.setFillColor(colors.white)
            c.setStrokeColor(color)
            c.setLineWidth(2)
            c.roundRect(label_x - text_width/2, label_y - 8, text_width, 16, 4, fill=1, stroke=1)
            
            # Draw label text - LARGER
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(label_x, label_y - 4, label_text)
    
    def _draw_system_legend(self, c, is_av: bool):
        """Draw legend for system types - COMBINED for single rack view"""
        
        # Position: right side, moved UP towards middle of page
        legend_w = 1.8 * inch  # Wider
        legend_x = self.width - self.margin - legend_w - 0.1 * inch
        legend_y = self.footer_height + 1.5 * inch  # MOVED UP
        
        # Combined legend for single rack (all systems)
        items = [
            (colors.HexColor('#3498DB'), "Video (CAT6)"),
            (colors.HexColor('#27AE60'), "Audio (SPK)"),
            (colors.HexColor('#F1C40F'), "Lighting (CTRL)"),
            (colors.HexColor('#E67E22'), "Network/WiFi (CAT6)"),  # ADDED
            (colors.HexColor('#E74C3C'), "CCTV (CAT6)"),
            (colors.HexColor('#9B59B6'), "Control (CAT6)"),
            (colors.HexColor('#1ABC9C'), "HVAC (CAT6)"),
            (colors.HexColor('#C0392B'), "Power"),
        ]
        
        legend_h = len(items) * 16 + 24  # Taller with more spacing
        
        # Background
        c.setFillColor(colors.HexColor('#FFFFFF'))
        c.setStrokeColor(colors.HexColor('#333333'))
        c.setLineWidth(1.5)
        c.roundRect(legend_x, legend_y, legend_w, legend_h, 6, fill=1, stroke=1)
        
        # Title
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(legend_x + 8, legend_y + legend_h - 14, "SYSTEMS LEGEND")
        
        # Divider line under title
        c.setStrokeColor(colors.HexColor('#CCCCCC'))
        c.setLineWidth(0.5)
        c.line(legend_x + 5, legend_y + legend_h - 20, legend_x + legend_w - 5, legend_y + legend_h - 20)
        
        line_y = legend_y + legend_h - 34
        for color, label in items:
            # Color swatch (line style)
            c.setStrokeColor(color)
            c.setLineWidth(3)
            c.line(legend_x + 8, line_y + 4, legend_x + 28, line_y + 4)
            
            # Label
            c.setFillColor(colors.HexColor('#333333'))
            c.setFont("Helvetica", 8)
            c.drawString(legend_x + 34, line_y, label)
            
            line_y -= 16
    
    def _draw_rack_page(self, c, layout: 'RackLayout', rooms: Dict[str, RoomWiring],
                        rack_title: str, page_subtitle: str, 
                        device_filter: set, is_av: bool):
        """Draw a single page with rack on left, rooms on right, with specific connections"""
        
        # Draw header
        self._draw_header(c, subtitle=page_subtitle)
        
        # Layout dimensions
        usable_y_top = self.height - self.header_height - 0.2 * inch
        usable_y_bottom = self.footer_height + 0.3 * inch
        usable_height = usable_y_top - usable_y_bottom
        
        # Rack on left side - make it tall
        rack_w = 2.2 * inch
        rack_h = usable_height - 0.4 * inch
        rack_x = self.margin + 0.3 * inch
        rack_y = usable_y_bottom + 0.2 * inch
        
        # Draw rack and get connection points for each equipment
        equipment_points = self._draw_detailed_rack(c, rack_x, rack_y, rack_w, rack_h, 
                                                     layout, rack_title, is_av)
        
        # Room area on right side
        room_area_x = rack_x + rack_w + 0.8 * inch
        room_area_w = self.width - room_area_x - self.margin
        
        # Filter rooms that have relevant devices
        relevant_rooms = []
        for room_key, room in rooms.items():
            room_devices = [d for d in room.devices if d.device_type in device_filter]
            if room_devices:
                relevant_rooms.append((room_key, room, room_devices))
        
        if not relevant_rooms:
            # Draw "No devices" message
            c.setFont("Helvetica", 12)
            c.setFillColor(colors.gray)
            c.drawString(room_area_x, rack_y + rack_h / 2, "No devices for this rack type")
            self._draw_footer(c)
            return
        
        # Calculate room box sizes - MUCH TALLER for readability
        num_rooms = len(relevant_rooms)
        max_rooms_per_col = 5  # Fewer per column since boxes are taller
        cols = (num_rooms + max_rooms_per_col - 1) // max_rooms_per_col
        cols = min(cols, 3)  # Max 3 columns
        
        room_w = (room_area_w - (cols - 1) * 0.2 * inch) / cols
        room_w = min(room_w, 3.0 * inch)
        room_h = 1.5 * inch  # Much taller for readability
        gap_y = 0.15 * inch
        
        rows_per_col = (num_rooms + cols - 1) // cols
        
        # Draw rooms and connections
        for idx, (room_key, room, room_devices) in enumerate(relevant_rooms):
            col = idx // rows_per_col
            row = idx % rows_per_col
            
            room_x = room_area_x + col * (room_w + 0.15 * inch)
            room_y = rack_y + rack_h - (row + 1) * (room_h + gap_y)
            
            # Draw connections FIRST (behind boxes)
            self._draw_device_connections(c, room_x, room_y, room_w, room_h,
                                          room_devices, equipment_points, rack_x + rack_w)
            
            # Draw room box with device icons
            self._draw_room_with_devices(c, room_x, room_y, room_w, room_h, 
                                         room_key, room_devices)
        
        # Draw legend
        self._draw_connection_legend(c, is_av)
        
        # Draw footer
        self._draw_footer(c)
    
    def _draw_detailed_rack(self, c, x: float, y: float, width: float, height: float,
                            layout: 'RackLayout', title: str, is_av: bool) -> Dict[str, List[Tuple[float, float]]]:
        """Draw detailed rack with equipment, return connection points by device type"""
        
        rack_size_u = layout.rack_size_u
        u_height = height / rack_size_u
        
        # Rack frame
        c.setFillColor(colors.HexColor('#1a1a1a'))
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.rect(x, y, width, height, fill=1, stroke=1)
        
        # Title above rack
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(x + width / 2, y + height + 8, title)
        
        # U numbers on left
        c.setFont("Helvetica", 5)
        c.setFillColor(colors.gray)
        for u in range(1, rack_size_u + 1, 4):
            u_y = y + (u - 1) * u_height + u_height / 2
            c.drawRightString(x - 3, u_y - 2, f"{u}U")
        
        # Rails
        rail_w = 5
        c.setFillColor(colors.HexColor('#333333'))
        c.rect(x + 3, y, rail_w, height, fill=1, stroke=0)
        c.rect(x + width - rail_w - 3, y, rail_w, height, fill=1, stroke=0)
        
        # Equipment connection points by device type
        equipment_points = defaultdict(list)
        
        for item in layout.items:
            item_y = y + (item.position_u - 1) * u_height
            item_h = item.rack_units * u_height
            
            # Determine equipment type and color
            name_lower = f"{item.brand} {item.model} {item.name}".lower()
            
            if item.item_type == RackItemType.EQUIPMENT:
                if any(kw in name_lower for kw in ['switch', 'router', 'ubiquiti', 'unifi', 'poe']):
                    fill_color = colors.HexColor('#E67E22')
                    eq_type = 'wap'  # Network switches connect to WAPs
                elif any(kw in name_lower for kw in ['nvr', 'protect', 'camera']):
                    fill_color = colors.HexColor('#E74C3C')
                    eq_type = 'camera'
                elif any(kw in name_lower for kw in ['amp', 'sonance', 'crown', 'audio']):
                    fill_color = colors.HexColor('#27AE60')
                    eq_type = 'speaker'
                elif any(kw in name_lower for kw in ['savant', 'control', 'ssc', 'pkg-']):
                    fill_color = colors.HexColor('#9B59B6')
                    eq_type = 'keypad'
                elif any(kw in name_lower for kw in ['video', 'matrix', 'ps65', 'ps80', 'svr', 'ub32']):
                    fill_color = colors.HexColor('#3498DB')
                    eq_type = 'tv'
                elif any(kw in name_lower for kw in ['lutron', 'hqp', 'lighting']):
                    fill_color = colors.HexColor('#F1C40F')
                    eq_type = 'keypad'
                else:
                    fill_color = colors.HexColor('#34495E')
                    eq_type = 'other'
                
                # Store connection point on right side of equipment
                conn_y = item_y + item_h / 2
                equipment_points[eq_type].append((x + width, conn_y))
                
            elif item.item_type in (RackItemType.VENT_1U, RackItemType.VENT_2U):
                fill_color = colors.HexColor('#444444')
            else:
                fill_color = colors.HexColor('#333333')
            
            # Draw equipment
            inset = 10
            c.setFillColor(fill_color)
            c.setStrokeColor(colors.HexColor('#222222'))
            c.setLineWidth(0.5)
            c.rect(x + inset, item_y + 1, width - 2 * inset, item_h - 2, fill=1, stroke=1)
            
            # Label
            if item.item_type == RackItemType.EQUIPMENT:
                c.setFillColor(colors.white)
                font_size = max(5, min(7, int(item_h / 2.2)))
                c.setFont("Helvetica-Bold", font_size)
                
                label = f"{item.brand} {item.model}"
                max_chars = int((width - 2 * inset) / (font_size * 0.5))
                if len(label) > max_chars:
                    label = label[:max_chars-2] + ".."
                
                c.drawCentredString(x + width / 2, item_y + item_h / 2 - font_size / 3, label)
        
        # Add subwoofer as alias for speaker, video_rx as alias for tv
        if 'speaker' in equipment_points:
            equipment_points['subwoofer'] = equipment_points['speaker']
        if 'tv' in equipment_points:
            equipment_points['video_rx'] = equipment_points['tv']
        if 'keypad' in equipment_points:
            equipment_points['touch_panel'] = equipment_points['keypad']
        if 'wap' in equipment_points:
            equipment_points['thermostat'] = equipment_points['wap']
        
        return equipment_points
    
    def _draw_room_with_devices(self, c, x: float, y: float, w: float, h: float,
                                 room_key: str, devices: List['RoughInDevice']):
        """Draw room box with device icons listed"""
        
        # Box background
        c.setFillColor(colors.white)
        c.setStrokeColor(self.color_room)
        c.setLineWidth(1.5)
        c.roundRect(x, y, w, h, 3, fill=1, stroke=1)
        
        # Room header
        header_h = 14
        c.setFillColor(self.color_room)
        c.roundRect(x, y + h - header_h, w, header_h, 3, fill=1, stroke=0)
        c.rect(x, y + h - header_h, w, header_h / 2, fill=1, stroke=0)
        
        # Room name
        display_name = room_key[:28] if len(room_key) > 28 else room_key
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(colors.white)
        c.drawCentredString(x + w / 2, y + h - 11, display_name.upper())
        
        # Device list with SVG icons
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont("Helvetica", 6)
        
        line_y = y + h - header_h - 12
        line_h = 12
        
        device_summary = defaultdict(int)
        for d in devices:
            device_summary[d.device_type] += d.quantity
        
        # Use DEVICE_LABELS for display names
        device_labels = {
            'tv': 'TV', 'video_rx': 'Video Rx', 'speaker': 'Speakers',
            'subwoofer': 'Subwoofer', 'lcr_bar': 'LCR Bar', 'keypad': 'Keypad',
            'keypad_wireless': 'Keypad', 'touch_panel': 'Touch Panel',
            'wap': 'WiFi AP', 'camera': 'Camera', 'thermostat': 'Thermostat',
            'local_amp': 'Bijou Amp', 'local_switch': 'Local Switch',
            'climate_ctrl': 'Climate Ctrl'
        }
        
        for device_type, qty in list(device_summary.items())[:6]:
            label = device_labels.get(device_type, device_type.replace('_', ' ').title())
            # Use SVG icons via _draw_icon_and_text
            self._draw_icon_and_text(c, x + 5, line_y, device_type, label, qty, icon_size=9)
            line_y -= line_h
    
    def _draw_device_connections(self, c, room_x: float, room_y: float, 
                                  room_w: float, room_h: float,
                                  devices: List['RoughInDevice'],
                                  equipment_points: Dict[str, List[Tuple[float, float]]],
                                  rack_right_x: float):
        """Draw connection lines from room to specific equipment in rack"""
        
        device_summary = defaultdict(int)
        for d in devices:
            device_summary[d.device_type] += d.quantity
        
        # Colors for each device type
        type_colors = {
            'tv': self.color_cat6, 'video_rx': self.color_cat6,
            'speaker': self.color_speaker, 'subwoofer': self.color_speaker,
            'keypad': self.color_control, 'touch_panel': self.color_control,
            'wap': self.color_cat6, 'thermostat': self.color_cat6,
            'camera': self.color_hdmi
        }
        
        # Connection labels
        type_labels = {
            'tv': 'CAT6', 'video_rx': 'CAT6', 
            'speaker': 'SPK', 'subwoofer': 'SPK',
            'keypad': 'CAT6', 'touch_panel': 'CAT6',
            'wap': 'CAT6', 'thermostat': 'CAT6',
            'camera': 'CAT6'
        }
        
        connections_drawn = 0
        for device_type, qty in device_summary.items():
            if device_type not in equipment_points or not equipment_points[device_type]:
                continue
            
            # Get the best connection point (closest one)
            room_center_y = room_y + room_h / 2
            eq_points = equipment_points[device_type]
            best_point = min(eq_points, key=lambda p: abs(p[1] - room_center_y))
            
            color = type_colors.get(device_type, colors.gray)
            label = type_labels.get(device_type, 'CAT6')
            
            # Line start (left side of room)
            start_x = room_x
            start_y = room_y + room_h / 2 + (connections_drawn - 1) * 8
            
            # Line end (equipment in rack)
            end_x, end_y = best_point
            
            # Draw connection line with elbow
            c.setStrokeColor(color)
            c.setLineWidth(1.2)
            c.setDash([])
            
            # Calculate mid point for elbow
            mid_x = (start_x + end_x) / 2 + (connections_drawn * 4)
            
            # Draw path: room -> mid -> equipment
            path = c.beginPath()
            path.moveTo(start_x, start_y)
            path.lineTo(mid_x, start_y)
            path.lineTo(mid_x, end_y)
            path.lineTo(end_x, end_y)
            c.drawPath(path)
            
            # Draw arrow at equipment end
            arrow_size = 4
            c.setFillColor(color)
            arrow = c.beginPath()
            arrow.moveTo(end_x, end_y)
            arrow.lineTo(end_x + arrow_size, end_y - arrow_size/2)
            arrow.lineTo(end_x + arrow_size, end_y + arrow_size/2)
            arrow.close()
            c.drawPath(arrow, fill=1, stroke=0)
            
            # Label with count on the line
            label_x = mid_x + 3
            label_y = (start_y + end_y) / 2
            
            c.setFillColor(colors.white)
            c.roundRect(label_x - 2, label_y - 5, 28, 10, 2, fill=1, stroke=0)
            
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 6)
            c.drawString(label_x, label_y - 2, f"{label}({qty})")
            
            connections_drawn += 1
    
    def _draw_connection_legend(self, c, is_av: bool):
        """Draw legend for connection types"""
        
        legend_x = self.width - self.margin - 1.8 * inch
        legend_y = self.footer_height + 0.4 * inch
        legend_w = 1.7 * inch
        legend_h = 1.2 * inch
        
        # Background
        c.setFillColor(colors.HexColor('#F8F9FA'))
        c.setStrokeColor(colors.HexColor('#DEE2E6'))
        c.setLineWidth(1)
        c.roundRect(legend_x, legend_y, legend_w, legend_h, 4, fill=1, stroke=1)
        
        # Title
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(legend_x + 5, legend_y + legend_h - 12, "CONNECTION TYPES")
        
        # Legend items
        items = []
        if is_av:
            items = [
                (self.color_cat6, "CAT6 - Video/Data"),
                (self.color_speaker, "Speaker Wire"),
                (self.color_control, "Control (CAT6)"),
            ]
        else:
            items = [
                (self.color_cat6, "CAT6 - Network"),
                (self.color_hdmi, "CAT6 - Security"),
            ]
        
        line_y = legend_y + legend_h - 28
        for color, label in items:
            c.setStrokeColor(color)
            c.setLineWidth(2)
            c.line(legend_x + 8, line_y + 3, legend_x + 28, line_y + 3)
            
            c.setFillColor(colors.HexColor('#333333'))
            c.setFont("Helvetica", 7)
            c.drawString(legend_x + 32, line_y, label)
            
            line_y -= 14
    
    def _draw_room_box_compact(self, c, x: float, y: float, width: float, height: float,
                               room_key: str, room: RoomWiring):
        """Draw a compact room box with devices"""
        # Box background
        c.setFillColor(colors.HexColor('#F8F9FA'))
        c.setStrokeColor(self.color_room)
        c.setLineWidth(1.5)
        c.roundRect(x, y, width, height, 4, fill=1, stroke=1)
        
        # Room header
        header_h = 16
        c.setFillColor(self.color_room)
        c.roundRect(x, y + height - header_h, width, header_h, 4, fill=1, stroke=0)
        c.rect(x, y + height - header_h, width, header_h / 2, fill=1, stroke=0)
        
        # Room name
        display_name = room_key[:22] if len(room_key) > 22 else room_key
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(colors.white)
        c.drawCentredString(x + width / 2, y + height - 12, display_name.upper())
        
        # Device summary (compact)
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont("Helvetica", 6)
        
        line_y = y + height - header_h - 10
        line_height = 9
        
        device_summary = defaultdict(int)
        for device in room.devices:
            device_summary[device.device_type] += device.quantity
        
        icons = {'tv': '📺', 'speaker': '🔊', 'keypad': '🔘', 'wap': '📶', 
                'camera': '📷', 'video_rx': '📡', 'subwoofer': '🔈'}
        
        for device_type, qty in list(device_summary.items())[:4]:  # Max 4 items
            icon = icons.get(device_type, '•')
            label = f"{icon} {device_type.replace('_', ' ').title()} ({qty})"
            c.drawString(x + 4, line_y, label[:18])
            line_y -= line_height
    
    def _draw_actual_rack_homerun(self, c, room_x: float, room_y: float,
                                   av_rack_x: Optional[float], net_rack_x: Optional[float],
                                   rack_y: float, rack_w: float, rack_h: float,
                                   room: RoomWiring, av_conn: Dict, net_conn: Dict):
        """Draw homerun lines from room to actual equipment in racks"""
        
        device_types = set(d.device_type for d in room.devices)
        connections = []
        
        # Determine connections based on device types
        # Video → AV Rack video equipment
        if any(t in device_types for t in ['tv', 'video_rx']) and av_rack_x and 'tv' in av_conn:
            count = sum(d.quantity * 2 for d in room.devices if d.device_type in ['tv', 'video_rx'])
            connections.append((av_conn['tv'], self.color_cat6, count))
        
        # Audio → AV Rack amplifiers
        if any(t in device_types for t in ['speaker', 'subwoofer']) and av_rack_x and 'speaker' in av_conn:
            connections.append((av_conn['speaker'], self.color_speaker, room.speaker_wire_count))
        
        # Control → AV Rack control processor
        if any(t in device_types for t in ['keypad', 'touch_panel']) and av_rack_x and 'keypad' in av_conn:
            count = sum(d.quantity for d in room.devices if d.device_type in ['keypad', 'touch_panel'])
            connections.append((av_conn['keypad'], self.color_control, count))
        
        # Network → Network Rack switches
        if any(t in device_types for t in ['wap', 'thermostat']) and net_rack_x:
            conn_point = net_conn.get('network') or net_conn.get('wap')
            if conn_point:
                count = sum(d.quantity for d in room.devices if d.device_type in ['wap', 'thermostat'])
                connections.append((conn_point, self.color_cat6, count))
        
        # Cameras → Network Rack NVR/switches
        if 'camera' in device_types and net_rack_x:
            conn_point = net_conn.get('camera') or net_conn.get('network')
            if conn_point:
                count = sum(d.quantity for d in room.devices if d.device_type == 'camera')
                connections.append((conn_point, self.color_hdmi, count))
        
        # Draw connection lines
        for idx, ((target_x, target_y), color, count) in enumerate(connections):
            if count <= 0:
                continue
            
            c.setStrokeColor(color)
            c.setLineWidth(0.8)
            c.setDash([2, 2])
            
            offset = (idx - len(connections) / 2) * 5
            mid_y = (room_y + target_y) / 2 + offset
            
            c.line(room_x + offset, room_y, room_x + offset, mid_y)
            c.line(room_x + offset, mid_y, target_x, mid_y)
            c.line(target_x, mid_y, target_x, target_y)
            
            c.setDash([])
    
    def _draw_room_box(self, c, x, y, room_key: str, room: RoomWiring):
        """Draw a room box with devices"""
        # Box background
        c.setFillColor(colors.HexColor('#F8F9FA'))
        c.setStrokeColor(self.color_room)
        c.setLineWidth(2)
        c.roundRect(x, y, self.room_box_w, self.room_box_h, 6, fill=1, stroke=1)
        
        # Room header bar
        header_h = 22
        c.setFillColor(self.color_room)
        c.roundRect(x, y + self.room_box_h - header_h, self.room_box_w, header_h, 
                   6, fill=1, stroke=0)
        # Cover bottom corners
        c.rect(x, y + self.room_box_h - header_h, self.room_box_w, header_h / 2, 
               fill=1, stroke=0)
        
        # Room name - use smaller font if name is long
        display_name = room_key[:30] if len(room_key) > 30 else room_key
        font_size = 10 if len(display_name) > 20 else 11
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(colors.white)
        c.drawCentredString(x + self.room_box_w / 2, y + self.room_box_h - 16, 
                           display_name.upper())
        
        # Device list
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont("Helvetica", 9)
        
        line_y = y + self.room_box_h - header_h - 16
        line_height = 14
        
        # Group devices by type and show counts
        device_summary = defaultdict(int)
        for device in room.devices:
            device_summary[device.device_type] += device.quantity
        
        device_labels = {
            'tv': 'TV / Display',
            'speaker': 'Speakers',
            'subwoofer': 'Subwoofer',
            'keypad': 'Keypads',
            'camera': 'Cameras',
            'wap': 'WiFi AP',
            'touch_panel': 'Touch Panel',
            'video_rx': 'Video Rx',
            'thermostat': 'Thermostat',
        }
        
        for device_type, qty in device_summary.items():
            label = device_labels.get(device_type, device_type.title())
            self._draw_icon_and_text(c, x + 8, line_y, device_type, label, qty, icon_size=11)
            line_y -= line_height
            
            if line_y < y + 10:
                break  # Prevent overflow
    
    def _draw_homerun(self, c, room_x, room_y, head_x, head_y, room: RoomWiring):
        """Draw homerun line from room to head-end with cable labels"""
        # Draw the line
        c.setStrokeColor(self.color_cable)
        c.setLineWidth(1.5)
        c.setDash([4, 2])  # Dashed line
        
        # Calculate intermediate point for cleaner routing
        mid_y = (room_y + head_y) / 2 + 20
        
        # Draw path: room -> up -> across -> down -> head-end
        c.line(room_x, room_y, room_x, mid_y)
        c.line(room_x, mid_y, head_x, mid_y)
        c.line(head_x, mid_y, head_x, head_y)
        
        c.setDash([])  # Reset dash
        
        # Cable label (positioned along the vertical segment from room)
        if room.cat6_count > 0 or room.speaker_wire_count > 0:
            label_y = room_y + 15
            label_x = room_x + 8
            
            c.setFont("Helvetica-Bold", 8)
            
            labels = []
            if room.cat6_count > 0:
                labels.append(f"CAT6 ({room.cat6_count})")
            if room.speaker_wire_count > 0:
                labels.append(f"SPK ({room.speaker_wire_count})")
            
            # Draw label background
            label_text = " + ".join(labels)
            text_width = c.stringWidth(label_text, "Helvetica-Bold", 8)
            
            c.setFillColor(colors.white)
            c.rect(label_x - 2, label_y - 3, text_width + 4, 11, fill=1, stroke=0)
            
            c.setFillColor(self.color_cat6 if room.cat6_count > 0 else self.color_speaker)
            c.drawString(label_x, label_y, label_text)
    
    def _draw_legend(self, c):
        """Draw cable type legend - compact box at bottom right, below room boxes"""
        # Compact legend - fits below Office/Gym boxes
        legend_h = 0.45 * inch  # Compact height
        legend_w = 5.5 * inch   # Moderate width to fit 4 items
        legend_x = self.width - legend_w - self.margin  # Right-aligned
        legend_y = 0.55 * inch  # Just above footer disclaimer
        
        # Legend box with white background
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor('#2C3E50'))
        c.setLineWidth(1)
        c.roundRect(legend_x, legend_y, legend_w, legend_h, 4, fill=1, stroke=1)
        
        # Legend items - compact horizontal layout
        items = [
            (self.color_cat6, "CAT6"),
            (self.color_speaker, "SPK"),
            (self.color_hdmi, "HDMI"),
            (self.color_control, "CTRL"),
        ]
        
        # Draw title
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.HexColor('#2C3E50'))
        c.drawString(legend_x + 8, legend_y + legend_h / 2 - 3, "LEGEND:")
        
        # Draw items horizontally - compact
        item_x = legend_x + 0.7 * inch
        item_y = legend_y + legend_h / 2
        item_spacing = 1.2 * inch
        
        c.setFont("Helvetica-Bold", 8)
        for color, label in items:
            # Color dot (smaller)
            c.setFillColor(color)
            c.circle(item_x + 6, item_y, 5, fill=1, stroke=0)
            
            # Label
            c.setFillColor(colors.HexColor('#333333'))
            c.drawString(item_x + 16, item_y - 3, label)
            
            item_x += item_spacing
    
    def _draw_footer(self, c, zone_mode: bool = False):
        """Draw footer with disclaimer including cable callout notice"""
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(colors.HexColor('#666666'))
        
        if zone_mode:
            disclaimer1 = ("Zone-based rough-in view generated without room/location assignments. "
                          "Counts are based on equipment list; room placement to be provided by integrator.")
            disclaimer2 = ""
        else:
            disclaimer1 = ("Rough-In plan shows locations and cable paths/counts only; "
                          "final routing and terminations to be verified by integrator on site.")
            disclaimer2 = ("Cable quantities shown for rough-in purposes only. "
                          "Final routing, terminations, and port assignments to be completed by integrator.")
        
        c.drawCentredString(self.width / 2, 0.35 * inch, disclaimer1)
        if disclaimer2:
            c.drawCentredString(self.width / 2, 0.2 * inch, disclaimer2)
        
        # Divider line
        c.setStrokeColor(colors.HexColor('#CCCCCC'))
        c.setLineWidth(0.5)
        c.line(self.margin, self.footer_height, 
               self.width - self.margin, self.footer_height)
    
    def _draw_floorplan_background(self, c, floorplan_path: str):
        """Draw floorplan as faint background image"""
        try:
            doc = fitz.open(floorplan_path)
            if len(doc) > 0:
                page = doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                
                # Save as temp image
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    pix.save(tmp.name)
                    
                    # Draw with transparency (faint)
                    c.saveState()
                    c.setFillAlpha(0.15)
                    
                    # Scale to fit page
                    img_w = pix.width
                    img_h = pix.height
                    scale = min((self.width - 2 * self.margin) / img_w,
                               (self.height - self.header_height - self.footer_height) / img_h)
                    
                    draw_w = img_w * scale
                    draw_h = img_h * scale
                    draw_x = (self.width - draw_w) / 2
                    draw_y = self.footer_height + (self.height - self.header_height - 
                                                    self.footer_height - draw_h) / 2
                    
                    c.drawImage(tmp.name, draw_x, draw_y, draw_w, draw_h)
                    c.restoreState()
                    
                    import os
                    os.unlink(tmp.name)
            doc.close()
        except Exception as e:
            print(f"⚠️ Could not load floorplan: {e}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate Electrician / Low-Voltage Rough-In Wiring Plan PDF'
    )
    parser.add_argument('csv_path', help='Path to equipment CSV file')
    parser.add_argument('--project_name', '-p', default='Sample Residence',
                       help='Project name for title (default: Sample Residence)')
    parser.add_argument('--mode', '-m', choices=['room', 'zone'], default='room',
                       help='Mode: room (per-room boxes) or zone (logical zone boxes)')
    parser.add_argument('--rack', '-r', action='store_true',
                       help='Show integrated rack elevation with equipment-specific connections')
    parser.add_argument('--dual-rack', '-d', action='store_true',
                       help='Show dual rack view (AV + Network) with connections to each')
    parser.add_argument('--floorplan', '-f', default=None,
                       help='Optional path to floorplan PDF for background (room mode only)')
    parser.add_argument('--output', '-o', default=None,
                       help='Output PDF path (default: auto-generated)')
    parser.add_argument('--rack-size', type=int, default=None,
                       help='Override detected rack size (in U)')
    
    args = parser.parse_args()
    
    # Validate input
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        sys.exit(1)
    
    print(f"📋 Parsing CSV: {csv_path}")
    print(f"📌 Mode: {args.mode.upper()}")
    print("-" * 60)
    
    # Generate output path
    if args.output:
        output_path = args.output
    else:
        csv_name = csv_path.stem.replace(' ', '_')
        mode_suffix = "_Zone" if args.mode == "zone" else ""
        rack_suffix = "_Dual_Rack" if args.dual_rack else ("_Rack" if args.rack else "")
        output_path = f"{csv_name}_Rough_In_Wiring_Plan{mode_suffix}{rack_suffix}.pdf"
    
    # Create generator
    generator = RoughInPlanGenerator(project_name=args.project_name, mode=args.mode)
    
    if args.mode == "zone":
        # Zone mode - group by logical zones
        zones = parse_csv_for_zones(str(csv_path))
        
        print(f"📦 Found {len(zones)} zones with rough-in devices:")
        for zone_name, zone in zones.items():
            device_count = sum(d.quantity for d in zone.devices)
            print(f"   • {zone_name}: {device_count} devices "
                  f"(CAT6:{zone.cat6_count}, SPK:{zone.speaker_wire_count})")
        
        print("-" * 60)
        generator.generate_zones(zones, output_path)
    else:
        # Room mode - group by room/location
        rooms = parse_csv_for_rough_in(str(csv_path))
        
        print(f"🏠 Found {len(rooms)} rooms with rough-in devices:")
        for room_key, room in rooms.items():
            device_count = sum(d.quantity for d in room.devices)
            print(f"   • {room_key}: {device_count} devices "
                  f"(CAT6:{room.cat6_count}, SPK:{room.speaker_wire_count})")
        
        print("-" * 60)
        
        if args.dual_rack:
            # Dual rack view (AV + Network) with connections
            generator.generate_dual_rack(rooms, str(csv_path), output_path, rack_size_override=args.rack_size)
        elif args.rack:
            # Integrated rack elevation view
            generator.generate_with_rack(rooms, output_path)
        else:
            generator.generate(rooms, output_path, args.floorplan)
    
    print(f"\n✅ Done! Output: {output_path}")
    
    return output_path


if __name__ == "__main__":
    main()

