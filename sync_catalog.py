import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

# Setup
API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = "appUhe8Eg7AY7KBMX"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Table IDs
PRODUCTS_TABLE = "PASTE_YOUR_PRODUCTS_TABLE_ID_HERE" 
CATALOG_TABLE = "tblwXTju8HxdIH3p0" 

def sync_product_to_catalog(target_product_name):
    # 1. FIND the record ID in the 'Products' table
    search_url = f"https://api.airtable.com/v0/{BASE_ID}/{PRODUCTS_TABLE}?filterByFormula={{Product Name}}='{target_product_name}'"
    
    response = requests.get(search_url, headers=HEADERS)
    records = response.json().get('records', [])
    
    if not records:
        print(f"❌ Could not find '{target_product_name}' in the Product Section.")
        return

    product_record_id = records[0]['id']
    print(f"🔍 Found ID for '{target_product_name}': {product_record_id}")

    # 2. CREATE the new entry in the 'Product Catalog' table
    upload_url = f"https://api.airtable.com/v0/{BASE_ID}/{CATALOG_TABLE}"
    
    data = {
        "records": [
            {
                "fields": {
                    "Name": target_product_name,        # Name column in Catalog
                    "Product Section": [product_record_id] # Linking column
                }
            }
        ]
    }

    upload_res = requests.post(upload_url, headers=HEADERS, data=json.dumps(data))
    
    if upload_res.status_code == 200:
        print(f"✅ Successfully added '{target_product_name}' to the Product Catalog!")
    else:
        print(f"❌ Error adding to Catalog: {upload_res.text}")

# --- RUN THE SYNC ---
# Replace this text with a real product name from your Product Section
sync_product_to_catalog("#")# --- RUN THE SYNC ---
# Replace this text with a real product name from your Product Section
# sync_product_to_catalog("#")# --- RUN THE SYNC ---
# Replace this text with a real product name from your Product Section
# sync_product_to_catalog("SonosAmp")## --- RUN THE SYNC ---
# Replace this text with a real product name from your Product Section
# sync_product_to_catalog("SonosAmp")





