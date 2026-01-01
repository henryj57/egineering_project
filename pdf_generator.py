"""
PDF Generator Module
Creates professional rack elevation diagrams using ReportLab
"""

import os
from datetime import datetime
from typing import Optional
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, LEDGER, landscape
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Group
from reportlab.graphics import renderPDF

from rack_arranger import RackLayout, RackItem, RackItemType

# Page size options
# TABLOID/LEDGER = 11x17 inches - good for screen viewing
# ARCH_D = 24x36 inches - industry standard for AV drawings  
# ARCH_C = 18x24 inches - medium large format
TABLOID = (11 * inch, 17 * inch)  # 11x17 portrait, will use landscape
ARCH_C = (18 * inch, 24 * inch)   # 18x24 portrait
ARCH_D = (24 * inch, 36 * inch)   # 24x36 portrait

# Default page size for good on-screen viewing
DEFAULT_PAGE_SIZE = landscape(TABLOID)  # 17x11


# Color scheme - professional AV documentation style
COLORS = {
    'rack_frame': colors.Color(0.15, 0.15, 0.15),      # Dark gray frame
    'rack_rail': colors.Color(0.3, 0.3, 0.3),          # Rail color
    'equipment': colors.Color(0.2, 0.2, 0.25),         # Equipment dark
    'equipment_face': colors.Color(0.25, 0.25, 0.3),   # Equipment face
    'vent': colors.Color(0.4, 0.4, 0.4),               # Vent panels
    'blank': colors.Color(0.35, 0.35, 0.35),           # Blank panels
    'text_light': colors.white,
    'text_dark': colors.black,
    'accent': colors.Color(0.2, 0.5, 0.8),             # Blue accent
    'grid': colors.Color(0.85, 0.85, 0.85),            # Light grid lines
    'title_bg': colors.Color(0.1, 0.1, 0.1),           # Title block background
}

# Dimensions (in points, 72 points = 1 inch)
RACK_WIDTH_INCHES = 19
RACK_DEPTH_INCHES = 20
U_HEIGHT_INCHES = 1.75

# Scale will be calculated dynamically to fit the page


class RackElevationPDF:
    """Generates professional rack elevation PDF documents"""
    
    def __init__(
        self,
        output_path: str,
        project_name: str = "AV System",
        company_name: str = "Your Company",
        logo_path: Optional[str] = None,
        revision: str = "A",
        page_size=None  # Default set below
    ):
        if page_size is None:
            page_size = DEFAULT_PAGE_SIZE
        self.output_path = output_path
        self.project_name = project_name
        self.company_name = company_name
        self.logo_path = logo_path
        self.revision = revision
        self.page_size = page_size
        self.page_width, self.page_height = page_size
        
        # Margins
        self.margin = 0.5 * inch
        
    def generate(self, layout: RackLayout) -> str:
        """
        Generate a PDF rack elevation document with a single rack.
        
        Args:
            layout: RackLayout object with positioned items
            
        Returns:
            Path to generated PDF
        """
        return self.generate_multi_page([layout])
    
    def generate_multi_page(self, layouts: list) -> str:
        """
        Generate a PDF with multiple rack layouts (one per page).
        
        Args:
            layouts: List of RackLayout objects
            
        Returns:
            Path to generated PDF
        """
        c = canvas.Canvas(self.output_path, pagesize=self.page_size)
        
        for i, layout in enumerate(layouts):
            # Draw this rack's page
            self._draw_page(c, layout)
            
            # Add new page if not the last layout
            if i < len(layouts) - 1:
                c.showPage()
        
        c.save()
        return self.output_path
    
    def _draw_page(self, c: canvas.Canvas, layout: RackLayout) -> None:
        """Draw a complete page with rack elevation"""
        
        # Calculate available space (landscape 11x8.5)
        title_height = 0.8 * inch
        bottom_margin = 0.4 * inch
        left_margin_for_u_numbers = 0.5 * inch
        legend_width = 3.0 * inch
        
        # Available space for rack
        available_height = self.page_height - self.margin - title_height - bottom_margin - 0.2 * inch
        available_width = self.page_width - self.margin * 2 - left_margin_for_u_numbers - legend_width - 0.5 * inch
        
        # Calculate scale to fit rack on page
        # Real rack dimensions in inches
        rack_real_height_inches = layout.rack_size_u * U_HEIGHT_INCHES  # 42U * 1.75" = 73.5"
        rack_real_width_inches = RACK_WIDTH_INCHES  # 19"
        
        # Calculate scale factors (points per real inch)
        scale_for_height = available_height / rack_real_height_inches
        scale_for_width = available_width / rack_real_width_inches
        
        # Use the smaller scale to fit both dimensions
        self.scale = min(scale_for_height, scale_for_width)
        
        # Calculate rack dimensions in points
        self.u_height_pts = U_HEIGHT_INCHES * self.scale
        self.rack_width_pts = RACK_WIDTH_INCHES * self.scale
        
        rack_height_pts = layout.rack_size_u * self.u_height_pts
        
        # Position rack: left side with room for U numbers, bottom of available space
        rack_x = self.margin + left_margin_for_u_numbers
        rack_y = bottom_margin
        
        # Draw title block (top of page)
        self._draw_title_block(c, layout)
        
        # Draw the rack frame and equipment
        self._draw_rack(c, layout, rack_x, rack_y)
        
        # Draw equipment legend (right side of rack)
        legend_x = rack_x + self.rack_width_pts + 0.4 * inch
        self._draw_legend(c, layout, legend_x, rack_y)
        
        # Draw U numbers on left side of rack
        self._draw_u_numbers(c, layout, rack_x, rack_y)
    
    def _draw_title_block(self, c: canvas.Canvas, layout: RackLayout) -> None:
        """Draw the title block at top of page"""
        
        title_height = 0.8 * inch
        title_y = self.page_height - self.margin - title_height
        title_width = self.page_width - 2 * self.margin
        
        # Background
        c.setFillColor(COLORS['title_bg'])
        c.rect(self.margin, title_y, title_width, title_height, fill=1, stroke=0)
        
        # Company name (left side)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(self.margin + 0.2 * inch, title_y + 0.5 * inch, self.company_name)
        
        # Project name (center)
        c.setFont("Helvetica-Bold", 14)
        project_text = f"Project: {self.project_name}"
        text_width = c.stringWidth(project_text, "Helvetica-Bold", 14)
        c.drawString(self.page_width / 2 - text_width / 2, title_y + 0.5 * inch, project_text)
        
        # Rack info
        c.setFont("Helvetica", 10)
        rack_info = f"{layout.rack_size_u}U Rack  |  Equipment Area"
        c.drawString(self.margin + 0.2 * inch, title_y + 0.2 * inch, rack_info)
        
        # Date and revision (right side)
        c.setFont("Helvetica", 10)
        date_str = datetime.now().strftime("%Y-%m-%d")
        rev_text = f"Rev: {self.revision}  |  Date: {date_str}"
        text_width = c.stringWidth(rev_text, "Helvetica", 10)
        c.drawString(self.page_width - self.margin - text_width - 0.2 * inch, title_y + 0.2 * inch, rev_text)
        
        # Page title
        c.setFont("Helvetica", 10)
        c.drawString(self.page_width - self.margin - 2 * inch, title_y + 0.5 * inch, "RACK ELEVATION - FRONT VIEW")
    
    def _draw_rack(self, c: canvas.Canvas, layout: RackLayout, x: float, y: float) -> None:
        """Draw the rack frame and all equipment"""
        
        rack_height = layout.rack_size_u * self.u_height_pts
        
        # Draw rack frame (outer border)
        c.setStrokeColor(COLORS['rack_frame'])
        c.setLineWidth(2)
        c.setFillColor(colors.Color(0.95, 0.95, 0.95))
        
        # Main rack outline
        frame_padding = 6
        c.rect(
            x - frame_padding,
            y - frame_padding,
            self.rack_width_pts + 2 * frame_padding,
            rack_height + 2 * frame_padding,
            fill=1,
            stroke=1
        )
        
        # Draw rack rails (left and right)
        rail_width = 6
        c.setFillColor(COLORS['rack_rail'])
        c.rect(x, y, rail_width, rack_height, fill=1, stroke=0)
        c.rect(x + self.rack_width_pts - rail_width, y, rail_width, rack_height, fill=1, stroke=0)
        
        # Draw each item
        for item in layout.items:
            item_y = y + (item.position_u - 1) * self.u_height_pts
            item_height = item.rack_units * self.u_height_pts
            
            self._draw_rack_item(c, item, x, item_y, self.rack_width_pts, item_height)
    
    def _draw_rack_item(
        self,
        c: canvas.Canvas,
        item: RackItem,
        x: float,
        y: float,
        width: float,
        height: float
    ) -> None:
        """Draw a single rack item (equipment, vent, or blank)"""
        
        # Inset from rails
        inset = 10
        item_x = x + inset
        item_width = width - 2 * inset
        
        # Choose colors based on item type
        if item.item_type == RackItemType.EQUIPMENT:
            fill_color = COLORS['equipment']
            stroke_color = COLORS['rack_frame']
            text_color = colors.white
        elif item.item_type in (RackItemType.VENT_1U, RackItemType.VENT_2U):
            fill_color = COLORS['vent']
            stroke_color = COLORS['rack_frame']
            text_color = colors.white
        else:  # Blank
            fill_color = COLORS['blank']
            stroke_color = COLORS['rack_frame']
            text_color = colors.white
        
        # Draw item background
        c.setFillColor(fill_color)
        c.setStrokeColor(stroke_color)
        c.setLineWidth(1)
        c.rect(item_x, y + 1, item_width, height - 2, fill=1, stroke=1)
        
        # Draw equipment-specific details
        if item.item_type == RackItemType.EQUIPMENT:
            self._draw_equipment_face(c, item, item_x, y, item_width, height)
        elif item.item_type in (RackItemType.VENT_1U, RackItemType.VENT_2U):
            self._draw_vent_pattern(c, item_x, y, item_width, height)
        
        # Draw label
        c.setFillColor(text_color)
        
        # Scale font size based on item height
        base_font_size = max(5, min(8, int(height / 2.5)))
        
        if item.item_type == RackItemType.EQUIPMENT:
            # Equipment: show brand and model
            c.setFont("Helvetica-Bold", base_font_size)
            label = f"{item.brand} {item.model}".strip()
            max_chars = int(item_width / (base_font_size * 0.5))
            if len(label) > max_chars:
                label = label[:max_chars-3] + "..."
            
            # Center the text
            text_width = c.stringWidth(label, "Helvetica-Bold", base_font_size)
            text_x = item_x + (item_width - text_width) / 2
            text_y = y + height / 2 - base_font_size / 3
            
            c.drawString(text_x, text_y, label)
            
            # Show rack units in corner (if space allows)
            if height >= 10:
                c.setFont("Helvetica", max(4, base_font_size - 2))
                c.drawString(item_x + 3, y + 3, f"{item.rack_units}U")
        else:
            # Vent/blank: simple centered label (only if enough height)
            if height >= 8:
                small_font = max(4, base_font_size - 1)
                c.setFont("Helvetica", small_font)
                label = item.display_name
                text_width = c.stringWidth(label, "Helvetica", small_font)
                text_x = item_x + (item_width - text_width) / 2
                text_y = y + height / 2 - small_font / 3
                c.drawString(text_x, text_y, label)
    
    def _draw_equipment_face(
        self,
        c: canvas.Canvas,
        item: RackItem,
        x: float,
        y: float,
        width: float,
        height: float
    ) -> None:
        """Draw equipment face details (LEDs, buttons, etc.)"""
        
        # Add a subtle gradient effect by drawing overlapping rectangles
        c.setFillColor(COLORS['equipment_face'])
        face_margin = 3
        c.rect(
            x + face_margin,
            y + face_margin + 1,
            width - 2 * face_margin,
            height - 2 * face_margin - 2,
            fill=1,
            stroke=0
        )
        
        # Add some indicator "LEDs" on the left
        if height >= self.u_height_pts:  # Only if at least 1U
            led_x = x + 15
            led_y = y + height - 8
            
            # Power LED (green)
            c.setFillColor(colors.Color(0, 0.8, 0))
            c.circle(led_x, led_y, 2, fill=1, stroke=0)
            
            # Status LED (blue)
            c.setFillColor(colors.Color(0, 0.5, 1))
            c.circle(led_x + 8, led_y, 2, fill=1, stroke=0)
    
    def _draw_vent_pattern(
        self,
        c: canvas.Canvas,
        x: float,
        y: float,
        width: float,
        height: float
    ) -> None:
        """Draw vent hole pattern"""
        
        c.setStrokeColor(colors.Color(0.25, 0.25, 0.25))
        c.setLineWidth(0.5)
        
        # Draw horizontal vent lines
        num_lines = max(2, int(height / 5))
        line_spacing = height / (num_lines + 1)
        
        for i in range(1, num_lines + 1):
            line_y = y + i * line_spacing
            c.line(x + 20, line_y, x + width - 20, line_y)
    
    def _draw_u_numbers(self, c: canvas.Canvas, layout: RackLayout, rack_x: float, rack_y: float) -> None:
        """Draw U numbers along the left side of the rack"""
        
        # Use a small fixed font size
        font_size = 6
        c.setFont("Helvetica", font_size)
        c.setFillColor(COLORS['text_dark'])
        
        # Only show every Nth U number to avoid crowding
        if layout.rack_size_u > 30:
            step = 5  # Show 1, 5, 10, 15...
        elif layout.rack_size_u > 15:
            step = 2  # Show 1, 3, 5, 7...
        else:
            step = 1  # Show all
        
        for u in range(1, layout.rack_size_u + 1, step):
            y_pos = rack_y + (u - 1) * self.u_height_pts + self.u_height_pts / 2 - 2
            c.drawRightString(rack_x - 5, y_pos, f"{u}")
    
    def _draw_legend(self, c: canvas.Canvas, layout: RackLayout, x: float, y: float) -> None:
        """Draw equipment legend on the right side"""
        
        rack_height = layout.rack_size_u * self.u_height_pts
        
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(COLORS['text_dark'])
        c.drawString(x, y + rack_height + 15, "EQUIPMENT LIST")
        
        # List equipment items
        equipment_items = [item for item in layout.items if item.is_equipment]
        current_y = y + rack_height - 5
        
        for i, item in enumerate(equipment_items):
            if current_y < y:  # Stop if we run out of space
                c.setFont("Helvetica", 7)
                c.drawString(x, current_y, f"... and {len(equipment_items) - i} more items")
                break
            
            # Item number and name
            c.setFont("Helvetica-Bold", 8)
            label = f"{i+1}. {item.brand} {item.model}"
            if len(label) > 35:
                label = label[:32] + "..."
            c.drawString(x, current_y, label)
            current_y -= 11
            
            # Details
            c.setFont("Helvetica", 7)
            details = f"   {item.rack_units}U"
            if item.weight:
                details += f" | {item.weight:.1f} lbs"
            if item.btu:
                details += f" | {item.btu:.0f} BTU"
            c.drawString(x, current_y, details)
            current_y -= 13
        
        # Summary section
        current_y -= 15
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, current_y, "SUMMARY")
        current_y -= 12
        
        c.setFont("Helvetica", 8)
        c.drawString(x, current_y, f"Total Equipment: {layout.total_equipment_u}U")
        current_y -= 10
        c.drawString(x, current_y, f"Vents/Blanks: {layout.total_vent_u}U")
        current_y -= 10
        c.drawString(x, current_y, f"Free Space: {layout.remaining_u}U")
        current_y -= 10
        c.drawString(x, current_y, f"Total Weight: {layout.total_weight:.1f} lbs")
        current_y -= 10
        c.drawString(x, current_y, f"Total BTU: {layout.total_btu:.0f}")


def generate_rack_pdf(
    layout: RackLayout,
    output_path: str,
    project_name: str = "AV System",
    company_name: str = "Your Company",
    revision: str = "A",
    page_size: str = "tabloid"
) -> str:
    """
    Convenience function to generate a rack elevation PDF.
    
    Args:
        layout: RackLayout with positioned items (or list of layouts for multi-page)
        output_path: Where to save the PDF
        project_name: Name of the project
        company_name: Company name for title block
        revision: Document revision
        page_size: Page size - "tabloid" (11x17), "arch_c" (18x24), "arch_d" (24x36), "letter"
        
    Returns:
        Path to generated PDF
    """
    # Parse page size
    size_map = {
        'letter': landscape(LETTER),
        'tabloid': landscape(TABLOID),
        'ledger': landscape(TABLOID),  # Same as tabloid
        'arch_c': landscape(ARCH_C),
        'arch_d': landscape(ARCH_D),
    }
    actual_page_size = size_map.get(page_size.lower(), DEFAULT_PAGE_SIZE)
    
    generator = RackElevationPDF(
        output_path=output_path,
        project_name=project_name,
        company_name=company_name,
        revision=revision,
        page_size=actual_page_size
    )
    
    # Handle single layout or list of layouts
    if isinstance(layout, list):
        return generator.generate_multi_page(layout)
    else:
        return generator.generate(layout)


if __name__ == "__main__":
    # Test PDF generation with sample data
    from rack_arranger import RackItem, RackItemType, arrange_rack
    
    sample_equipment = [
        RackItem(RackItemType.EQUIPMENT, "Savant Host", "Savant", "SVR-5200S-00", 2, weight=15.0, btu=200),
        RackItem(RackItemType.EQUIPMENT, "WattBox Power", "WattBox", "WB-800-IPVM-12", 2, weight=12.0, btu=50),
        RackItem(RackItemType.EQUIPMENT, "Marantz AVR", "Marantz", "SR6015", 3, weight=25.0, btu=400),
        RackItem(RackItemType.EQUIPMENT, "Network Switch", "Araknis", "AN-110-SW-R-24", 1, weight=5.0, btu=30),
        RackItem(RackItemType.EQUIPMENT, "Subwoofer Amp", "B&K", "SA250 MK2", 2, weight=20.0, btu=800),
        RackItem(RackItemType.EQUIPMENT, "MOTU Switch", "MOTU", "AVB SWITCH", 1, weight=3.0, btu=20),
    ]
    
    layout = arrange_rack(sample_equipment, rack_size_u=42)
    
    output = "/Users/henryjohnson/Desktop/PYTHON FILES/test_rack_elevation.pdf"
    generate_rack_pdf(layout, output, project_name="Test Project", company_name="BlueDog Group")
    
    print(f"✅ Generated test PDF: {output}")

