import os
import re
import json
import requests
import fitz  # PyMuPDF
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# 1. Connect to Google Sheets using Service Account credentials from Environment Variable
SERVICE_ACCOUNT_INFO = json.loads(os.environ["GCP_SA_KEY"])
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)

SPREADSHEET_NAME = "High Court Cause List Tracker"  # Name of your Google Sheet
sheet = gc.open(SPREADSHEET_NAME).sheet1

# Ensure header exists
if not sheet.row_values(1):
    sheet.append_row(["Date Added", "Matched Keyword", "Snippet / Parties"])

# 2. Configure Keywords
KEYWORDS = [
    (r"\bA\.?C\.?S\.?\s+Home\b", "ACS Home"),
    (r"\bPrincipal\s+Sec(?:retary)?\.?\s+Home\b", "Principal Secretary Home"),
    (r"\bSec(?:retary)?\.?\s+Home\b", "Secretary Home"),
    (r"\bHome\s+Dep(?:artmen)?t\.?\b", "Home Department"),
    (r"\bD\.?G\.?P\.?\b|\bDirector\s+General\s+of\s+Police\b", "DGP"),
    (r"\bPolice\b", "Police")
]

# 3. Download the PDF
today_str = datetime.now().strftime("%d-%m-%Y")
# Replace with the actual URL or dynamic daily URL pattern of your court's cause list
PDF_URL = "https://www2.allahabadhighcourt.in/clist/-99_0_CauseList23092026_All_21092026071229.pdf"

print(f"Downloading cause list from {PDF_URL}...")
response = requests.get(PDF_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
response.raise_for_status()

# 4. Parse PDF in-memory using PyMuPDF (Fast & no OCR limits)
pdf_doc = fitz.open(stream=response.content, filetype="pdf")
print(f"Total pages in cause list: {len(pdf_doc)}")

# Load existing entries in Column C (snippets) to prevent duplicates
existing_entries = set(sheet.col_values(3)[1:]) if sheet.row_count > 1 else set()

new_rows = []

for page_idx in range(len(pdf_doc)):
    page_text = pdf_doc[page_idx].get_text()
    
    # Quick filter: skip page entirely if none of the keywords appear
    if not any(re.search(pat, page_text, re.IGNORECASE) for pat, _ in KEYWORDS):
        continue
    
    # Split page into individual case blocks based on common serial / case markers
    case_blocks = re.split(r'\n(?=\s*(?:\[\s*\d+\s*\]|\d+[\.\/\)]|\b(?:WRIT|CRL|W\.P\.|BAIL)\b))', page_text)
    
    for block in case_blocks:
        clean_block = " ".join(block.split())
        if len(clean_block) < 25:
            continue
            
        for pattern, label in KEYWORDS:
            if re.search(pattern, clean_block, re.IGNORECASE):
                snippet = clean_block[:500]
                if snippet not in existing_entries:
                    new_rows.append([today_str, label, snippet])
                    existing_entries.add(snippet)
                break

# 5. Push to Google Sheet in a single batch
if new_rows:
    sheet.append_rows(new_rows)
    print(f"Successfully appended {len(new_rows)} matching cases.")
else:
    print("No matching cases found for the specified keywords today.")
