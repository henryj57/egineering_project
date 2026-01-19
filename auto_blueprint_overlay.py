#!/usr/bin/env python3
"""
AUTOMATED BLUEPRINT EQUIPMENT OVERLAY SYSTEM
============================================
Automatically detects room boundaries using computer vision and places
equipment bubbles at the center of each room.

Features:
- OCR detection of room labels
- Flood-fill algorithm to find room boundaries
- Automatic centroid calculation for bubble placement
- Manual override capability for rooms without text labels (e.g., Gym)
- Color-coded device icons (TV, Speaker, Subwoofer)

Usage:
    python auto_blueprint_overlay.py --csv <path_to_csv> --blueprints <floor1.pdf> <floor2.pdf> --output <output.pdf>

Or import and use programmatically:
    from auto_blueprint_overlay import generate_blueprint_overlay
    generate_blueprint_overlay(csv_path, blueprint_paths, output_path, manual_overrides)
"""

import fitz
import cv2
import numpy as np
from PIL import Image, ImageEnhance
import pytesseract
import tempfile
import os
import argparse
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg


# Default icon paths (relative to script location)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")

# Device color coding
DEVICE_COLORS = {
    "TV": colors.HexColor('#9B59B6'),      # Purple
    "SPK": colors.HexColor('#27AE60'),     # Green
    "SUB": colors.HexColor('#E67E22'),     # Orange
    "CAT6": colors.HexColor('#3498DB'),    # Blue
    "WAP": colors.HexColor('#F39C12'),     # Yellow
    "CAM": colors.HexColor('#E74C3C'),     # Red
}


def load_svg_icons(icons_dir=None):
    """Load SVG icons for device types"""
    if icons_dir is None:
        icons_dir = ICONS_DIR
    
    icon_files = {
        "TV": os.path.join(icons_dir, "TV.svg"),
        "SPK": os.path.join(icons_dir, "Speaker.svg"),
        "SUB": os.path.join(icons_dir, "Subwoofer.svg"),
        "CAM": os.path.join(icons_dir, "Camera.svg"),
        "WAP": os.path.join(icons_dir, "WAP.svg"),
    }
    
    svg_icons = {}
    for name, path in icon_files.items():
        if os.path.exists(path):
            drawing = svg2rlg(path)
            if drawing:
                svg_icons[name] = drawing
    
    return svg_icons


def detect_room_centers(pdf_path):
    """
    Detect room centers using OCR + flood fill algorithm.
    
    1. Extract room labels via OCR
    2. Use flood fill from each label position to find room boundaries
    3. Calculate centroid of each room
    
    Returns: dict of room_name -> {'x': float, 'y': float} (relative coordinates 0-1)
    """
    doc = fitz.open(pdf_path)
    page = doc[0]
    zoom = 200 / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    
    temp_img = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    pix.save(temp_img.name)
    
    img = cv2.imread(temp_img.name)
    img_h, img_w = img.shape[:2]
    
    # Convert to binary (walls dark, rooms light)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
    
    # OCR to find room labels
    pil_img = Image.open(temp_img.name)
    enhancer = ImageEnhance.Contrast(pil_img)
    pil_enhanced = enhancer.enhance(2.0)
    
    ocr_data = pytesseract.image_to_data(
        pil_enhanced, 
        output_type=pytesseract.Output.DICT, 
        config='--oem 3 --psm 12'
    )
    
    # Room-related keywords
    room_keywords = [
        "kitchen", "office", "den", "great", "room", "suite", "primary", "junior",
        "bath", "gym", "sunroom", "closet", "bedroom", "guest", "laundry", "entry",
        "jr", "master", "living", "dining", "foyer", "hallway", "garage", "media"
    ]
    
    # Extract raw labels
    raw_labels = []
    for i, text in enumerate(ocr_data['text']):
        text_lower = text.strip().lower()
        conf = ocr_data['conf'][i]
        if conf > 40 and len(text_lower) > 1 and any(kw in text_lower for kw in room_keywords):
            x = ocr_data['left'][i]
            y = ocr_data['top'][i]
            w = ocr_data['width'][i]
            h = ocr_data['height'][i]
            raw_labels.append({
                'text': text.strip().upper(),
                'x': x + w/2,
                'y': y + h/2
            })
    
    # Group nearby labels (combine "PRIMARY" + "SUITE" etc.)
    grouped_labels = []
    used = set()
    for i, label in enumerate(raw_labels):
        if i in used:
            continue
        group_text = label['text']
        group_x, group_y, count = label['x'], label['y'], 1
        
        for j, other in enumerate(raw_labels):
            if j != i and j not in used:
                if abs(other['x'] - label['x']) < 100 and abs(other['y'] - label['y']) < 80:
                    group_text += " " + other['text']
                    group_x += other['x']
                    group_y += other['y']
                    count += 1
                    used.add(j)
        
        grouped_labels.append({
            'text': group_text,
            'x': group_x / count,
            'y': group_y / count
        })
        used.add(i)
    
    # Flood fill to find room boundaries and calculate centers
    room_centers = {}
    for label in grouped_labels:
        seed_x, seed_y = int(label['x']), int(label['y'])
        
        if 0 <= seed_x < img_w and 0 <= seed_y < img_h:
            mask = np.zeros((img_h + 2, img_w + 2), np.uint8)
            flooded = binary.copy()
            cv2.floodFill(flooded, mask, (seed_x, seed_y), 128)
            filled_region = (flooded == 128).astype(np.uint8) * 255
            contours, _ = cv2.findContours(filled_region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                largest = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest) > 1000:
                    M = cv2.moments(largest)
                    if M["m00"] > 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        room_centers[label['text']] = {
                            'x': cx / img_w,
                            'y': cy / img_h
                        }
    
    os.unlink(temp_img.name)
    doc.close()
    return room_centers


def render_pdf_to_image(pdf_path, dpi=150):
    """Render PDF page to image for canvas background"""
    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72.0, dpi/72.0))
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    pix.save(temp_file.name)
    width, height = pix.width, pix.height
    doc.close()
    return temp_file.name, width, height


def draw_equipment_bubble(c, x, y, room_name, devices, svg_icons, scale_factor=0.5):
    """Draw an equipment bubble centered at (x, y)"""
    num_devices = len(devices)
    bubble_w = max(1.8 * inch, num_devices * 0.45 * inch + 0.5 * inch) * scale_factor
    bubble_h = 0.9 * inch * scale_factor
    icon_size = int(20 * scale_factor)
    header_h = 16 * scale_factor
    
    # Center bubble on position
    draw_x = x - bubble_w / 2
    draw_y = y - bubble_h / 2
    
    c.saveState()
    
    # Shadow
    c.setFillColor(colors.HexColor('#00000033'))
    c.roundRect(draw_x + 2, draw_y - 2, bubble_w, bubble_h, 6, fill=1, stroke=0)
    
    # Main bubble
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor('#2C3E50'))
    c.setLineWidth(1.5)
    c.roundRect(draw_x, draw_y, bubble_w, bubble_h, 6, fill=1, stroke=1)
    
    # Header
    c.setFillColor(colors.HexColor('#2C3E50'))
    c.roundRect(draw_x, draw_y + bubble_h - header_h, bubble_w, header_h, 6, fill=1, stroke=0)
    c.rect(draw_x, draw_y + bubble_h - header_h, bubble_w, header_h/2, fill=1, stroke=0)
    
    # Room name
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", max(5, int(8 * scale_factor)))
    display_name = room_name[:20] if len(room_name) > 20 else room_name
    c.drawCentredString(draw_x + bubble_w/2, draw_y + bubble_h - header_h + 2, display_name)
    
    # Device icons
    icon_area_y = draw_y + 4
    icon_spacing = bubble_w / (num_devices + 1)
    icon_x = draw_x + icon_spacing
    
    for device, count in devices.items():
        device_color = DEVICE_COLORS.get(device, colors.gray)
        c.setFillColor(device_color)
        c.circle(icon_x, icon_area_y + 16*scale_factor, 10*scale_factor, fill=1, stroke=0)
        
        if device in svg_icons:
            drawing = svg_icons[device]
            icon_scale = (icon_size * 0.8) / max(drawing.width, drawing.height)
            c.saveState()
            c.translate(icon_x - icon_size*0.4, icon_area_y + 8*scale_factor)
            c.scale(icon_scale, icon_scale)
            renderPDF.draw(drawing, c, 0, 0)
            c.restoreState()
        
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont("Helvetica-Bold", max(5, int(8 * scale_factor)))
        c.drawCentredString(icon_x, icon_area_y, f"×{count}")
        icon_x += icon_spacing
    
    c.restoreState()


def draw_legend(c, page_width, y_position, svg_icons):
    """Draw a prominent legend bar at the bottom of every page"""
    legend_height = 0.4 * inch
    legend_width = 6 * inch
    legend_x = (page_width - legend_width) / 2
    
    # Legend background
    c.setFillColor(colors.HexColor('#F8F9FA'))
    c.setStrokeColor(colors.HexColor('#2C3E50'))
    c.setLineWidth(1)
    c.roundRect(legend_x, y_position, legend_width, legend_height, 4, fill=1, stroke=1)
    
    # Legend title
    c.setFillColor(colors.HexColor('#2C3E50'))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(legend_x + 0.15 * inch, y_position + 0.12 * inch, "LEGEND:")
    
    # Legend items
    items_x = legend_x + 1.0 * inch
    legend_items = [
        ("TV", "TV", colors.HexColor('#9B59B6')),
        ("SPK", "Speaker", colors.HexColor('#27AE60')),
        ("SUB", "Subwoofer", colors.HexColor('#E67E22')),
    ]
    
    for abbrev, desc, color in legend_items:
        # Colored circle
        c.setFillColor(color)
        c.circle(items_x + 8, y_position + 0.2 * inch, 8, fill=1, stroke=0)
        
        # Icon if available
        if abbrev in svg_icons:
            drawing = svg_icons[abbrev]
            icon_scale = 12 / max(drawing.width, drawing.height)
            c.saveState()
            c.translate(items_x + 2, y_position + 0.12 * inch)
            c.scale(icon_scale, icon_scale)
            renderPDF.draw(drawing, c, 0, 0)
            c.restoreState()
        
        # Label
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont("Helvetica", 9)
        c.drawString(items_x + 0.25 * inch, y_position + 0.12 * inch, desc)
        items_x += 1.5 * inch


def match_room_to_equipment(detected_rooms, equipment_config):
    """Match detected room names to equipment configuration"""
    matched = {}
    for detected_name, pos in detected_rooms.items():
        for config_name, config in equipment_config.items():
            if config_name in detected_name or detected_name in config_name:
                matched[detected_name] = {
                    'x': pos['x'],
                    'y': pos['y'],
                    'devices': config['devices']
                }
                break
    return matched


def generate_blueprint_overlay(
    blueprint_configs,
    output_path,
    project_name="Project",
    page_size=(36, 24),
    icons_dir=None
):
    """
    Generate blueprint overlay PDF with equipment bubbles.
    
    Args:
        blueprint_configs: List of dicts, each with:
            - 'pdf_path': Path to blueprint PDF
            - 'title': Floor title (e.g., "GROUND FLOOR")
            - 'equipment': Dict of room_name -> {'devices': {...}}
            - 'manual_overrides': Optional dict for rooms that can't be auto-detected
        output_path: Output PDF path
        project_name: Project name for title
        page_size: Tuple of (width, height) in inches
        icons_dir: Path to icons directory
    """
    svg_icons = load_svg_icons(icons_dir)
    
    page_width = page_size[0] * inch
    page_height = page_size[1] * inch
    
    c = canvas.Canvas(output_path, pagesize=(page_width, page_height))
    
    margin = 0.5 * inch
    title_height = 0.8 * inch
    legend_height = 0.6 * inch  # Space for prominent legend bar
    bp_area_w = page_width - 2 * margin
    bp_area_h = page_height - title_height - legend_height - margin
    
    for config in blueprint_configs:
        floor_pdf = config['pdf_path']
        title = config['title']
        equipment_config = config['equipment']
        manual_overrides = config.get('manual_overrides', {})
        
        print(f"\n--- {title} ---")
        
        # Detect room centers automatically
        detected_rooms = detect_room_centers(floor_pdf)
        matched_rooms = match_room_to_equipment(detected_rooms, equipment_config)
        
        # Add manual overrides
        for room_name, data in manual_overrides.items():
            matched_rooms[room_name] = data
            print(f"  + MANUAL: {room_name}")
        
        print(f"  Total rooms: {len(matched_rooms)}")
        
        # Draw blueprint background
        img_path, img_w, img_h = render_pdf_to_image(floor_pdf, dpi=150)
        scale = min(bp_area_w / img_w, bp_area_h / img_h) * 0.95
        draw_w, draw_h = img_w * scale, img_h * scale
        draw_x = (page_width - draw_w) / 2
        draw_y = legend_height + (bp_area_h - draw_h) / 2
        
        c.drawImage(img_path, draw_x, draw_y, width=draw_w, height=draw_h)
        os.unlink(img_path)
        
        # Title
        c.setFont("Helvetica-Bold", 28)
        c.setFillColor(colors.HexColor('#1E3A5F'))
        c.drawCentredString(
            page_width/2, 
            page_height - title_height + 0.2*inch, 
            f"{project_name} — {title} EQUIPMENT PLAN"
        )
        
        # Draw equipment bubbles at detected centers
        for room_name, data in matched_rooms.items():
            bubble_x = draw_x + data['x'] * draw_w
            bubble_y = draw_y + (1 - data['y']) * draw_h
            draw_equipment_bubble(c, bubble_x, bubble_y, room_name, data['devices'], svg_icons)
            print(f"  ✓ {room_name}")
        
        draw_legend(c, page_width, 0.15 * inch, svg_icons)
        c.showPage()
    
    c.save()
    print(f"\n✅ Output: {output_path}")
    return output_path


# Example usage / CLI
if __name__ == "__main__":
    # Example configuration
    blueprint_configs = [
        {
            'pdf_path': "/Users/henryjohnson/Downloads/GROUND FLOOR_Published.pdf",
            'title': "GROUND FLOOR",
            'equipment': {
                "KITCHEN": {"devices": {"TV": 1, "SPK": 2, "SUB": 1}},
                "OFFICE": {"devices": {"SPK": 2}},
                "GREAT ROOM": {"devices": {"SPK": 4, "SUB": 2}},
                "DEN": {"devices": {"TV": 1, "SPK": 2, "SUB": 1}},
            },
            'manual_overrides': {
                "OFFICE": {"x": 0.751, "y": 0.452, "devices": {"SPK": 2}},
                "DEN": {"x": 0.707, "y": 0.333, "devices": {"TV": 1, "SPK": 2, "SUB": 1}},
            }
        },
        {
            'pdf_path': "/Users/henryjohnson/Downloads/SECOND FLOOR_Published.pdf",
            'title': "SECOND FLOOR",
            'equipment': {
                "JUNIOR SUITE": {"devices": {"TV": 1, "SPK": 2}},
                "JR. SUITE": {"devices": {"TV": 1, "SPK": 2}},
                "PRIMARY SUITE": {"devices": {"TV": 1, "SPK": 2}},
                "SUNROOM": {"devices": {"SPK": 2}},
                "PRIMARY BATH": {"devices": {"SPK": 2}},
                "GYM": {"devices": {"SPK": 2}},
            },
            'manual_overrides': {
                "GYM": {"x": 0.63, "y": 0.17, "devices": {"SPK": 2}},
            }
        },
    ]
    
    output_path = "/Users/henryjohnson/Desktop/PYTHON FILES/SI_AVC_Blueprint_With_Equipment.pdf"
    
    generate_blueprint_overlay(
        blueprint_configs,
        output_path,
        project_name="SI-AVC"
    )

