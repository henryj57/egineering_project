#!/usr/bin/env python3
"""
Block Diagram Generator - Enhanced Version
Creates detailed system architecture diagrams showing equipment connections
"""

import csv
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, TABLOID
ARCH_D = (24 * 72, 36 * 72)
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


# System colors
SYSTEM_COLORS = {
    'video': colors.HexColor('#3498DB'),        # Blue
    'video_rx': colors.HexColor('#5DADE2'),     # Light blue
    'audio': colors.HexColor('#27AE60'),        # Green
    'network': colors.HexColor('#E67E22'),      # Orange
    'control': colors.HexColor('#9B59B6'),      # Purple
    'lighting': colors.HexColor('#F1C40F'),     # Yellow
    'hvac': colors.HexColor('#1ABC9C'),         # Teal
    'power': colors.HexColor('#E74C3C'),        # Red
    'security': colors.HexColor('#34495E'),     # Dark gray
    'other': colors.HexColor('#95A5A6'),        # Gray
}


@dataclass
class SystemIntent:
    """System architecture intent"""
    rack_topology: str = "Single"
    rack_location: str = "Equipment Closet"
    video_distribution: str = "Centralized"
    audio_architecture: str = "Centralized"
    network_architecture: str = "All Networked"
    control_system: str = "Savant"
    central_controller: bool = True
    
    @classmethod
    def from_csv(cls, csv_path: str) -> 'SystemIntent':
        intent = cls()
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, FileNotFoundError):
                continue
        else:
            return intent
        
        reader = csv.DictReader(content.splitlines())
        for row in reader:
            intent.rack_topology = row.get('Rack_Topology', 'Single')
            intent.rack_location = row.get('Rack_location', 'Equipment Closet')
            intent.video_distribution = row.get('Video_Distribution', 'Centralized')
            intent.audio_architecture = row.get('Audio_Architecture', 'Centralized')
            intent.network_architecture = row.get('Network_Architecture', 'All Networked')
            break
        
        return intent


@dataclass
class Equipment:
    """Individual piece of equipment"""
    part_number: str
    display_name: str
    category: str  # network, video, audio, control, etc.
    location: str
    quantity: int = 1
    
    # Connection info
    connects_to: List[str] = field(default_factory=list)
    connection_type: str = ""  # ethernet, hdmi, speaker, etc.


@dataclass
class NetworkDevice:
    """Network device with port info"""
    name: str
    part_number: str
    device_type: str  # router, aggregation, poe_switch, ap
    location: str
    port_count: int = 0
    connects_to: List[str] = field(default_factory=list)


@dataclass
class RoomEndpoint:
    """Room with its endpoints"""
    name: str
    room_number: str
    level: str
    has_idf: bool = False
    idf_switch: Optional[str] = None
    
    # Equipment in room
    tvs: List[str] = field(default_factory=list)
    video_rx: List[str] = field(default_factory=list)
    speakers: List[Tuple[str, int]] = field(default_factory=list)  # (type, count)
    controllers: List[str] = field(default_factory=list)
    other: List[str] = field(default_factory=list)


def get_display_name(part_number: str) -> str:
    """Get a friendly display name for equipment"""
    display_names = {
        # Network
        'UDM-PRO-MAX': 'UDM Pro Max\n(Router/Controller)',
        'UDM-PRO': 'UDM Pro\n(Router)',
        'USW-PRO-XG-AGGREGATION': 'Aggregation\nSwitch',
        'USW-PRO-XG-24-POE': '24-Port PoE\nSwitch',
        'USW-PRO-XG-8-POE': '8-Port PoE\nSwitch (IDF)',
        'USW-PRO-24-POE': '24-Port PoE\nSwitch',
        'E7 CAMPUS': 'Outdoor\nWiFi AP',
        'E7': 'WiFi AP',
        
        # Video
        'PKG-MACUNLIMITED': 'Savant Host\n(IP Video Server)',
        'PS65': 'IP Video Rx\n(4K/65W PoE)',
        'PS80': 'IP Video Rx\n(4K/80W PoE)',
        'UB32': 'IP Video Rx\n(4K Wall)',
        'WB80': 'IP Video Rx\n(4K Wall)',
        'QN65QN90FAFXZA': '65" Samsung TV',
        'QN85QN90FAFXZA': '85" Samsung TV',
        'QN65LS01BAFXZA': '65" Frame TV',
        
        # Audio
        'PAV-SIPA125SM-10': 'Savant Amp\n125W x10',
        'PAV-AOMBAL8C-10': 'Audio Balun\n8-Ch',
        'SS42PX-24XP2X4F': 'Savant Audio\nSwitch',
        'IS8': 'Ceiling\nSpeaker',
        'RZ210BK': 'Landscape\nSpeaker',
        'OV210WT': 'Outdoor\nSpeaker',
        'SPL5QT-LCR': 'LCR\nSoundbar',
        'BIJOU 3100': 'Local Amp',
        
        # Control
        'SSC-0012': 'Savant\nController',
        'REM-4000SG-00': 'Pro Remote',
        'PAV-AIO1C-00': 'Audio I/O',
        
        # Lighting
        'HQP7-2': 'Lutron\nProcessor',
        'KP-S2': 'Lutron\nKeypad',
        
        # HVAC
        'CLI-8000': 'HVAC\nController',
        'CLI-THFM1': 'Thermostat',
        
        # Power
        'WB-OVRC-OLUPS-1500-1': 'UPS\n1500VA',
        'WB-800VPS-IPVM-18': 'PDU\n18-Outlet',
        'WB-300VB-IP-5': 'Surge\nProtector',
        'OVRC-300-PRO': 'OvrC Hub',
        
        # Security
        'UA-HUB': 'Access Hub',
        'UA-G3-PRO-W': 'Video\nDoorbell',
    }
    
    for key, name in display_names.items():
        if key in part_number:
            return name
    
    return part_number[:12] if len(part_number) > 12 else part_number


def categorize_equipment(part_number: str, system: str = "") -> str:
    """Categorize equipment by type"""
    pn = part_number.upper()
    sys_lower = system.lower()
    
    # Network devices
    if any(x in pn for x in ['UDM', 'USW', 'UAP', 'E7', 'SWITCH', 'ROUTER']):
        if 'UDM' in pn:
            return 'router'
        if 'AGGREGATION' in pn:
            return 'aggregation'
        if 'USW' in pn or 'SWITCH' in pn:
            return 'poe_switch'
        if 'E7' in pn or 'UAP' in pn:
            return 'wifi_ap'
        return 'network'
    
    # Video
    if any(x in pn for x in ['PS65', 'PS80', 'UB32', 'WB80']):
        return 'video_rx'
    if any(x in pn for x in ['QN', 'TV', 'DISPLAY']):
        return 'tv'
    if 'PKG-MAC' in pn or 'HOST' in pn:
        return 'video_server'
    
    # Audio
    if any(x in pn for x in ['PAV-SIPA', 'AMP']):
        return 'amplifier'
    if any(x in pn for x in ['IS8', 'SPEAKER', 'SPL5', 'RZ210', 'OV210']):
        return 'speaker'
    if 'AOM' in pn or 'BALUN' in pn:
        return 'audio_balun'
    if 'SS42' in pn:
        return 'audio_switch'
    
    # Control
    if any(x in pn for x in ['SSC-', 'CONTROLLER']):
        return 'controller'
    if 'REM-' in pn or 'REMOTE' in pn:
        return 'remote'
    if 'AIO' in pn:
        return 'audio_io'
    
    # Power
    if any(x in pn for x in ['UPS', 'PDU', 'WB-', 'OVRC']):
        return 'power'
    
    # Lighting
    if any(x in pn for x in ['HQP', 'LUTRON', 'KP-']):
        return 'lighting'
    
    # HVAC
    if any(x in pn for x in ['CLI-', 'THERM']):
        return 'hvac'
    
    # Security
    if any(x in pn for x in ['UA-', 'DOORBELL', 'CAMERA']):
        return 'security'
    
    return 'other'


def parse_equipment_for_connections(csv_path: str) -> Dict:
    """Parse CSV and extract equipment with connection information"""
    
    # Data structures
    head_end_equipment = defaultdict(list)  # category -> [Equipment]
    network_devices = []  # NetworkDevice list
    rooms = {}  # location -> RoomEndpoint
    
    skip_patterns = [
        'CONN-', 'WP-', 'PLATE:', '~PWR', 'DATA-', 'AUDIO-', 'VIDEO-',
        'BRKT:', 'CAT6', 'CAT5', 'RG6', '14/2', '14/4', '16/2', 'LUTRON-GRN',
        'DEVICE -', 'CONTROL -', 'NETWORK ', 'AMP-', 'IP ', 'UI -',
        'SPEAKER SYSTEM', 'CABLE MODEM', 'SPACESAVER', '-ENCL-', 'EBB-',
        '~RCS', '~AXS', 'BR1', 'UACC-', 'PDW-', 'RM-', '~LCB', '~SVR',
        'RCK-', 'SSL-', 'OVX001', 'IS-ENCL', 'BRK.', 'BLUEBERRY',
        'LQSE-', 'PD10', 'PD8', 'HQR-', 'QSPS-', 'QS-WLB', 'IR EMITTER',
        'EQUIPMENT RACK', 'SA-20', 'SENSOR',
    ]
    
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
        return {'head_end': head_end_equipment, 'network': network_devices, 'rooms': rooms}
    
    reader = csv.DictReader(content.splitlines())
    
    for row in reader:
        part_number = row.get('Part Number', '').strip()
        location_path = row.get('LocationPath', '').strip()
        system = row.get('System', '').strip()
        quantity = int(float(row.get('Quantity', 1)))
        
        if not part_number or not location_path:
            continue
        
        # Skip non-equipment
        if any(p in part_number for p in skip_patterns):
            continue
        if part_number in placeholder_exact:
            continue
        
        category = categorize_equipment(part_number, system)
        display_name = get_display_name(part_number)
        
        # Parse location
        is_head_end = any(term in location_path.lower() 
                        for term in ['equipment', 'closet', 'rack', 'mdf', 'systems:'])
        
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
        
        # Add to appropriate collection
        if is_head_end or category in ['router', 'aggregation', 'video_server', 'amplifier', 
                                        'audio_switch', 'audio_balun', 'power', 'lighting']:
            # Head-end equipment
            if category in ['router', 'aggregation', 'poe_switch']:
                # Network device
                port_count = 24 if '24' in part_number else (8 if '8' in part_number else 4)
                network_devices.append(NetworkDevice(
                    name=display_name.replace('\n', ' '),
                    part_number=part_number,
                    device_type=category,
                    location='head_end',
                    port_count=port_count
                ))
            else:
                equip = Equipment(
                    part_number=part_number,
                    display_name=display_name,
                    category=category,
                    location='head_end',
                    quantity=quantity
                )
                head_end_equipment[category].append(equip)
        else:
            # Room equipment
            if location_path not in rooms:
                rooms[location_path] = RoomEndpoint(
                    name=room_name,
                    room_number=room_number,
                    level=level
                )
            
            room = rooms[location_path]
            
            # Categorize within room
            if category == 'poe_switch':
                room.has_idf = True
                room.idf_switch = display_name.replace('\n', ' ')
                network_devices.append(NetworkDevice(
                    name=display_name.replace('\n', ' '),
                    part_number=part_number,
                    device_type='idf_switch',
                    location=location_path,
                    port_count=8
                ))
            elif category == 'tv':
                for _ in range(quantity):
                    room.tvs.append(display_name.replace('\n', ' '))
            elif category == 'video_rx':
                for _ in range(quantity):
                    room.video_rx.append(display_name.replace('\n', ' '))
            elif category == 'speaker':
                room.speakers.append((display_name.replace('\n', ' '), quantity))
            elif category == 'controller' or category == 'remote':
                room.controllers.append(display_name.replace('\n', ' '))
            elif category == 'wifi_ap':
                network_devices.append(NetworkDevice(
                    name=display_name.replace('\n', ' '),
                    part_number=part_number,
                    device_type='wifi_ap',
                    location=location_path
                ))
            else:
                room.other.append(display_name.replace('\n', ' '))
    
    return {
        'head_end': dict(head_end_equipment),
        'network': network_devices,
        'rooms': rooms
    }


class DetailedBlockDiagramGenerator:
    """Generate detailed block diagram with connections"""
    
    def __init__(self, page_size='tabloid'):
        if page_size == 'arch_d':
            self.page_width, self.page_height = landscape(ARCH_D)
        else:
            self.page_width, self.page_height = landscape(TABLOID)
        
        self.margin = 0.5 * inch
        self.content_width = self.page_width - 2 * self.margin
        self.content_height = self.page_height - 2 * self.margin
    
    def draw_equipment_box(self, c, x, y, width, height, label, color, 
                           sub_label=None, port_count=None):
        """Draw an equipment box with better internal spacing"""
        # Background
        c.setFillColor(colors.white)
        c.setStrokeColor(color)
        c.setLineWidth(2)
        c.roundRect(x, y, width, height, 5, fill=1, stroke=1)
        
        # Color header bar - taller for more padding
        header_h = 18
        c.setFillColor(color)
        c.rect(x, y + height - header_h, width, header_h, fill=1, stroke=0)
        
        # Label - larger font
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        
        # Handle multi-line labels
        lines = label.split('\n')
        c.drawCentredString(x + width/2, y + height - 13, lines[0])
        
        # Sub-label or second line - more space below header
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 7)
        if len(lines) > 1:
            c.drawCentredString(x + width/2, y + height - header_h - 14, lines[1])
        elif sub_label:
            c.drawCentredString(x + width/2, y + height - header_h - 14, sub_label)
        
        # Port count indicator - more padding from bottom
        if port_count:
            c.setFont("Helvetica", 6)
            c.drawCentredString(x + width/2, y + 6, f"{port_count} ports")
    
    def draw_connection_line(self, c, x1, y1, x2, y2, color, style='solid', label=None):
        """Draw a connection line"""
        c.setStrokeColor(color)
        c.setLineWidth(1.5)
        
        if style == 'dashed':
            c.setDash(3, 2)
        else:
            c.setDash()
        
        c.line(x1, y1, x2, y2)
        c.setDash()  # Reset
        
        if label:
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            c.setFillColor(colors.white)
            c.rect(mid_x - 15, mid_y - 5, 30, 10, fill=1, stroke=0)
            c.setFillColor(color)
            c.setFont("Helvetica", 5)
            c.drawCentredString(mid_x, mid_y - 2, label)
    
    def draw_arrow(self, c, x1, y1, x2, y2, color):
        """Draw an arrow"""
        import math
        
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(1.5)
        c.line(x1, y1, x2, y2)
        
        # Arrow head
        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_len = 6
        c.line(x2, y2, 
               x2 - arrow_len * math.cos(angle - 0.4), 
               y2 - arrow_len * math.sin(angle - 0.4))
        c.line(x2, y2, 
               x2 - arrow_len * math.cos(angle + 0.4), 
               y2 - arrow_len * math.sin(angle + 0.4))
    
    def draw_section_header(self, c, x, y, width, text, color):
        """Draw a section header"""
        c.setFillColor(color)
        c.roundRect(x, y, width, 18, 3, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(x + width/2, y + 5, text)
    
    def generate(self, data: Dict, intent: SystemIntent, output_path: str, project_name: str):
        """Generate the detailed block diagram with better spacing"""
        
        c = canvas.Canvas(output_path, pagesize=(self.page_width, self.page_height))
        
        head_end = data['head_end']
        network_devices = data['network']
        rooms = data['rooms']
        
        # Title area
        c.setFont("Helvetica-Bold", 18)
        c.drawString(self.margin, self.page_height - 0.4 * inch, project_name)
        c.setFont("Helvetica", 11)
        c.setFillColor(colors.HexColor('#666666'))
        c.drawString(self.margin, self.page_height - 0.6 * inch, "System Block Diagram - Equipment Connections")
        c.setFillColor(colors.black)
        
        # Define layout zones - spread across the page width
        # Page is 17" wide (tabloid landscape), we have ~16" of usable space
        zone_width = self.content_width / 5  # 5 zones: Network, Video, Audio, Control, Power
        zone_gap = 0.2 * inch
        
        # Equipment section starts below title
        equip_top = self.page_height - 0.85 * inch
        equip_height = 3.0 * inch  # More vertical space for equipment
        
        # Larger boxes for readability
        box_w = 1.0 * inch
        box_h = 0.55 * inch
        vertical_gap = 0.75 * inch  # Space between equipment rows
        
        # Find network devices by type
        router = None
        agg_switch = None
        core_switches = []
        wifi_aps = []
        
        for dev in network_devices:
            if dev.device_type == 'router':
                router = dev
            elif dev.device_type == 'aggregation':
                agg_switch = dev
            elif dev.device_type == 'poe_switch' and dev.location == 'head_end':
                core_switches.append(dev)
            elif dev.device_type == 'wifi_ap':
                wifi_aps.append(dev)
        
        # ============ ZONE 1: NETWORK INFRASTRUCTURE ============
        zone1_x = self.margin
        
        self.draw_section_header(c, zone1_x, equip_top, 
                                zone_width - zone_gap, "NETWORK", 
                                SYSTEM_COLORS['network'])
        
        # Router/Firewall (top of hierarchy)
        equip_y = equip_top - 0.3 * inch - box_h
        router_center_x = zone1_x + 0.05 * inch + box_w/2
        if router:
            self.draw_equipment_box(c, zone1_x + 0.05 * inch, equip_y, box_w, box_h,
                                   "Router/Firewall\n(UDM Pro Max)", SYSTEM_COLORS['network'])
        
        # Aggregation Switch (core - upstream of PoE switches)
        agg_y = equip_y - vertical_gap * 0.9
        agg_center_x = zone1_x + 0.05 * inch + box_w/2
        if agg_switch:
            self.draw_equipment_box(c, zone1_x + 0.05 * inch, agg_y, box_w, box_h,
                                   "Aggregation\nSwitch", SYSTEM_COLORS['network'])
            # Connect router to aggregation
            if router:
                self.draw_connection_line(c, router_center_x, equip_y,
                                         agg_center_x, agg_y + box_h,
                                         SYSTEM_COLORS['network'], label="10G")
        
        # 24-Port PoE Switches - show both explicitly side by side
        poe_y = agg_y - vertical_gap * 0.85
        poe_box_w = box_w * 0.85
        num_poe = min(len(core_switches), 2)
        
        poe_positions = []  # Store positions for connection lines
        for i in range(num_poe):
            poe_x = zone1_x + 0.02 * inch + i * (poe_box_w + 0.06 * inch)
            poe_positions.append(poe_x + poe_box_w/2)
            self.draw_equipment_box(c, poe_x, poe_y, poe_box_w, box_h * 0.85,
                                   f"24-Port PoE\nSwitch ({i+1})", SYSTEM_COLORS['network'])
            # Connect each PoE switch to Aggregation
            if agg_switch:
                self.draw_connection_line(c, poe_x + poe_box_w/2, poe_y + box_h * 0.85,
                                         agg_center_x, agg_y,
                                         SYSTEM_COLORS['network'], label="10G" if i == 0 else "")
        
        # WiFi APs & IDF Switches - endpoints fed by PoE switches
        ap_count = len(wifi_aps)
        endpoint_y = poe_y - vertical_gap * 0.75
        
        if ap_count > 0:
            c.setFillColor(colors.HexColor('#FDF2E9'))
            c.setStrokeColor(SYSTEM_COLORS['network'])
            c.setLineWidth(2)
            c.roundRect(zone1_x + 0.05 * inch, endpoint_y, box_w * 0.9, box_h * 0.7, 5, fill=1, stroke=1)
            c.setFillColor(SYSTEM_COLORS['network'])
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(zone1_x + 0.05 * inch + box_w * 0.45, endpoint_y + box_h * 0.7 - 14, f"WiFi APs")
            c.setFont("Helvetica", 7)
            c.drawCentredString(zone1_x + 0.05 * inch + box_w * 0.45, endpoint_y + 6, f"({ap_count} units)")
            # Connect to PoE switch
            if poe_positions:
                self.draw_connection_line(c, poe_positions[0], poe_y,
                                         zone1_x + 0.05 * inch + box_w * 0.45, endpoint_y + box_h * 0.7,
                                         SYSTEM_COLORS['network'], style='dashed', label="PoE")
        
        # ============ ZONE 2: VIDEO DISTRIBUTION ============
        zone2_x = self.margin + zone_width
        
        self.draw_section_header(c, zone2_x, equip_top,
                                zone_width - zone_gap, "VIDEO", 
                                SYSTEM_COLORS['video'])
        
        # Video server/host (IP Video Transmitter side)
        video_servers = head_end.get('video_server', [])
        server_center_x = zone2_x + 0.05 * inch + box_w/2
        if video_servers:
            self.draw_equipment_box(c, zone2_x + 0.05 * inch, equip_y, box_w, box_h,
                                   "IP Video Server\n(Savant Host)", SYSTEM_COLORS['video'])
        
        # Get rooms with video
        video_rooms = [(name, room) for name, room in rooms.items() if room.video_rx or room.tvs]
        video_rx_count = sum(len(r.video_rx) for r in rooms.values())
        tv_count = sum(len(r.tvs) for r in rooms.values())
        
        if video_rx_count > 0:
            # Show room-specific receivers with their TVs
            rx_y = equip_y - vertical_gap * 0.85
            
            # Draw a container showing "Room Endpoints" with Rx → TV pattern
            container_w = box_w * 1.4
            container_h = box_h * 2.2
            
            c.setFillColor(colors.HexColor('#EBF5FB'))
            c.setStrokeColor(SYSTEM_COLORS['video'])
            c.setLineWidth(2)
            c.roundRect(zone2_x + 0.02 * inch, rx_y - container_h + box_h, container_w, container_h, 6, fill=1, stroke=1)
            
            # Container header
            c.setFillColor(SYSTEM_COLORS['video'])
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(zone2_x + 0.02 * inch + container_w/2, rx_y + box_h - 12, "ROOM ENDPOINTS")
            
            # Show the Rx → TV pattern inside
            inner_y = rx_y + box_h - 30
            
            # IP Video Receiver box (at room)
            c.setFillColor(colors.white)
            c.setStrokeColor(SYSTEM_COLORS['video'])
            c.setLineWidth(1.5)
            c.roundRect(zone2_x + 0.1 * inch, inner_y - 25, box_w * 0.8, 22, 3, fill=1, stroke=1)
            c.setFillColor(SYSTEM_COLORS['video'])
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(zone2_x + 0.1 * inch + box_w * 0.4, inner_y - 18, "Video Rx @ TV")
            c.setFont("Helvetica", 6)
            c.drawCentredString(zone2_x + 0.1 * inch + box_w * 0.4, inner_y - 8, f"({video_rx_count} units)")
            
            # Arrow to TV
            c.setStrokeColor(SYSTEM_COLORS['video'])
            c.setLineWidth(1)
            self.draw_arrow(c, zone2_x + 0.1 * inch + box_w * 0.4, inner_y - 28,
                           zone2_x + 0.1 * inch + box_w * 0.4, inner_y - 45,
                           SYSTEM_COLORS['video'])
            c.setFont("Helvetica", 5)
            c.setFillColor(SYSTEM_COLORS['video'])
            c.drawString(zone2_x + 0.1 * inch + box_w * 0.45, inner_y - 40, "HDMI")
            
            # TV box
            c.setFillColor(colors.HexColor('#E8F6F3'))
            c.setStrokeColor(SYSTEM_COLORS['video'])
            c.setLineWidth(1.5)
            c.roundRect(zone2_x + 0.1 * inch, inner_y - 72, box_w * 0.8, 22, 3, fill=1, stroke=1)
            c.setFillColor(SYSTEM_COLORS['video'])
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(zone2_x + 0.1 * inch + box_w * 0.4, inner_y - 65, "TV / Display")
            c.setFont("Helvetica", 6)
            c.drawCentredString(zone2_x + 0.1 * inch + box_w * 0.4, inner_y - 55, f"({tv_count} total)")
            
            # Connect server to room endpoints container
            if video_servers:
                self.draw_connection_line(c, server_center_x, equip_y,
                               zone2_x + 0.02 * inch + container_w/2, rx_y + box_h,
                               SYSTEM_COLORS['video'], label="IP Video")
        
        # ============ ZONE 3: AUDIO DISTRIBUTION ============
        zone3_x = self.margin + zone_width * 2
        
        self.draw_section_header(c, zone3_x, equip_top,
                                zone_width - zone_gap, "AUDIO", 
                                SYSTEM_COLORS['audio'])
        
        # Amps
        amps = head_end.get('amplifier', [])
        if amps:
            self.draw_equipment_box(c, zone3_x + 0.1 * inch, equip_y, box_w, box_h,
                                   amps[0].display_name, SYSTEM_COLORS['audio'])
        
        # Speaker zones
        total_speakers = sum(sum(qty for _, qty in r.speakers) for r in rooms.values())
        if total_speakers > 0:
            spk_y = equip_y - vertical_gap
            c.setFillColor(colors.HexColor('#E8F8F5'))
            c.setStrokeColor(SYSTEM_COLORS['audio'])
            c.setLineWidth(2)
            c.roundRect(zone3_x + 0.1 * inch, spk_y, box_w, box_h, 5, fill=1, stroke=1)
            c.setFillColor(SYSTEM_COLORS['audio'])
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(zone3_x + 0.1 * inch + box_w/2, spk_y + box_h - 18, "Speaker Zones")
            c.setFont("Helvetica", 8)
            c.drawCentredString(zone3_x + 0.1 * inch + box_w/2, spk_y + 10, f"({total_speakers} speakers)")
            
            if amps:
                self.draw_connection_line(c, zone3_x + 0.1 * inch + box_w/2, equip_y,
                               zone3_x + 0.1 * inch + box_w/2, spk_y + box_h,
                               SYSTEM_COLORS['audio'], label="Speaker")
        
        # ============ ZONE 4: CONTROL & LIGHTING ============
        zone4_x = self.margin + zone_width * 3
        
        self.draw_section_header(c, zone4_x, equip_top,
                                zone_width - zone_gap, "CONTROL", 
                                SYSTEM_COLORS['control'])
        
        controllers = head_end.get('controller', [])
        if controllers:
            self.draw_equipment_box(c, zone4_x + 0.05 * inch, equip_y, box_w, box_h,
                                   controllers[0].display_name, SYSTEM_COLORS['control'])
        
        # Lighting - position below controller
        lighting = head_end.get('lighting', [])
        light_y = equip_y - vertical_gap
        if lighting:
            self.draw_equipment_box(c, zone4_x + 0.05 * inch, light_y, box_w, box_h,
                                   lighting[0].display_name, SYSTEM_COLORS['lighting'])
        
        # ============ ZONE 5: POWER ============
        zone5_x = self.margin + zone_width * 4
        
        self.draw_section_header(c, zone5_x, equip_top,
                                zone_width - zone_gap, "POWER", 
                                SYSTEM_COLORS['power'])
        
        power = head_end.get('power', [])
        if power:
            for i, pwr in enumerate(power[:4]):
                pwr_y = equip_y - i * (box_h + 0.12 * inch)
                self.draw_equipment_box(c, zone5_x + 0.05 * inch, pwr_y, 
                                       box_w, box_h,
                                       pwr.display_name, SYSTEM_COLORS['power'])
        
        # ============ ROOM ENDPOINTS SECTION ============
        room_section_y = self.page_height - equip_height - 1.4 * inch
        
        # Section header bar
        c.setFillColor(colors.HexColor('#566573'))
        c.roundRect(self.margin, room_section_y, self.content_width, 22, 4, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(self.margin + self.content_width/2, room_section_y + 6, 
                           f"ROOM ENDPOINTS  ({len(rooms)} locations)")
        
        # Room boxes - more spread out
        idf_rooms = [r for r in rooms.values() if r.has_idf]
        other_rooms = [r for r in rooms.values() if not r.has_idf]
        all_rooms = idf_rooms + other_rooms
        
        room_box_w = 1.5 * inch
        room_box_h = 1.8 * inch  # Taller for better spacing inside
        
        # Calculate rows needed
        max_cols = 6
        cols = min(max_cols, len(all_rooms))
        rows = (len(all_rooms) + cols - 1) // cols if cols > 0 else 1
        
        room_gap = 0.2 * inch
        total_room_width = cols * room_box_w + (cols - 1) * room_gap
        start_x = self.margin + (self.content_width - total_room_width) / 2
        
        for idx, room in enumerate(all_rooms[:12]):
            col = idx % cols
            row = idx // cols
            
            room_x = start_x + col * (room_box_w + room_gap)
            room_y = room_section_y - 0.3 * inch - (row + 1) * (room_box_h + room_gap * 0.8)
            
            # Room box
            fill = colors.HexColor('#E8F4F8') if room.has_idf else colors.HexColor('#FDF2E9')
            c.setFillColor(fill)
            c.setStrokeColor(colors.HexColor('#566573'))
            c.setLineWidth(1.5)
            c.roundRect(room_x, room_y, room_box_w, room_box_h, 6, fill=1, stroke=1)
            
            # Room title bar
            c.setFillColor(colors.HexColor('#566573'))
            c.rect(room_x, room_y + room_box_h - 20, room_box_w, 20, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 8)
            title = f"{room.room_number} {room.name}" if room.room_number else room.name
            title = title[:20]
            c.drawCentredString(room_x + room_box_w/2, room_y + room_box_h - 14, title)
            
            # Room contents - with better spacing
            c.setFont("Helvetica", 8)
            content_y = room_y + room_box_h - 42
            line_height = 18  # More space between lines
            
            if room.has_idf:
                c.setFillColor(SYSTEM_COLORS['network'])
                c.setFont("Helvetica-Bold", 8)
                c.drawString(room_x + 10, content_y, "📡 IDF Switch")
                content_y -= line_height
                c.setFont("Helvetica", 8)
            
            if room.tvs:
                c.setFillColor(SYSTEM_COLORS['video'])
                c.circle(room_x + 12, content_y + 3, 3, fill=1, stroke=0)
                c.setFillColor(colors.black)
                tv_text = f"TV ({len(room.tvs)})" if len(room.tvs) > 1 else "TV"
                c.drawString(room_x + 20, content_y, tv_text)
                content_y -= line_height
            
            if room.video_rx:
                c.setFillColor(SYSTEM_COLORS['video'])
                c.circle(room_x + 12, content_y + 3, 3, fill=1, stroke=0)
                c.setFillColor(colors.black)
                c.drawString(room_x + 20, content_y, f"Video Rx ({len(room.video_rx)})")
                content_y -= line_height
            
            if room.speakers:
                total_spk = sum(qty for _, qty in room.speakers)
                c.setFillColor(SYSTEM_COLORS['audio'])
                c.circle(room_x + 12, content_y + 3, 3, fill=1, stroke=0)
                c.setFillColor(colors.black)
                c.drawString(room_x + 20, content_y, f"Speakers ({total_spk})")
                content_y -= line_height
            
            if room.controllers:
                c.setFillColor(SYSTEM_COLORS['control'])
                c.circle(room_x + 12, content_y + 3, 3, fill=1, stroke=0)
                c.setFillColor(colors.black)
                c.drawString(room_x + 20, content_y, "Controller")
        
        # ============ LEGEND BOX (In Room Endpoints Section) ============
        legend_width = 1.5 * inch
        legend_height = 2.4 * inch  # Taller to fit all items
        legend_x = self.page_width - self.margin - legend_width - 0.1 * inch
        legend_y = room_y + room_box_h - legend_height  # Align top with room boxes
        
        # Legend box background
        c.setFillColor(colors.HexColor('#F0F3F4'))
        c.setStrokeColor(colors.HexColor('#2C3E50'))
        c.setLineWidth(2)
        c.roundRect(legend_x, legend_y, legend_width, legend_height, 6, fill=1, stroke=1)
        
        # Legend header
        c.setFillColor(colors.HexColor('#2C3E50'))
        c.rect(legend_x, legend_y + legend_height - 24, legend_width, 24, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(legend_x + legend_width/2, legend_y + legend_height - 17, "LEGEND")
        
        # Legend items - larger and more spaced
        c.setFont("Helvetica", 9)
        legend_items = [
            ("Network", SYSTEM_COLORS['network']),
            ("Video", SYSTEM_COLORS['video']),
            ("Audio", SYSTEM_COLORS['audio']),
            ("Control", SYSTEM_COLORS['control']),
            ("Lighting", SYSTEM_COLORS['lighting']),
            ("Power", SYSTEM_COLORS['power']),
        ]
        
        item_start_y = legend_y + legend_height - 48
        line_spacing = 22  # More space between items
        
        for i, (label, color) in enumerate(legend_items):
            ly = item_start_y - i * line_spacing
            c.setFillColor(color)
            c.circle(legend_x + 18, ly + 3, 6, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.drawString(legend_x + 32, ly, label)
        
        # Footer
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor('#7F8C8D'))
        from datetime import datetime
        c.drawString(self.margin, self.margin + 12,
                    f"Generated: {datetime.now().strftime('%m/%d/%Y')} | {intent.video_distribution} Video | {intent.audio_architecture} Audio")
        
        # Disclaimer statement
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(colors.HexColor('#566573'))
        disclaimer = "System Block Diagram – Functional Overview Only. This diagram represents system architecture and relationships, not wiring details, signal flow, or programming intent."
        c.drawString(self.margin, self.margin, disclaimer)
        
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
    """Main function to generate block diagram"""
    
    print(f"📄 Parsing equipment CSV: {equipment_csv}")
    data = parse_equipment_for_connections(equipment_csv)
    print(f"📊 Found {len(data['rooms'])} rooms, {len(data['network'])} network devices")
    
    # Use provided intent, or parse from CSV, or use defaults
    if intent is None:
        intent = SystemIntent()
        if intent_csv:
            print(f"📋 Parsing system intent: {intent_csv}")
            intent = SystemIntent.from_csv(intent_csv)
    
    print(f"   Video: {intent.video_distribution}")
    print(f"   Audio: {intent.audio_architecture}")
    
    # Generate diagram
    print(f"🎨 Generating detailed block diagram...")
    generator = DetailedBlockDiagramGenerator(page_size)
    generator.generate(data, intent, output_path, project_name)
    
    print(f"✅ Generated: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python block_diagram.py <equipment_csv> [intent_csv] [project_name]")
        sys.exit(1)
    
    equipment_csv = sys.argv[1]
    intent_csv = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('-') else None
    project_name = sys.argv[3] if len(sys.argv) > 3 else "AV System"
    
    output_name = Path(equipment_csv).stem.replace(' ', '_') + '_Block_Diagram.pdf'
    
    generate_block_diagram(equipment_csv, output_name, project_name, intent_csv)
