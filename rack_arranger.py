"""
Rack Arranger Module
Sorts equipment by weight and distributes vents for cooling and aesthetics
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class RackItemType(Enum):
    EQUIPMENT = "equipment"
    VENT_1U = "vent_1u"
    VENT_2U = "vent_2u"
    BLANK_1U = "blank_1u"


@dataclass
class RackItem:
    """Represents an item in the rack (equipment or vent/blank)"""
    item_type: RackItemType
    name: str
    brand: str = ""
    model: str = ""
    rack_units: int = 1
    weight: float = 0.0
    btu: float = 0.0
    position_u: int = 0  # Position in rack (1 = bottom)
    front_image_url: Optional[str] = None
    connections: Optional[dict] = None
    quantity: int = 1
    subsystem: str = ""  # 'AV' or 'Network' from Airtable Brain
    
    @property
    def is_equipment(self) -> bool:
        return self.item_type == RackItemType.EQUIPMENT
    
    @property
    def display_name(self) -> str:
        if self.item_type == RackItemType.EQUIPMENT:
            return f"{self.brand} {self.model}".strip() or self.name
        elif self.item_type == RackItemType.VENT_1U:
            return "1U Vent Panel"
        elif self.item_type == RackItemType.VENT_2U:
            return "2U Vent Panel"
        else:
            return "1U Blank Panel"


@dataclass
class RackLayout:
    """Represents the complete rack layout"""
    rack_size_u: int
    items: List[RackItem] = field(default_factory=list)
    project_name: str = ""
    
    @property
    def total_equipment_u(self) -> int:
        return sum(item.rack_units for item in self.items if item.is_equipment)
    
    @property
    def total_vent_u(self) -> int:
        return sum(item.rack_units for item in self.items if not item.is_equipment)
    
    @property
    def total_used_u(self) -> int:
        return sum(item.rack_units for item in self.items)
    
    @property
    def remaining_u(self) -> int:
        return self.rack_size_u - self.total_used_u
    
    @property
    def total_btu(self) -> float:
        return sum(item.btu for item in self.items)
    
    @property
    def total_weight(self) -> float:
        return sum(item.weight for item in self.items)


def create_vent(units: int = 1) -> RackItem:
    """Create a vent panel"""
    if units == 2:
        return RackItem(
            item_type=RackItemType.VENT_2U,
            name="2U Vent Panel",
            rack_units=2,
            weight=0.5
        )
    return RackItem(
        item_type=RackItemType.VENT_1U,
        name="1U Vent Panel",
        rack_units=1,
        weight=0.25
    )


def create_blank(units: int = 1) -> RackItem:
    """Create a blank panel"""
    return RackItem(
        item_type=RackItemType.BLANK_1U,
        name=f"{units}U Blank Panel",
        rack_units=units,
        weight=0.25 * units
    )


def arrange_rack(
    equipment: List[RackItem],
    rack_size_u: int = 42,
    min_vent_spacing: int = 8,  # Add vent every N units of equipment
    top_buffer_u: int = 1,      # Leave space at top (reduced for more vent room)
    bottom_buffer_u: int = 1    # Leave space at bottom
) -> RackLayout:
    """
    Arrange equipment in a rack with optimal placement.
    
    Strategy:
    1. Sort equipment by weight (heaviest at bottom)
    2. Distribute vents evenly throughout for cooling and aesthetics
    3. Leave buffer space at top and bottom
    
    Args:
        equipment: List of RackItems to place
        rack_size_u: Total rack units available (default 42U)
        min_vent_spacing: Add vent after this many U of equipment
        top_buffer_u: Units to leave empty at top
        bottom_buffer_u: Units to leave empty at bottom
    
    Returns:
        RackLayout with positioned items
    """
    layout = RackLayout(rack_size_u=rack_size_u)
    
    if not equipment:
        return layout
    
    # Sort by weight descending (heaviest first = bottom of rack)
    sorted_equipment = sorted(
        equipment,
        key=lambda x: (x.weight or 0),
        reverse=True
    )
    
    # Calculate available space
    available_u = rack_size_u - top_buffer_u - bottom_buffer_u
    total_equipment_u = sum(item.rack_units for item in sorted_equipment)
    
    # Check if equipment fits
    if total_equipment_u > available_u:
        print(f"⚠️  Warning: Equipment ({total_equipment_u}U) exceeds available space ({available_u}U)")
        print("    Some items may not fit in the rack.")
    
    # Calculate how many spacers (vents/blanks) we need
    remaining_space = available_u - total_equipment_u
    num_equipment_items = len(sorted_equipment)
    
    if remaining_space <= 0 or num_equipment_items == 0:
        # No space for spacers, just add equipment
        final_items = []
        current_position = bottom_buffer_u + 1
        for item in sorted_equipment:
            item.position_u = current_position
            final_items.append(item)
            current_position += item.rack_units
        layout.items = final_items
        return layout
    
    # Strategy: Distribute spacers evenly throughout the rack for a professional look
    # AV integrators: vents between hot equipment, blanks distributed evenly
    
    final_items = []
    
    # Calculate spacing strategy based on fill ratio
    fill_ratio = total_equipment_u / available_u
    
    if fill_ratio >= 0.85:
        # Rack is very full - just add vents between hot items
        final_items = arrange_tight_rack(sorted_equipment, remaining_space, bottom_buffer_u)
    elif fill_ratio >= 0.5:
        # Moderate fill - add 1U vent between each item
        final_items = arrange_moderate_rack(sorted_equipment, remaining_space, bottom_buffer_u, rack_size_u)
    else:
        # Sparse rack - distribute equipment and blanks evenly for professional look
        final_items = arrange_sparse_rack(sorted_equipment, remaining_space, bottom_buffer_u, rack_size_u, available_u)
    
    layout.items = final_items
    
    return layout


def arrange_tight_rack(equipment, remaining_space, bottom_buffer_u):
    """
    Arrange a tightly packed rack - add vents between equipment for cooling.
    Professional look: group similar items, vent after every 2-3 items minimum.
    """
    final_items = []
    current_position = bottom_buffer_u + 1
    
    # For tight racks, we need to be strategic about vent placement
    # Add a vent after every 2-3 pieces of equipment, prioritizing after hot items
    num_items = len(equipment)
    
    # Calculate ideal vent placement - at least every 3 items
    vent_interval = 3  # Add vent after every N items
    min_vents_needed = max(1, (num_items - 1) // vent_interval)
    
    # Use available space for vents, but add at least min_vents_needed
    vents_to_add = max(remaining_space, min_vents_needed)
    
    # Determine which positions get vents (prioritize after high-BTU items)
    vent_positions = set()
    
    # First, mark positions after high-BTU items
    for i, item in enumerate(equipment[:-1]):  # Skip last item
        if (item.btu or 0) > 200:
            vent_positions.add(i)
    
    # Then fill in remaining vents at regular intervals
    items_since_vent = 0
    for i in range(num_items - 1):
        items_since_vent += 1
        if items_since_vent >= vent_interval and i not in vent_positions:
            if len(vent_positions) < vents_to_add:
                vent_positions.add(i)
                items_since_vent = 0
        if i in vent_positions:
            items_since_vent = 0
    
    # Build the rack
    for i, item in enumerate(equipment):
        item.position_u = current_position
        final_items.append(item)
        current_position += item.rack_units
        
        # Add vent after this item if marked
        if i in vent_positions:
            vent = create_vent(1)
            vent.position_u = current_position
            final_items.append(vent)
            current_position += 1
    
    return final_items


def arrange_moderate_rack(equipment, remaining_space, bottom_buffer_u, rack_size_u):
    """Arrange a moderately filled rack - vent between each item, blanks at top"""
    final_items = []
    current_position = bottom_buffer_u + 1
    num_items = len(equipment)
    
    # One vent between each pair of equipment items
    vents_needed = num_items - 1 if num_items > 1 else 0
    vents_to_use = min(vents_needed, remaining_space)
    blanks_for_top = remaining_space - vents_to_use
    
    for i, item in enumerate(equipment):
        item.position_u = current_position
        final_items.append(item)
        current_position += item.rack_units
        
        # Add vent after each item (except last)
        if i < num_items - 1 and vents_to_use > 0:
            vent = create_vent(1)
            vent.position_u = current_position
            final_items.append(vent)
            current_position += 1
            vents_to_use -= 1
    
    # Fill top with blanks
    while blanks_for_top > 0:
        blank = create_blank(1)
        blank.position_u = current_position
        final_items.append(blank)
        current_position += 1
        blanks_for_top -= 1
    
    return final_items


def arrange_sparse_rack(equipment, remaining_space, bottom_buffer_u, rack_size_u, available_u):
    """
    Arrange a sparsely filled rack - distribute equipment evenly throughout
    with blanks filling gaps for a professional, balanced look.
    
    This is what a professional AV integrator would do:
    - Equipment spread throughout the rack (not all at bottom)
    - Vents near hot equipment
    - Blanks filling empty spaces evenly
    """
    final_items = []
    num_items = len(equipment)
    total_equipment_u = sum(item.rack_units for item in equipment)
    
    if num_items == 0:
        return final_items
    
    # Calculate ideal spacing: spread equipment evenly through rack
    # Put heavy/hot items lower, lighter items higher, with gaps between
    
    # Divide rack into zones - equipment goes at bottom of each zone
    # This creates an even distribution throughout the rack
    
    # Calculate how many U each "slot" (equipment + spacer) should ideally be
    total_slots = num_items
    space_per_slot = available_u / total_slots
    
    current_position = bottom_buffer_u + 1
    
    for i, item in enumerate(equipment):
        # Calculate where this item should ideally start
        ideal_start = bottom_buffer_u + 1 + int(i * space_per_slot)
        
        # Add blanks/vents to reach ideal position
        while current_position < ideal_start:
            # Use vents near equipment, blanks for larger gaps
            if ideal_start - current_position <= 2:
                spacer = create_vent(1)
            else:
                spacer = create_blank(1)
            spacer.position_u = current_position
            final_items.append(spacer)
            current_position += 1
        
        # Add the equipment
        item.position_u = current_position
        final_items.append(item)
        current_position += item.rack_units
        
        # Add a vent after equipment if it generates heat
        if i < num_items - 1 and (item.btu or 0) > 100:
            if current_position < rack_size_u:
                vent = create_vent(1)
                vent.position_u = current_position
                final_items.append(vent)
                current_position += 1
    
    # Fill remaining space at top with blanks
    while current_position <= rack_size_u:
        blank = create_blank(1)
        blank.position_u = current_position
        final_items.append(blank)
        current_position += 1
    
    return final_items


def expand_quantities(equipment: List[RackItem]) -> List[RackItem]:
    """
    Expand equipment with quantity > 1 into separate items.
    Each item gets its own rack slot.
    """
    expanded = []
    for item in equipment:
        qty = item.quantity or 1
        for i in range(qty):
            # Create a copy for each quantity
            new_item = RackItem(
                item_type=item.item_type,
                name=item.name,
                brand=item.brand,
                model=item.model,
                rack_units=item.rack_units,
                weight=item.weight,
                btu=item.btu,
                front_image_url=item.front_image_url,
                connections=item.connections,
                quantity=1  # Each expanded item has qty 1
            )
            expanded.append(new_item)
    return expanded


def print_rack_layout(layout: RackLayout) -> None:
    """Print a text representation of the rack layout"""
    print(f"\n{'='*60}")
    print(f"RACK LAYOUT - {layout.rack_size_u}U Rack")
    print(f"{'='*60}")
    print(f"Equipment: {layout.total_equipment_u}U | Vents/Blanks: {layout.total_vent_u}U | Free: {layout.remaining_u}U")
    print(f"Total Weight: {layout.total_weight:.1f} lbs | Total BTU: {layout.total_btu:.0f}")
    print(f"{'='*60}\n")
    
    # Print from top to bottom (highest U first)
    sorted_items = sorted(layout.items, key=lambda x: x.position_u, reverse=True)
    
    for item in sorted_items:
        pos = int(item.position_u)
        units = int(item.rack_units)
        u_range = f"U{pos:02d}"
        if units > 1:
            u_range = f"U{pos:02d}-{pos + units - 1:02d}"
        
        item_type = "📦" if item.is_equipment else "🌬️"
        weight_str = f"{item.weight:.1f}lb" if item.weight else ""
        btu_str = f"{item.btu:.0f}BTU" if item.btu else ""
        
        print(f"  {u_range:10} │ {item_type} {item.display_name:35} │ {weight_str:8} {btu_str}")
    
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    # Test the rack arranger with sample data
    sample_equipment = [
        RackItem(RackItemType.EQUIPMENT, "Savant Host", "Savant", "SVR-5200S-00", 2, weight=15.0, btu=200),
        RackItem(RackItemType.EQUIPMENT, "WattBox Power", "WattBox", "WB-800-IPVM-12", 2, weight=12.0, btu=50),
        RackItem(RackItemType.EQUIPMENT, "Marantz AVR", "Marantz", "SR6015", 3, weight=25.0, btu=400),
        RackItem(RackItemType.EQUIPMENT, "Network Switch", "Araknis", "AN-110-SW-R-24", 1, weight=5.0, btu=30),
        RackItem(RackItemType.EQUIPMENT, "Subwoofer Amp", "B&K", "SA250 MK2", 2, weight=20.0, btu=800),
        RackItem(RackItemType.EQUIPMENT, "MOTU Switch", "MOTU", "AVB SWITCH", 1, weight=3.0, btu=20),
    ]
    
    layout = arrange_rack(sample_equipment, rack_size_u=42)
    print_rack_layout(layout)

