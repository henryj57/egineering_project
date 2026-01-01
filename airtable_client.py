"""
Airtable Client Module - "The Brain"
Fetches product data from the Equipment Catalog table using pyairtable
"""

import os
from typing import Optional, Dict, List, Any
from pathlib import Path
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

# Try to import pyairtable
try:
    from pyairtable import Api, Table
    PYAIRTABLE_AVAILABLE = True
except ImportError:
    PYAIRTABLE_AVAILABLE = False
    print("⚠️  pyairtable not installed. Run: pip3 install pyairtable")


class AirtableBrain:
    """
    Client for interacting with the Airtable Equipment Catalog ("The Brain").
    
    Uses pyairtable library for reliable API access.
    """
    
    def __init__(self):
        if not PYAIRTABLE_AVAILABLE:
            raise ImportError("pyairtable is required. Install with: pip3 install pyairtable")
        
        # Load credentials from .env
        self.api_key = os.getenv("AIRTABLE_API_KEY") or os.getenv("AIRTABLE_PAT")
        self.base_id = os.getenv("AIRTABLE_BASE_ID", "appUhE8Eg7AY7KBMX")
        self.table_name = os.getenv("AIRTABLE_TABLE_NAME", "Product Catalog")
        
        if not self.api_key:
            raise ValueError(
                "AIRTABLE_API_KEY not found in .env file.\n"
                "Add this to your .env file:\n"
                "  AIRTABLE_API_KEY=pat_your_token_here\n"
                "  AIRTABLE_BASE_ID=appUhE8Eg7AY7KBMX"
            )
        
        # Initialize pyairtable
        self.api = Api(self.api_key)
        self.table = self.api.table(self.base_id, self.table_name)
        
        # Cache for product lookups
        self._product_cache: Dict[str, Dict] = {}
        self._cache_loaded = False
    
    def _load_all_products(self) -> None:
        """Load all products from Airtable into cache"""
        if self._cache_loaded:
            return
        
        print("🧠 Loading Equipment Catalog from Airtable Brain...")
        
        try:
            all_records = self.table.all()
            
            # Build cache indexed by multiple keys for flexible lookup
            for record in all_records:
                fields = record.get('fields', {})
                
                # Extract product identifiers
                model = fields.get('Model', '').strip().lower()
                model_number = fields.get('Model Number', '').strip().lower()
                part_number = fields.get('Part Number', '').strip().lower()
                name = fields.get('Name', '').strip().lower()
                brand = fields.get('Brand', '').strip().lower()
                
                # Extract specs - support multiple field name variations
                height_u = self._get_height_u(fields)
                watts = self._get_watts(fields)
                btu = self._get_btu(fields, watts)
                weight = self._get_weight(fields)
                subsystem = self._get_subsystem(fields)
                
                product_data = {
                    'record_id': record.get('id'),
                    'name': fields.get('Name', ''),
                    'brand': fields.get('Brand', ''),
                    'model': fields.get('Model', '') or fields.get('Model Number', ''),
                    'part_number': fields.get('Part Number', ''),
                    'rack_units': height_u,
                    'height_u': height_u,
                    'watts': watts,
                    'btu': btu,
                    'weight': weight,
                    'subsystem': subsystem,  # 'AV' or 'Network' or 'Power' etc.
                    'is_rack_mountable': height_u is not None and height_u > 0,
                    'category': fields.get('Category', '') or fields.get('Type', ''),
                    'connections': fields.get('Connections', {}),
                    'front_image': self._get_image_url(fields.get('Front Image')),
                    'source': 'airtable'
                }
                
                # Index by multiple keys for flexible lookup
                for key in [model, model_number, part_number, name]:
                    if key:
                        self._product_cache[key] = product_data
                
                # Also index by brand + model
                if brand and model:
                    self._product_cache[f"{brand} {model}"] = product_data
            
            self._cache_loaded = True
            print(f"✅ Loaded {len(all_records)} products from Brain")
            
        except Exception as e:
            print(f"❌ Error loading from Airtable: {e}")
            raise
    
    def _get_height_u(self, fields: dict) -> Optional[int]:
        """Extract Height (U) from various possible field names"""
        for field_name in ['Height (U)', 'Rack Units', 'RU', 'U Height', 'Height', 'Size (U)']:
            value = fields.get(field_name)
            if value is not None:
                try:
                    return int(float(value))
                except (ValueError, TypeError):
                    continue
        return None
    
    def _get_watts(self, fields: dict) -> Optional[float]:
        """Extract Watts from various possible field names"""
        for field_name in ['Watts', 'Power (W)', 'Power', 'Wattage', 'Power Consumption']:
            value = fields.get(field_name)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        return None
    
    def _get_btu(self, fields: dict, watts: Optional[float] = None) -> Optional[float]:
        """Extract BTU or calculate from Watts"""
        for field_name in ['BTU', 'BTU/hr', 'Heat Output', 'Thermal']:
            value = fields.get(field_name)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        
        # Calculate BTU from Watts if available (1 Watt ≈ 3.41 BTU/hr)
        if watts:
            return watts * 3.41
        
        return None
    
    def _get_weight(self, fields: dict) -> Optional[float]:
        """Extract Weight from various possible field names"""
        for field_name in ['Weight', 'Weight (lbs)', 'Weight (lb)', 'Mass']:
            value = fields.get(field_name)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        return None
    
    def _get_subsystem(self, fields: dict) -> str:
        """
        Extract Subsystem (AV vs Network) from various possible field names.
        Returns 'AV', 'Network', or '' if not specified.
        """
        for field_name in ['Subsystem', 'System', 'Category', 'Type', 'Department']:
            value = fields.get(field_name)
            if value:
                value_lower = str(value).lower()
                
                # Network keywords
                if any(kw in value_lower for kw in ['network', 'net', 'switch', 'router', 'wifi', 'lan']):
                    return 'Network'
                
                # AV keywords
                if any(kw in value_lower for kw in ['av', 'audio', 'video', 'control', 'lighting', 'savant', 'lutron']):
                    return 'AV'
                
                # Return the raw value if no match
                return str(value)
        
        return ''
    
    def _get_image_url(self, attachments: Any) -> Optional[str]:
        """Extract image URL from Airtable attachment field"""
        if not attachments or not isinstance(attachments, list):
            return None
        if len(attachments) > 0 and isinstance(attachments[0], dict):
            return attachments[0].get('url')
        return None
    
    def lookup_by_model(self, model_number: str) -> Optional[Dict]:
        """
        Look up a product by Model Number from the Brain.
        
        Args:
            model_number: The model/part number to search for
            
        Returns:
            Product data dict or None if not found
        """
        self._load_all_products()
        
        # Clean up the search term
        search_key = model_number.strip().lower()
        
        # Direct lookup
        if search_key in self._product_cache:
            return self._product_cache[search_key]
        
        # Fuzzy match - check if model is contained in any cached key
        for cached_key, data in self._product_cache.items():
            if search_key in cached_key or cached_key in search_key:
                return data
        
        return None
    
    def get_rack_specs(self, model_number: str) -> Optional[Dict]:
        """
        Get rack-relevant specs for a product.
        
        Returns:
            Dict with rack_units, weight, btu, watts, subsystem
            or None if not found in Brain
        """
        product = self.lookup_by_model(model_number)
        
        if not product:
            return None
        
        # Must have rack units to be included
        if not product.get('rack_units') or product.get('rack_units', 0) == 0:
            return None
        
        return {
            'rack_units': product.get('rack_units', 1),
            'height_u': product.get('height_u', 1),
            'weight': product.get('weight', 10.0),
            'watts': product.get('watts', 0),
            'btu': product.get('btu', 0),
            'subsystem': product.get('subsystem', ''),
            'is_rack_mountable': True,
            'brand': product.get('brand', ''),
            'model': product.get('model', ''),
            'connections': product.get('connections', {}),
            'source': 'airtable'
        }
    
    def get_all_products(self) -> List[Dict]:
        """Get all products from the catalog"""
        self._load_all_products()
        
        # Return unique products (deduplicated by record_id)
        seen_ids = set()
        unique_products = []
        
        for product in self._product_cache.values():
            record_id = product.get('record_id')
            if record_id and record_id not in seen_ids:
                seen_ids.add(record_id)
                unique_products.append(product)
        
        return unique_products


# Singleton instance
_brain: Optional[AirtableBrain] = None


def get_airtable_client() -> AirtableBrain:
    """Get or create the Airtable Brain singleton"""
    global _brain
    if _brain is None:
        _brain = AirtableBrain()
    return _brain


# Alias for clarity
def get_brain() -> AirtableBrain:
    """Get the Airtable Brain (Equipment Catalog)"""
    return get_airtable_client()


if __name__ == "__main__":
    # Test the Airtable connection
    print("🔌 Testing connection to Airtable Brain...")
    print("=" * 50)
    
    try:
        brain = get_brain()
        products = brain.get_all_products()
        
        print(f"\n📦 Found {len(products)} products in Equipment Catalog:\n")
        
        # Show first 10 products with specs
        for p in products[:10]:
            print(f"  • {p.get('brand', 'N/A')} {p.get('model', 'N/A')}")
            print(f"    Height: {p.get('rack_units', 'N/A')}U | Watts: {p.get('watts', 'N/A')}W | Subsystem: {p.get('subsystem', 'N/A')}")
            print()
        
        if len(products) > 10:
            print(f"  ... and {len(products) - 10} more products")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure your .env file has:")
        print("  AIRTABLE_API_KEY=pat_your_token_here")
        print("  AIRTABLE_BASE_ID=appYourBaseId")
