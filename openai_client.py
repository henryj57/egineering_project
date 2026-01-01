"""
OpenAI Client Module
Uses GPT-4 to infer product specifications for AV equipment
Includes persistent caching to avoid redundant API calls
"""

import os
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env from current directory and parent (Desktop)
load_dotenv()
load_dotenv(Path(__file__).parent.parent / ".env")  # Also check Desktop/.env

# Try to import openai
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️  OpenAI package not installed. Run: pip3 install openai")

# Cache file location
CACHE_FILE = Path(__file__).parent / "product_specs_cache.json"


class ProductSpecsAI:
    """Uses OpenAI to infer AV equipment specifications with persistent caching"""
    
    def __init__(self):
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package is required. Install with: pip3 install openai")
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o"  # Use GPT-4o for best accuracy
        
        # Load persistent cache
        self._cache = self._load_cache()
        print(f"📦 Loaded {len(self._cache)} cached product specs")
    
    def _load_cache(self) -> dict:
        """Load cached product specs from disk"""
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_cache(self) -> None:
        """Save product specs cache to disk"""
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(self._cache, f, indent=2)
        except IOError as e:
            print(f"⚠️  Could not save cache: {e}")
    
    def get_product_specs(self, products: list[dict]) -> dict[str, dict]:
        """
        Get specifications for multiple products, using cache when available.
        Only calls OpenAI API for products not already in cache.
        
        Args:
            products: List of dicts with 'brand', 'model', 'category', 'name' keys
            
        Returns:
            Dict mapping "brand model" to specs dict with rack_units, weight, btu, connections
        """
        if not products:
            return {}
        
        results = {}
        products_to_lookup = []
        
        # Check cache first
        for p in products:
            key = f"{p.get('brand', '')} {p.get('model', '')}".strip().lower()
            if key in self._cache:
                print(f"  💾 Cache hit: {p.get('brand', '')} {p.get('model', '')}")
                results[key] = self._cache[key]
            else:
                products_to_lookup.append(p)
        
        # If all products were cached, return early
        if not products_to_lookup:
            print("  ✅ All products found in cache!")
            return results
        
        print(f"  🌐 Looking up {len(products_to_lookup)} products via OpenAI API...")
        
        # Build the product list for the prompt
        product_list = []
        for i, p in enumerate(products_to_lookup, 1):
            product_list.append(
                f"{i}. {p.get('brand', '')} {p.get('model', '')} - {p.get('category', '')} - {p.get('name', '')}"
            )
        
        products_text = "\n".join(product_list)
        
        prompt = f"""You are an expert AV systems integrator. I need specifications for rack-mountable AV equipment.

For each product below, provide:
1. rack_units: Height in rack units (U). Standard rack unit is 1.75 inches.
2. weight: Approximate weight in pounds (lbs)
3. btu: Heat output in BTU/hour (roughly watts × 3.41)
4. connections: Object with input/output connection types

Products to analyze:
{products_text}

IMPORTANT - RACK-MOUNTABLE EQUIPMENT (is_rack_mountable: true):
- Network switches (Ubiquiti, Araknis, Pakedge, Cisco): 1-2U
- AV receivers and processors: 2-4U
- Amplifiers (Savant PAV, Sonance, Crown): 1-3U
- Power conditioners/UPS (WattBox, Furman, Panamax): 1-3U
- Lutron HomeWorks Processors (HQP6, HQP7): 6-7U (these are LARGE!)
- Lutron repeaters (HQR-REP): 0.5U (mounts on rail)
- Savant Smart Controllers (SSC): 1U (with rack mount kit)
- Savant Climate Controllers (CLI-8000): 1U
- Savant Servers (SVR): 2U
- Savant Rack Mount Brackets (RCK, RMB): 2U
- Control4 controllers: 1U
- Routers and firewalls: 1U
- Patch panels: 1-2U
- Middle Atlantic shelves, blanks, vents (SA, BR, UMS): 1-2U

NOT RACK-MOUNTABLE (is_rack_mountable: false, rack_units: 0):
- Speakers, subwoofers, soundbars
- Cables, connectors, wire
- Keypads, touchscreens (wall-mounted)
- TVs, projectors, screens
- Wireless access points (E7, UAP - ceiling/wall mounted)
- Thermostats (CLI-THFM1 - wall mounted)
- Hard drives (UACC-HDD) - they go IN a device
- SFP modules (UACC-UPLINK) - they plug INTO a switch
- Software licenses (SSL)
- Power supplies (PWR, QSPS) - they go with dimmers, not rack

Be INCLUSIVE - if equipment CAN be rack mounted with appropriate brackets, include it.

Respond with ONLY valid JSON in this exact format:
{{
  "products": [
    {{
      "brand": "Brand Name",
      "model": "Model Number", 
      "rack_units": 2,
      "weight": 15.0,
      "btu": 200,
      "is_rack_mountable": true,
      "connections": {{
        "hdmi_in": 4,
        "hdmi_out": 2,
        "audio_out": "7.1 analog",
        "network": "RJ45"
      }}
    }}
  ]
}}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert AV systems integrator with deep knowledge of professional audio/video equipment specifications. Always respond with valid JSON only."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low temperature for consistency
                response_format={"type": "json_object"}
            )
            
            # Parse the response
            content = response.choices[0].message.content
            data = json.loads(content)
            
            # Process API results and add to cache
            for product in data.get("products", []):
                key = f"{product.get('brand', '')} {product.get('model', '')}".strip().lower()
                spec_data = {
                    "rack_units": product.get("rack_units", 1),
                    "weight": product.get("weight", 10.0),
                    "btu": product.get("btu", 100),
                    "is_rack_mountable": product.get("is_rack_mountable", True),
                    "connections": product.get("connections", {})
                }
                # Add to results and cache
                results[key] = spec_data
                self._cache[key] = spec_data
            
            # Save updated cache to disk
            self._save_cache()
            print(f"  💾 Saved {len(products_to_lookup)} new products to cache")
            
            return results
            
        except Exception as e:
            print(f"❌ OpenAI API error: {e}")
            return results  # Return any cached results we found
    
    def get_single_product_specs(self, brand: str, model: str, category: str = "") -> Optional[dict]:
        """Get specs for a single product"""
        products = [{"brand": brand, "model": model, "category": category, "name": ""}]
        specs = self.get_product_specs(products)
        
        key = f"{brand} {model}".strip().lower()
        return specs.get(key)


# Singleton instance
_client: Optional[ProductSpecsAI] = None


def get_openai_client() -> ProductSpecsAI:
    """Get or create the OpenAI client singleton"""
    global _client
    if _client is None:
        _client = ProductSpecsAI()
    return _client


if __name__ == "__main__":
    # Test the OpenAI integration
    print("🤖 Testing OpenAI product specs lookup...\n")
    
    test_products = [
        {"brand": "Marantz", "model": "SR6015", "category": "Receivers > Surround", "name": "9.2 channel 8K receiver"},
        {"brand": "WattBox", "model": "WB-800-IPVM-12", "category": "Power Protection", "name": "12 outlet power conditioner"},
        {"brand": "Savant", "model": "SVR-5200S-00", "category": "Control Systems", "name": "Pro Host controller"},
        {"brand": "Araknis", "model": "AN-110-SW-R-24", "category": "Networking > Switches", "name": "24-port switch"},
    ]
    
    try:
        client = get_openai_client()
        print("✅ Connected to OpenAI\n")
        
        print("📡 Sending products to GPT-4o for analysis...")
        specs = client.get_product_specs(test_products)
        
        print(f"\n📦 Received specs for {len(specs)} products:\n")
        
        for key, data in specs.items():
            print(f"  • {key}")
            print(f"    Rack Units: {data.get('rack_units')}U")
            print(f"    Weight: {data.get('weight')} lbs")
            print(f"    BTU: {data.get('btu')}")
            print(f"    Rack Mountable: {data.get('is_rack_mountable')}")
            print(f"    Connections: {data.get('connections')}")
            print()
            
    except Exception as e:
        print(f"❌ Error: {e}")

