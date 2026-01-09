#!/usr/bin/env python3
"""
Block Diagram Generator
Creates high-level system architecture diagrams from System Intent + Equipment CSVs
"""

import csv
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, TABLOID

# ARCH_D is 24x36 inches
ARCH_D = (24 * 72, 36 * 72)  # In points (72 points per inch)
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# System colors
SYSTEM_COLORS = {
    'video': colors.HexColor('#3498DB'),        # Blue
    'video_rx': colors.HexColor('#5DADE2'),     # Light blue (video receivers)
    'audio': colors.HexColor('#27AE60'),        # Green
    'network': colors.HexColor('#E67E22'),      # Orange
    'control': colors.HexColor('#9B59B6'),      # Purple
    'lighting': colors.HexColor('#F1C40F'),     # Yellow
    'hvac': colors.HexColor('#1ABC9C'),         # Teal
    'power': colors.HexColor('#E74C3C'),        # Red
    'security': colors.HexColor('#34495E'),     # Dark gray
    'other': colors.HexColor('#95A5A6'),        # Gray
}

SYSTEM_LABELS = {
    'video': 'VIDEO',
    'video_rx': 'VIDEO RX',
    'audio': 'AUDIO', 
    'network': 'NETWORK',
    'control': 'CONTROL',
    'lighting': 'LIGHTING',
    'hvac': 'HVAC',
    'power': 'POWER',
    'security': 'SECURITY',
    'other': 'OTHER',
}


@dataclass
class SystemIntent:
    """System architecture intent from System Intent CSV"""
    rack_topology: str = "Single"
    rack_location: str = "Equipment Closet"
    video_distribution: str = "Centralized"
    audio_architecture: str = "Centralized"
    network_architecture: str = "All Networked"
    central_controller: bool = True
    
    @classmethod
    def from_csv(cls, csv_path: str) -> 'SystemIntent':
        """Parse System Intent CSV"""
        intent = cls()
        
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        content = None
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, FileNotFoundError):
                continue
        
        if not content:
            return intent
        
        reader = csv.DictReader(content.splitlines())
        for row in reader:
            intent.rack_topology = row.get('Rack_Topology', 'Single')
            intent.rack_location = row.get('Rack_location', 'Equipment Closet')
            intent.video_distribution = row.get('Video_Distribution', 'Centralized')
            intent.audio_architecture = row.get('Audio_Architecture', 'Centralized')
            intent.network_architecture = row.get('Network_Architecture', 'All Networked')
            intent.central_controller = row.get('Central_Controller', 'Yes').lower() == 'yes'
            break
        
        return intent


@dataclass
class EquipmentBlock:
    """Equipment grouped by system"""
    system: str
    items: Dict[str, int] = field(default_factory=dict)  # item_name -> count


@dataclass
class LocationBlock:
    """A location with its equipment"""
    name: str
    level: str
    room_number: str
    equipment: Dict[str, EquipmentBlock] = field(default_factory=dict)
    is_head_end: bool = False
    has_idf: bool = False


def categorize_part(part_number: str, system: str) -> str:
    """Determine system category from part number and system field"""
    pn = part_number.upper()
    sys_lower = system.lower()
    
    # Check system field first
    if 'video' in sys_lower:
        return 'video'
    if 'audio' in sys_lower:
        return 'audio'
    if 'network' in sys_lower or 'wifi' in sys_lower:
        return 'network'
    if 'control' in sys_lower or 'automation' in sys_lower:
        return 'control'
    if 'lighting' in sys_lower:
        return 'lighting'
    if 'hvac' in sys_lower or 'climate' in sys_lower:
        return 'hvac'
    if 'power' in sys_lower or 'rack' in sys_lower:
        return 'power'
    if 'cctv' in sys_lower or 'security' in sys_lower or 'access' in sys_lower:
        return 'security'
    
    # Check part number patterns
    # Note: PS65, PS80, UB32, WB80 are IP Video Receivers - categorize separately
    if any(x in pn for x in ['PS65', 'PS80', 'UB32', 'WB80']):
        return 'video_rx'  # Separate category for receivers
    if any(x in pn for x in ['QN', 'HDMI', 'VIDEO']):
        return 'video'
    if any(x in pn for x in ['PAV-SI', 'AMP', 'SPEAKER', 'IS8', 'SPL5', 'BIJOU', 'AOM']):
        return 'audio'
    if any(x in pn for x in ['USW', 'UDM', 'E7', 'AP', 'SWITCH']):
        return 'network'
    if any(x in pn for x in ['SSC', 'PKG-MAC', 'HOST', 'REM-']):
        return 'control'
    if any(x in pn for x in ['HQP', 'LUTRON', 'HW-NW']):
        return 'lighting'
    if any(x in pn for x in ['CLI-', 'THERM']):
        return 'hvac'
    if any(x in pn for x in ['WB-', 'UPS', 'PDU', 'OVRC']):
        return 'power'
    
    return 'other'


def get_display_name(part_number: str) -> str:
    """Get a friendly display name for equipment"""
    display_names = {
        'PKG-MACUNLIMITED': 'Savant Host',
        'SSC-0012': 'Controller',
        'PAV-SIPA125SM-10': 'Amp 125W',
        'PAV-AOMBAL8C-10': 'Audio Balun',
        'UDM-PRO-MAX': 'Router',
        'USW-PRO-XG-AGGREGATION': 'Aggregation SW',
        'USW-PRO-XG-24-POE': '24-Port PoE SW',
        'USW-PRO-XG-8-POE': '8-Port PoE SW',
        'E7 CAMPUS': 'Outdoor WiFi AP',
        'E7': 'WiFi AP',
        'HQP7-2': 'Lutron Processor',
        'CLI-8000': 'HVAC Controller',
        'CLI-THFM1': 'Thermostat',
        'WB-OVRC-OLUPS-1500-1': 'UPS',
        'WB-800VPS-IPVM-18': 'PDU',
        'WB-300VB-IP-5': 'Surge Protector',
        'OVRC-300-PRO': 'OvrC Hub',
        'QN65QN90FAFXZA': '65" Samsung TV',
        'QN85QN90FAFXZA': '85" Samsung TV',
        'QN65LS01BAFXZA': '65" Frame TV',
        'PS65': 'IP Video Rx',
        'PS80': 'IP Video Rx',
        'UB32': 'Video Wall Box',
        'WB80': 'Video Wall Box',
        'IS8': 'IS8 Ceiling Spk',
        'SPL5QT-LCR': 'LCR Soundbar',
        'BIJOU 3100': 'Bijou Amp',
        'RZ210BK': 'Landscape Spk',
        'OV210WT': 'Outdoor Spk',
        'REM-4000SG-00': 'Pro Remote',
        'PAV-AIO1C-00': 'Audio I/O',
        'UA-HUB': 'Access Hub',
        'UA-G3-PRO-W': 'Video Doorbell',
        # Lutron keypads (various encoding variations)
        'HW-NW-KP': 'Lutron Keypad',
        'HW�NW-KP': 'Lutron Keypad',  # Handle encoding issue
        'HW NW-KP': 'Lutron Keypad',
        'NW-KP-S2': 'Lutron Keypad',  # Partial match for encoded variants
        'KP-S2-E': 'Lutron Keypad',
    }
    
    # Check for exact or partial matches
    for key, name in display_names.items():
        if key in part_number:
            return name
    
    # Shorten unknown part numbers
    return part_number[:20] if len(part_number) > 20 else part_number


def parse_equipment_csv(csv_path: str) -> Dict[str, LocationBlock]:
    """Parse equipment CSV and group by location"""
    locations: Dict[str, LocationBlock] = {}
    
    # Skip patterns - includes labor placeholders and non-equipment items
    skip_patterns = [
        'CONN-', 'WP-', 'PLATE:', '~PWR', 'DATA-', 'AUDIO-', 'VIDEO-',
        'BRKT:', 'CAT6', 'CAT5', 'RG6', '14/2', '14/4', '16/2', 'LUTRON-GRN',
        'DEVICE -', 'CONTROL -', 'NETWORK ', 'AMP-', 'IP ', 'UI -',
        'SPEAKER SYSTEM', 'CABLE MODEM', 'SPACESAVER', '-ENCL-', 'EBB-',
        '~RCS', '~AXS', 'BR1', 'UACC-', 'PDW-', 'RM-', '~LCB', '~SVR',
        'RCK-', 'SSL-', 'OVX001', 'IS-ENCL', 'BRK.', 'BLUEBERRY',
        'LQSE-', 'PD10', 'PD8', 'HQR-', 'QSPS-', 'QS-WLB', 'IR EMITTER',
        'EQUIPMENT RACK', 'SA-20', 'SENSOR',
        # Labor placeholders (exact matches)
    ]
    
    # Exact match placeholders to skip (these are labor/programming items, not actual equipment)
    placeholder_exact = [
        'TV', 'NETWORK WAP', 'NETWORK SWITCH-MANAGED', 'NETWORK ROUTER [ADVANCED]',
        'IP SMART POWER', 'IP DEVICE', 'INTERFACE - PROCESSOR-LIGHTING',
        'CONTROL - LIGHTING KEYPAD', 'UI - REMOTE - HANDHELD',
        'DEVICE - PROCESSOR-CONTROL', 'DEVICE - MATRIX SWITCHER',
        'DEVICE - IP AV [TX/RX]', 'DEVICE - HOST [5xxx]', 'DEVICE - IP',
        'AMP-MULTI', 'SPEAKER - IN-CEILING',
    ]
    
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    content = None
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    if not content:
        return locations
    
    reader = csv.DictReader(content.splitlines())
    
    for row in reader:
        part_number = row.get('Part Number', '').strip()
        location_path = row.get('LocationPath', '').strip()
        system = row.get('System', '').strip()
        quantity = int(float(row.get('Quantity', 1)))
        
        if not part_number or not location_path:
            continue
        
        # Skip non-equipment items
        if any(p in part_number for p in skip_patterns):
            continue
        
        # Skip exact match placeholders (labor/programming items)
        if part_number in placeholder_exact:
            continue
        
        # Parse location
        level = ''
        room_number = ''
        room_name = location_path
        
        if ':' in location_path:
            parts = location_path.split(':', 1)
            level = parts[0].strip()
            room_part = parts[1].strip()
            match = re.match(r'(\d+)\s*-\s*(.+)', room_part)
            if match:
                room_number = match.group(1)
                room_name = match.group(2).strip()
            else:
                room_name = room_part
        
        # Create location if not exists
        if location_path not in locations:
            is_head_end = any(term in location_path.lower() 
                           for term in ['equipment', 'closet', 'rack', 'mdf'])
            locations[location_path] = LocationBlock(
                name=room_name,
                level=level,
                room_number=room_number,
                is_head_end=is_head_end
            )
        
        loc = locations[location_path]
        
        # Check for IDF switch
        if 'USW-PRO-XG-8-POE' in part_number and not loc.is_head_end:
            loc.has_idf = True
        
        # Categorize and add equipment
        category = categorize_part(part_number, system)
        display_name = get_display_name(part_number)
        
        if category not in loc.equipment:
            loc.equipment[category] = EquipmentBlock(system=category)
        
        # Track count per unique item
        if display_name not in loc.equipment[category].items:
            loc.equipment[category].items[display_name] = 0
        loc.equipment[category].items[display_name] += quantity
    
    return locations


class BlockDiagramGenerator:
    """Generate block diagram PDF"""
    
    def __init__(self, page_size='tabloid'):
        if page_size == 'arch_d':
            self.page_width, self.page_height = landscape(ARCH_D)
        else:
            self.page_width, self.page_height = landscape(TABLOID)
        
        self.margin = 0.5 * inch
        self.content_width = self.page_width - 2 * self.margin
        self.content_height = self.page_height - 2 * self.margin
    
    def draw_rounded_rect(self, c, x, y, width, height, radius, fill_color, stroke_color=None):
        """Draw a rounded rectangle"""
        c.saveState()
        
        path = c.beginPath()
        path.moveTo(x + radius, y)
        path.lineTo(x + width - radius, y)
        path.arcTo(x + width - radius, y, x + width, y + radius, 90)
        path.lineTo(x + width, y + height - radius)
        path.arcTo(x + width - radius, y + height - radius, x + width, y + height, 0)
        path.lineTo(x + radius, y + height)
        path.arcTo(x, y + height - radius, x + radius, y + height, 270)
        path.lineTo(x, y + radius)
        path.arcTo(x, y, x + radius, y + radius, 180)
        path.close()
        
        c.setFillColor(fill_color)
        c.drawPath(path, fill=1, stroke=0)
        
        if stroke_color:
            c.setStrokeColor(stroke_color)
            c.setLineWidth(2)
            c.drawPath(path, fill=0, stroke=1)
        
        c.restoreState()
    
    def draw_system_block(self, c, x, y, width, height, system: str, items: Dict[str, int]):
        """Draw a single system block"""
        color = SYSTEM_COLORS.get(system, SYSTEM_COLORS['other'])
        label = SYSTEM_LABELS.get(system, system.upper())
        
        # Background
        light_color = colors.HexColor('#FFFFFF')
        self.draw_rounded_rect(c, x, y, width, height, 5, light_color, color)
        
        # Header bar
        header_height = 18
        c.setFillColor(color)
        c.rect(x, y + height - header_height, width, header_height, fill=1, stroke=0)
        
        # Header text
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(x + width/2, y + height - 13, label)
        
        # Items
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 7)
        
        item_y = y + height - header_height - 12
        shown = 0
        for item_name, count in list(items.items())[:4]:  # Max 4 items
            if item_y > y + 5:
                if count > 1:
                    display = f"• {item_name} ({count})"
                else:
                    display = f"• {item_name}"
                if len(display) > 25:
                    display = display[:24] + "…"
                c.drawString(x + 5, item_y, display)
                item_y -= 10
                shown += 1
        
        if len(items) > 4:
            c.drawString(x + 5, item_y, f"  +{len(items)-4} more")
    
    def draw_head_end_block(self, c, x, y, width, height, location: LocationBlock, intent: SystemIntent):
        """Draw the main head-end equipment block"""
        # Main container
        c.setFillColor(colors.HexColor('#ECF0F1'))
        c.setStrokeColor(colors.HexColor('#2C3E50'))
        c.setLineWidth(3)
        c.roundRect(x, y, width, height, 10, fill=1, stroke=1)
        
        # Title bar
        title_height = 30
        c.setFillColor(colors.HexColor('#2C3E50'))
        c.rect(x, y + height - title_height, width, title_height, fill=1, stroke=0)
        
        # Title
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 14)
        title = f"{intent.rack_location.upper()}"
        c.drawCentredString(x + width/2, y + height - 20, title)
        
        # Subtitle
        c.setFont("Helvetica", 9)
        subtitle = f"Video: {intent.video_distribution} | Audio: {intent.audio_architecture} | Network: {intent.network_architecture}"
        c.drawCentredString(x + width/2, y + height - title_height - 12, subtitle)
        
        # Draw system blocks inside
        systems = list(location.equipment.keys())
        if not systems:
            return
        
        # Layout: 2 rows of blocks
        block_margin = 10
        inner_width = width - 2 * block_margin
        inner_height = height - title_height - 30
        
        cols = min(4, len(systems))
        rows = (len(systems) + cols - 1) // cols
        
        block_width = (inner_width - (cols - 1) * 8) / cols
        block_height = min(80, (inner_height - (rows - 1) * 8) / rows)
        
        for i, system in enumerate(systems[:8]):  # Max 8 systems
            col = i % cols
            row = i // cols
            
            bx = x + block_margin + col * (block_width + 8)
            by = y + height - title_height - 35 - (row + 1) * (block_height + 8)
            
            block = location.equipment[system]
            self.draw_system_block(c, bx, by, block_width, block_height, 
                                  system, block.items)
    
    def draw_room_block(self, c, x, y, width, height, location: LocationBlock):
        """Draw a room/endpoint block"""
        # Container
        fill_color = colors.HexColor('#FDF2E9') if not location.has_idf else colors.HexColor('#E8F4F8')
        c.setFillColor(fill_color)
        c.setStrokeColor(colors.HexColor('#566573'))
        c.setLineWidth(1.5)
        c.roundRect(x, y, width, height, 8, fill=1, stroke=1)
        
        # Title
        title_height = 20
        c.setFillColor(colors.HexColor('#566573'))
        c.rect(x, y + height - title_height, width, title_height, fill=1, stroke=0)
        
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)
        
        title = location.name[:18]
        if location.room_number:
            title = f"{location.room_number} {title}"[:18]
        c.drawCentredString(x + width/2, y + height - 14, title)
        
        # IDF indicator
        if location.has_idf:
            c.setFillColor(colors.HexColor('#E67E22'))
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x + 3, y + height - title_height - 10, "📡 IDF")
        
        # Equipment summary - show each unique item with its count
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 7)
        
        item_y = y + height - title_height - (20 if location.has_idf else 12)
        items_shown = 0
        max_items = 7  # Maximum items to show per room
        
        for system, block in location.equipment.items():
            color = SYSTEM_COLORS.get(system, SYSTEM_COLORS['other'])
            
            for item_name, count in block.items.items():
                if item_y <= y + 5 or items_shown >= max_items:
                    break
                
                # Color dot
                c.setFillColor(color)
                c.circle(x + 8, item_y + 2, 3, fill=1, stroke=0)
                
                # Text - show count only if > 1
                c.setFillColor(colors.black)
                if count > 1:
                    summary = f"{item_name} ({count})"
                else:
                    summary = item_name
                if len(summary) > 22:
                    summary = summary[:21] + "…"
                c.drawString(x + 15, item_y, summary)
                item_y -= 11
                items_shown += 1
    
    def draw_network_backbone(self, c, x, y, width, height):
        """Draw the network backbone bar"""
        c.setFillColor(colors.HexColor('#E67E22'))
        c.roundRect(x, y, width, height, 5, fill=1, stroke=0)
        
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + width/2, y + height/2 - 4, "IP NETWORK BACKBONE")
    
    def draw_connection_arrow(self, c, x1, y1, x2, y2, color, label=None):
        """Draw a connection arrow"""
        c.setStrokeColor(color)
        c.setLineWidth(2)
        c.line(x1, y1, x2, y2)
        
        # Arrow head
        import math
        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_len = 8
        c.line(x2, y2, 
               x2 - arrow_len * math.cos(angle - 0.4), 
               y2 - arrow_len * math.sin(angle - 0.4))
        c.line(x2, y2, 
               x2 - arrow_len * math.cos(angle + 0.4), 
               y2 - arrow_len * math.sin(angle + 0.4))
    
    def generate(self, intent: SystemIntent, locations: Dict[str, LocationBlock], 
                output_path: str, project_name: str = "AV System"):
        """Generate the block diagram PDF"""
        
        c = canvas.Canvas(output_path, pagesize=(self.page_width, self.page_height))
        
        # Title
        c.setFont("Helvetica-Bold", 18)
        c.drawString(self.margin, self.page_height - 0.4 * inch, project_name)
        c.setFont("Helvetica", 12)
        c.drawString(self.margin, self.page_height - 0.6 * inch, "System Block Diagram")
        
        # Find head-end and rooms
        head_end = None
        rooms = []
        
        for loc_path, location in locations.items():
            if location.is_head_end:
                head_end = location
            elif location.equipment:  # Only rooms with equipment
                rooms.append(location)
        
        if not head_end:
            # Use first location with most equipment as head-end
            head_end = max(locations.values(), key=lambda x: len(x.equipment))
            head_end.is_head_end = True
            rooms = [loc for loc in locations.values() if loc != head_end and loc.equipment]
        
        # Layout calculations
        content_top = self.page_height - 0.8 * inch
        
        # Head-end block (top center)
        head_end_width = min(10 * inch, self.content_width * 0.8)
        head_end_height = 2.2 * inch
        head_end_x = self.margin + (self.content_width - head_end_width) / 2
        head_end_y = content_top - head_end_height - 0.1 * inch
        
        self.draw_head_end_block(c, head_end_x, head_end_y, 
                                head_end_width, head_end_height, head_end, intent)
        
        # Network backbone (middle)
        backbone_height = 0.35 * inch
        backbone_y = head_end_y - backbone_height - 0.4 * inch
        backbone_x = self.margin + 0.5 * inch
        backbone_width = self.content_width - 1 * inch
        
        self.draw_network_backbone(c, backbone_x, backbone_y, backbone_width, backbone_height)
        
        # Connection from head-end to backbone
        self.draw_connection_arrow(c, 
            head_end_x + head_end_width/2, head_end_y,
            head_end_x + head_end_width/2, backbone_y + backbone_height,
            colors.HexColor('#E67E22'))
        
        # Room blocks (bottom rows)
        room_area_top = backbone_y - 0.3 * inch
        room_area_height = room_area_top - self.margin - 0.3 * inch
        
        # Calculate room block sizes
        max_cols = 6
        cols = min(max_cols, len(rooms))
        rows = (len(rooms) + cols - 1) // cols if cols > 0 else 1
        
        room_margin = 0.15 * inch
        room_width = (self.content_width - (cols + 1) * room_margin) / cols if cols > 0 else 2 * inch
        room_height = min(1.8 * inch, (room_area_height - (rows + 1) * room_margin) / rows) if rows > 0 else 1.5 * inch
        
        # First pass: Draw all arrows BEHIND the room blocks
        room_positions = []
        for i, room in enumerate(rooms[:12]):  # Max 12 rooms
            col = i % cols
            row = i // cols
            
            rx = self.margin + room_margin + col * (room_width + room_margin)
            ry = room_area_top - room_height - row * (room_height + room_margin)
            room_positions.append((rx, ry, room))
            
            # Draw connection arrow (behind)
            conn_x = rx + room_width / 2
            self.draw_connection_arrow(c,
                conn_x, backbone_y,
                conn_x, ry + room_height,
                colors.HexColor('#566573'))
        
        # Second pass: Draw all room blocks ON TOP of arrows
        for rx, ry, room in room_positions:
            self.draw_room_block(c, rx, ry, room_width, room_height, room)
        
        # Legend
        legend_x = self.page_width - 2.5 * inch
        legend_y = self.margin + 0.2 * inch
        
        c.setFont("Helvetica-Bold", 8)
        c.drawString(legend_x, legend_y + 1.2 * inch, "SYSTEMS")
        
        c.setFont("Helvetica", 7)
        for i, (system, color) in enumerate(list(SYSTEM_COLORS.items())[:8]):
            ly = legend_y + 1 * inch - i * 12
            c.setFillColor(color)
            c.circle(legend_x + 5, ly + 2, 4, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.drawString(legend_x + 15, ly, SYSTEM_LABELS.get(system, system))
        
        # Footer
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor('#7F8C8D'))
        from datetime import datetime
        c.drawString(self.margin, self.margin - 0.1 * inch, 
                    f"Generated: {datetime.now().strftime('%m/%d/%Y')} | Page Size: 11x17")
        
        c.save()
        return output_path


def generate_block_diagram(
    equipment_csv: str,
    output_path: str,
    project_name: str = "AV System",
    intent_csv: str = None,
    intent: SystemIntent = None,
    page_size: str = 'tabloid'
) -> str:
    """Main function to generate block diagram
    
    Args:
        equipment_csv: Path to equipment CSV file
        output_path: Output PDF path
        project_name: Project name for title
        intent_csv: Optional path to system intent CSV
        intent: Optional SystemIntent object (takes precedence over intent_csv)
        page_size: Page size ('tabloid', 'arch_d', etc.)
    """
    
    print(f"📄 Parsing equipment CSV: {equipment_csv}")
    locations = parse_equipment_csv(equipment_csv)
    print(f"📊 Found {len(locations)} locations")
    
    # Use provided intent, or parse from CSV, or use defaults
    if intent is None:
        intent = SystemIntent()
        if intent_csv:
            print(f"📋 Parsing system intent: {intent_csv}")
            intent = SystemIntent.from_csv(intent_csv)
    
    print(f"   Video: {intent.video_distribution}")
    print(f"   Audio: {intent.audio_architecture}")
    print(f"   Network: {intent.network_architecture}")
    
    # Generate diagram
    print(f"🎨 Generating block diagram...")
    generator = BlockDiagramGenerator(page_size)
    generator.generate(intent, locations, output_path, project_name)
    
    print(f"✅ Generated: {output_path}")
    return output_path


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python block_diagram.py <equipment_csv> [intent_csv] [project_name]")
        print("\nExample:")
        print("  python block_diagram.py 'SI - AVC.csv' 'System Intent.csv' 'Smith Residence'")
        sys.exit(1)
    
    equipment_csv = sys.argv[1]
    intent_csv = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('-') else None
    project_name = sys.argv[3] if len(sys.argv) > 3 else "AV System"
    
    # Check if second arg is actually project name (no intent CSV)
    if intent_csv and not Path(intent_csv).exists():
        project_name = intent_csv
        intent_csv = None
    
    base_name = Path(equipment_csv).stem.replace(' ', '_')
    output_path = f"{base_name}_Block_Diagram.pdf"
    
    generate_block_diagram(equipment_csv, output_path, project_name, intent_csv)


if __name__ == "__main__":
    main()

