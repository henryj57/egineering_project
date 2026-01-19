#!/usr/bin/env python3
"""
Import D-Tools Products.csv into SQL as an equipment library seed.

- Reads the D-Tools export with columns like:
  Brand, Model, Part Number, Category, Height, Width, Depth, Weight,
  Rack Mounted, Rack Units, Amps, Volts, Watts, BTU, etc.

- Writes to table: equipment_model
- Uses INSERT OR REPLACE for SQLite (simple upsert)

Usage:
  python3 import_dtools_products.py --csv "~/Downloads/DTools Products.csv" --db "sqlite:///equipment_library.db"
"""

import argparse
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd


def norm_str(x: Any) -> Optional[str]:
    """Normalize strings: return None for blank/NaN; else stripped string."""
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    return s if s else None


def to_float(x: Any) -> Optional[float]:
    """Parse numeric fields; return None if blank/unparseable."""
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    if not s:
        return None
    s = s.replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except:
        return None


def to_int(x: Any) -> Optional[int]:
    f = to_float(x)
    if f is None:
        return None
    try:
        return int(round(f))
    except:
        return None


def to_bool(x: Any) -> Optional[bool]:
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return None


def mount_type_from_rack_mounted(rack_mounted: Optional[bool], rack_units: Optional[int]) -> Optional[str]:
    """Infer mount_type from rack_mounted and rack_units."""
    if rack_mounted is True:
        return "rails"
    if rack_mounted is False:
        if rack_units in (None, 0):
            return "accessory"
    return None


def build_model_key(manufacturer: str, model: str) -> str:
    return f"{manufacturer.strip().lower()}:{model.strip().lower()}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help='Path to "DTools Products.csv" export')
    ap.add_argument("--db", required=True, help='DB path, e.g. sqlite:///equipment_library.db')
    args = ap.parse_args()

    csv_path = os.path.expanduser(args.csv)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # Extract SQLite path from connection string
    db_path = args.db.replace("sqlite:///", "")
    
    # Create/connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_model (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_key TEXT UNIQUE NOT NULL,
            manufacturer TEXT,
            brand TEXT,
            model TEXT,
            part_number TEXT,
            category TEXT,
            keywords TEXT,
            system TEXT,
            phase TEXT,
            upc TEXT,
            ean TEXT,
            itf TEXT,
            discontinued INTEGER,
            height_in REAL,
            width_in REAL,
            depth_in REAL,
            weight_lb REAL,
            rack_mounted INTEGER,
            ru_height INTEGER,
            mount_type TEXT,
            amps REAL,
            volts REAL,
            watts REAL,
            btu REAL,
            msrp REAL,
            unit_cost REAL,
            unit_price REAL,
            taxable INTEGER,
            image_url TEXT,
            created_date TEXT,
            modified_date TEXT,
            source TEXT,
            imported_at TEXT
        )
    """)
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_model ON equipment_model(model)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_part_number ON equipment_model(part_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manufacturer ON equipment_model(manufacturer)")
    
    conn.commit()

    # Read CSV
    print(f"📂 Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"   Found {len(df)} rows")

    def col(name: str):
        return df[name] if name in df.columns else None

    brand = col("Brand")
    model_col = col("Model")
    part_no = col("Part Number")
    supplier = col("Supplier")
    category = col("Category")
    keywords = col("Keywords")
    system = col("System")
    phase = col("Phase")
    upc = col("UPC")
    ean = col("EAN")
    itf = col("ITF")
    discontinued = col("Discontinued")

    height = col("Height")
    width = col("Width")
    depth = col("Depth")
    weight = col("Weight")
    rack_mounted = col("Rack Mounted")
    rack_units = col("Rack Units")

    amps = col("Amps")
    volts = col("Volts")
    watts = col("Watts")
    btu = col("BTU")

    msrp = col("MSRP")
    unit_cost = col("Unit Cost")
    unit_price = col("Unit Price")
    taxable = col("Taxable")

    image_url = col("Image URL")
    created_date = col("Created Date")
    modified_date = col("Modified Date")

    imported = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    print("📥 Importing products...")
    
    for i in range(len(df)):
        manufacturer = norm_str(supplier.iloc[i] if supplier is not None else None) or norm_str(brand.iloc[i] if brand is not None else None)
        if not manufacturer:
            skipped += 1
            continue

        m = norm_str(model_col.iloc[i] if model_col is not None else None)
        pn = norm_str(part_no.iloc[i] if part_no is not None else None)
        model = pn or m
        if not model:
            skipped += 1
            continue

        rk_mnt = to_bool(rack_mounted.iloc[i] if rack_mounted is not None else None)
        ru = to_int(rack_units.iloc[i] if rack_units is not None else None)
        mt = mount_type_from_rack_mounted(rk_mnt, ru)

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO equipment_model (
                    model_key, manufacturer, brand, model, part_number,
                    category, keywords, system, phase,
                    upc, ean, itf, discontinued,
                    height_in, width_in, depth_in, weight_lb,
                    rack_mounted, ru_height, mount_type,
                    amps, volts, watts, btu,
                    msrp, unit_cost, unit_price, taxable,
                    image_url, created_date, modified_date,
                    source, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                build_model_key(manufacturer, model),
                manufacturer,
                norm_str(brand.iloc[i]) if brand is not None else None,
                model,
                pn,
                norm_str(category.iloc[i]) if category is not None else None,
                norm_str(keywords.iloc[i]) if keywords is not None else None,
                norm_str(system.iloc[i]) if system is not None else None,
                norm_str(phase.iloc[i]) if phase is not None else None,
                norm_str(upc.iloc[i]) if upc is not None else None,
                norm_str(ean.iloc[i]) if ean is not None else None,
                norm_str(itf.iloc[i]) if itf is not None else None,
                1 if (discontinued is not None and to_bool(discontinued.iloc[i])) else 0,
                to_float(height.iloc[i]) if height is not None else None,
                to_float(width.iloc[i]) if width is not None else None,
                to_float(depth.iloc[i]) if depth is not None else None,
                to_float(weight.iloc[i]) if weight is not None else None,
                1 if rk_mnt else (0 if rk_mnt is False else None),
                ru,
                mt,
                to_float(amps.iloc[i]) if amps is not None else None,
                to_float(volts.iloc[i]) if volts is not None else None,
                to_float(watts.iloc[i]) if watts is not None else None,
                to_float(btu.iloc[i]) if btu is not None else None,
                to_float(msrp.iloc[i]) if msrp is not None else None,
                to_float(unit_cost.iloc[i]) if unit_cost is not None else None,
                to_float(unit_price.iloc[i]) if unit_price is not None else None,
                1 if (taxable is not None and to_bool(taxable.iloc[i])) else 0,
                norm_str(image_url.iloc[i]) if image_url is not None else None,
                norm_str(created_date.iloc[i]) if created_date is not None else None,
                norm_str(modified_date.iloc[i]) if modified_date is not None else None,
                "dtools_csv",
                now
            ))
            imported += 1
        except Exception as e:
            skipped += 1
            if skipped < 5:
                print(f"   ⚠️ Error on row {i}: {e}")

    conn.commit()

    # Stats
    cursor.execute("SELECT COUNT(*) FROM equipment_model")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM equipment_model WHERE rack_mounted = 1")
    rack_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM equipment_model WHERE ru_height > 0")
    ru_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM equipment_model WHERE watts > 0")
    watts_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM equipment_model WHERE btu > 0")
    btu_count = cursor.fetchone()[0]

    conn.close()

    print(f"\n✅ Import Complete!")
    print(f"   Imported: {imported:,}")
    print(f"   Skipped:  {skipped:,}")
    
    print(f"\n📊 Database Statistics ({db_path}):")
    print(f"   Total products:     {total:,}")
    print(f"   Rack-mountable:     {rack_count:,}")
    print(f"   With RU height:     {ru_count:,}")
    print(f"   With Wattage:       {watts_count:,}")
    print(f"   With BTU:           {btu_count:,}")
    
    print(f"\n✅ Done! Database ready at: {db_path}")
    print("   Point your rack generator at equipment_model by model_key.")


# Lookup helper for use by other scripts
def lookup_equipment(model: str = None, part_number: str = None, db_path: str = "racks.db") -> dict:
    """Look up equipment specs by model or part number."""
    if not os.path.exists(db_path):
        return None
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if part_number:
        cursor.execute(
            "SELECT * FROM equipment_model WHERE part_number = ? OR model = ? LIMIT 1",
            (part_number, part_number)
        )
    elif model:
        cursor.execute(
            "SELECT * FROM equipment_model WHERE model LIKE ? OR part_number LIKE ? LIMIT 1",
            (f"%{model}%", f"%{model}%")
        )
    else:
        return None
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def get_equipment_specs(model: str = None, part_number: str = None, db_path: str = "racks.db") -> dict:
    """Get rack-relevant specs for equipment. Returns defaults if not found."""
    result = lookup_equipment(model=model, part_number=part_number, db_path=db_path)
    
    if result:
        ru_height = result.get('ru_height') or 0
        # If it has RU height > 0, treat it as rack-mountable regardless of flag
        is_rack_mounted = bool(result.get('rack_mounted')) or ru_height > 0
        
        return {
            'rack_units': ru_height if ru_height > 0 else 1,
            'watts': result.get('watts') or 0,
            'btu': result.get('btu') or 0,
            'weight': result.get('weight_lb') or 0,
            'depth': result.get('depth_in') or 0,
            'rack_mounted': is_rack_mounted,
            'mount_type': result.get('mount_type') or 'rails',
            'manufacturer': result.get('manufacturer') or '',
            'brand': result.get('brand') or '',
            'model': result.get('model') or '',
            'category': result.get('category') or '',
        }
    
    # Defaults
    return {
        'rack_units': 1,
        'watts': 0,
        'btu': 0,
        'weight': 0,
        'depth': 0,
        'rack_mounted': False,
        'mount_type': None,
        'manufacturer': '',
        'brand': '',
        'model': model or part_number or '',
        'category': '',
    }


if __name__ == "__main__":
    main()
