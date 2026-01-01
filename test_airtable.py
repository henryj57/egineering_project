import requests
import os
from dotenv import load_dotenv
from urllib.parse import quote

load_dotenv()

API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = quote("Product Catalog")

if not API_KEY or not BASE_ID:
    raise ValueError("Missing AIRTABLE_API_KEY or AIRTABLE_BASE_ID")

url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

print("=== ATTEMPTING CONNECTION ===")
response = requests.get(url, headers=headers)

print("Status Code:", response.status_code)
print(response.text)



