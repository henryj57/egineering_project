"""
MySQL Database Client - Product Catalog
Replaces Airtable as the "Brain" for equipment specifications
"""

import os
from typing import Optional, Dict, List
from pathlib import Path
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()
load_dotenv(Path(__file__).parent / ".env")

# Try to import MySQL connector
try:
    import mysql.connector
    from mysql.connector import Error
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("⚠️  mysql-connector-python not installed. Run: pip3 install mysql-connector-python")


class ProductDatabase:
    """
    MySQL client for the Product Catalog database.
    Stores equipment specs: Height (U), Watts, BTU, Weight, Subsystem, etc.
    """
    
    def __init__(self):
        if not MYSQL_AVAILABLE:
            raise ImportError("mysql-connector-python is required. Install with: pip3 install mysql-connector-python")
        
        # Load credentials from .env
        self.host = os.getenv("MYSQL_HOST", "localhost")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.user = os.getenv("MYSQL_USER", "root")
        self.password = os.getenv("MYSQL_PASSWORD", "")
        self.database = os.getenv("MYSQL_DATABASE", "av_catalog")
        
        self.connection = None
        self._product_cache: Dict[str, Dict] = {}
        self._cache_loaded = False
    
    def connect(self):
        """Establish connection to MySQL"""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database
            )
            if self.connection.is_connected():
                print(f"✅ Connected to MySQL database: {self.database}")
                return True
        except Error as e:
            print(f"❌ MySQL Connection Error: {e}")
            return False
    
    def disconnect(self):
        """Close the database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("🔌 Disconnected from MySQL")
    
    def initialize_schema(self):
        """Create the product_catalog table if it doesn't exist"""
        if not self.connection or not self.connection.is_connected():
            self.connect()
        
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS product_catalog (
            id INT AUTO_INCREMENT PRIMARY KEY,
            brand VARCHAR(100),
            model VARCHAR(100) NOT NULL,
            name VARCHAR(255),
            part_number VARCHAR(100),
            height_u INT DEFAULT 1,
            watts DECIMAL(10,2) DEFAULT 0,
            btu DECIMAL(10,2) DEFAULT 0,
            weight DECIMAL(10,2) DEFAULT 0,
            subsystem ENUM('AV', 'Network', 'Power', 'Other') DEFAULT 'AV',
            is_rack_mountable BOOLEAN DEFAULT TRUE,
            category VARCHAR(100),
            connections TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            
            UNIQUE KEY unique_model (brand, model),
            INDEX idx_model (model),
            INDEX idx_part_number (part_number),
            INDEX idx_subsystem (subsystem)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(create_table_sql)
            self.connection.commit()
            print("✅ Product catalog table ready")
            cursor.close()
            return True
        except Error as e:
            print(f"❌ Error creating table: {e}")
            return False
    
    def add_product(self, product: Dict) -> bool:
        """Add or update a product in the catalog"""
        if not self.connection or not self.connection.is_connected():
            self.connect()
        
        upsert_sql = """
        INSERT INTO product_catalog 
            (brand, model, name, part_number, height_u, watts, btu, weight, subsystem, is_rack_mountable, category, connections, notes)
        VALUES 
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            part_number = VALUES(part_number),
            height_u = VALUES(height_u),
            watts = VALUES(watts),
            btu = VALUES(btu),
            weight = VALUES(weight),
            subsystem = VALUES(subsystem),
            is_rack_mountable = VALUES(is_rack_mountable),
            category = VALUES(category),
            connections = VALUES(connections),
            notes = VALUES(notes)
        """
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(upsert_sql, (
                product.get('brand', ''),
                product.get('model', ''),
                product.get('name', ''),
                product.get('part_number', ''),
                product.get('height_u', 1),
                product.get('watts', 0),
                product.get('btu', 0),
                product.get('weight', 0),
                product.get('subsystem', 'AV'),
                product.get('is_rack_mountable', True),
                product.get('category', ''),
                product.get('connections', ''),
                product.get('notes', '')
            ))
            self.connection.commit()
            cursor.close()
            return True
        except Error as e:
            print(f"❌ Error adding product: {e}")
            return False
    
    def bulk_add_products(self, products: List[Dict]) -> int:
        """Add multiple products at once"""
        added = 0
        for product in products:
            if self.add_product(product):
                added += 1
        print(f"✅ Added/updated {added} products")
        return added
    
    def _load_all_products(self) -> None:
        """Load all products from MySQL into cache"""
        if self._cache_loaded:
            return
        
        if not self.connection or not self.connection.is_connected():
            self.connect()
        
        print("🧠 Loading Product Catalog from MySQL...")
        
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM product_catalog WHERE is_rack_mountable = TRUE")
            rows = cursor.fetchall()
            
            for row in rows:
                product_data = {
                    'id': row['id'],
                    'brand': row['brand'] or '',
                    'model': row['model'] or '',
                    'name': row['name'] or '',
                    'part_number': row['part_number'] or '',
                    'rack_units': row['height_u'] or 1,
                    'height_u': row['height_u'] or 1,
                    'watts': float(row['watts'] or 0),
                    'btu': float(row['btu'] or 0),
                    'weight': float(row['weight'] or 0),
                    'subsystem': row['subsystem'] or 'AV',
                    'is_rack_mountable': bool(row['is_rack_mountable']),
                    'category': row['category'] or '',
                    'connections': row['connections'] or '',
                    'source': 'mysql'
                }
                
                # Index by multiple keys for flexible lookup
                model_key = row['model'].strip().lower() if row['model'] else ''
                part_key = row['part_number'].strip().lower() if row['part_number'] else ''
                brand = row['brand'].strip().lower() if row['brand'] else ''
                
                if model_key:
                    self._product_cache[model_key] = product_data
                if part_key:
                    self._product_cache[part_key] = product_data
                if brand and model_key:
                    self._product_cache[f"{brand} {model_key}"] = product_data
            
            cursor.close()
            self._cache_loaded = True
            print(f"✅ Loaded {len(rows)} products from MySQL")
            
        except Error as e:
            print(f"❌ Error loading from MySQL: {e}")
            raise
    
    def lookup_by_model(self, model_number: str) -> Optional[Dict]:
        """
        Look up a product by Model Number.
        
        Args:
            model_number: The model/part number to search for
            
        Returns:
            Product data dict or None if not found
        """
        self._load_all_products()
        
        search_key = model_number.strip().lower() if model_number else ''
        
        # Skip empty or too-short search keys
        if len(search_key) < 3:
            return None
        
        # Direct lookup
        if search_key in self._product_cache:
            return self._product_cache[search_key]
        
        # Fuzzy match - require minimum 4 characters for fuzzy matching
        if len(search_key) >= 4:
            for cached_key, data in self._product_cache.items():
                if len(cached_key) >= 4 and (search_key in cached_key or cached_key in search_key):
                    return data
        
        return None
    
    def get_rack_specs(self, model_number: str) -> Optional[Dict]:
        """
        Get rack-relevant specs for a product.
        
        Returns:
            Dict with rack_units, weight, btu, watts, subsystem
            or None if not found
        """
        product = self.lookup_by_model(model_number)
        
        if not product:
            return None
        
        if not product.get('rack_units') or product.get('rack_units', 0) == 0:
            return None
        
        return {
            'rack_units': product.get('rack_units', 1),
            'height_u': product.get('height_u', 1),
            'weight': product.get('weight', 10.0),
            'watts': product.get('watts', 0),
            'btu': product.get('btu', 0),
            'subsystem': product.get('subsystem', 'AV'),
            'is_rack_mountable': True,
            'brand': product.get('brand', ''),
            'model': product.get('model', ''),
            'connections': product.get('connections', ''),
            'source': 'mysql'
        }
    
    def get_all_products(self) -> List[Dict]:
        """Get all products from the catalog"""
        self._load_all_products()
        
        # Return unique products
        seen_ids = set()
        unique_products = []
        
        for product in self._product_cache.values():
            product_id = product.get('id')
            if product_id and product_id not in seen_ids:
                seen_ids.add(product_id)
                unique_products.append(product)
        
        return unique_products
    
    def search_products(self, query: str) -> List[Dict]:
        """Search products by brand, model, or name"""
        if not self.connection or not self.connection.is_connected():
            self.connect()
        
        search_sql = """
        SELECT * FROM product_catalog 
        WHERE brand LIKE %s 
           OR model LIKE %s 
           OR name LIKE %s 
           OR part_number LIKE %s
        """
        
        try:
            cursor = self.connection.cursor(dictionary=True)
            search_term = f"%{query}%"
            cursor.execute(search_sql, (search_term, search_term, search_term, search_term))
            rows = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in rows]
        except Error as e:
            print(f"❌ Search error: {e}")
            return []


# Singleton instance
_db: Optional[ProductDatabase] = None


def get_database() -> ProductDatabase:
    """Get or create the database singleton"""
    global _db
    if _db is None:
        _db = ProductDatabase()
        _db.connect()
    return _db


# Alias for compatibility with existing code
def get_airtable_client():
    """Compatibility alias - returns MySQL database instead"""
    return get_database()


def get_brain():
    """Compatibility alias - returns MySQL database instead"""
    return get_database()


if __name__ == "__main__":
    print("🔌 Testing MySQL Database Connection...")
    print("=" * 50)
    
    try:
        db = get_database()
        
        # Initialize schema
        db.initialize_schema()
        
        # Check for existing products
        products = db.get_all_products()
        print(f"\n📦 Found {len(products)} products in catalog")
        
        if len(products) == 0:
            print("\n💡 Database is empty. You can import products using:")
            print("   python3 import_products.py <csv_file>")
        else:
            print("\nFirst 5 products:")
            for p in products[:5]:
                print(f"  • {p.get('brand', '')} {p.get('model', '')}: {p.get('height_u', 0)}U, {p.get('watts', 0)}W")
        
        db.disconnect()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n📋 Setup Instructions:")
        print("1. Install MySQL: brew install mysql")
        print("2. Start MySQL: brew services start mysql")
        print("3. Create database: mysql -u root -e 'CREATE DATABASE av_catalog;'")
        print("4. Add to .env file:")
        print("   MYSQL_HOST=localhost")
        print("   MYSQL_USER=root")
        print("   MYSQL_PASSWORD=your_password")
        print("   MYSQL_DATABASE=av_catalog")

