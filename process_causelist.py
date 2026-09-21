import os
import re
import json
import requests
import pymupdf
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# 1. Google Sheets Connection
SERVICE_ACCOUNT_INFO = json.loads(os.environ["GCP_SA_KEY"])
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)

SPREADSHEET_NAME = "High Court Cause List Tracker"  # Ensure this matches your Sheet title
sheet = gc.open(SPREADSHEET_NAME).sheet1

# Set up clean structured headers
HEADERS = [
    "Date Added",
    "Court / Bench",
    "Item No",
    "Case Number",
    "Parties (Petitioner vs Respondent)",
    "Matched Keyword",
    "Advocates"
]

if not sheet.row_values(1):
    sheet.append_row(HEADERS)

# 2. Keywords Setup
KEYWORDS = [
    (r"\bA\.?C\.?S\.?\s+Home\b", "ACS Home"),
    (r"\bPrincipal\s+Sec(?:retary)?\.?\s+Home\b", "Principal Secretary Home"),
    (r"\bSec(?:retary)?\.?\s+Home\b", "Secretary Home"),
    (r"\bHome\s+Dep(?:artmen)?t\.?\b", "Home Department"),
    (r"\bD\.?G\.?P\.?\b|\bDirector\s+General\s+of\s+Police\b", "DGP"),
    (r"\bPolice\b", "Police")
]

# 3. Download Cause List PDF
today_str = datetime.now().strftime("%d-%m-%Y")
PDF_URL = "https://www2.allahabadhighcourt.in/clist/-99_0_CauseList23092026_All_21092026071229.pdf"  # Replace with actual URL

print(f"Downloading PDF from {PDF_URL}...")
response = requests.get(PDF_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
response.raise_for_status()

pdf_doc = pymupdf.open(stream=response.content, filetype="pdf")
print(f"Total pages: {len(pdf_doc)}")

# Load existing Case Numbers (Column D) to prevent duplicate rows
existing_cases = set(sheet.col_values(4)[1:]) if sheet.row_count > 1 else set()

new_rows = []
current_court = "Court / Bench Not Specified"

for page_idx in range(len(pdf_doc)):
    page = pdf_doc[page_idx]
    
    # Extract text as layout-aware blocks: (x0, y0, x1, y1, text, block_no, block_type)
    blocks = page.get_text("blocks")
    
    # Combine page text into structured lines
    page_text = "\n".join([b[4] for b in blocks if b[4].strip()])

    # Detect Court / Bench heading if present on the page
    court_match = re.search(r"(COURT\s+NO\.\s*\d+|CHAMBER\s+OF\s+[\w\s\.]+|HON'BLE\s+MR\.\s+JUSTICE\s+[\w\s\.]+)", page_text, re.IGNORECASE)
    if court_match:
        current_court = " ".join(court_match.group(0).split())

    # Fast skip if no target keywords exist on this page
    if not any(re.search(pat, page_text, re.IGNORECASE) for pat, _ in KEYWORDS):
        continue

    # Split cases by Item Number or Case Identifier
    # Matches patterns like: "1.  WRIT - A/...", "101.  CRLA/...", "[ 12 ] WRIT - C/..."
    raw_cases = re.split(r'\n(?=(?:\d{1,4}\.|\s*\[\s*\d{1,4}\s*\])\s+(?:WRIT|CRLA|BAIL|APPLICATION|MISC|CONTEMPT|FIRST APPEAL|W\.P\.|\b[A-Z\-]{2,15}\b\/\d+))', page_text, flags=re.IGNORECASE)

    for case_text in raw_cases:
        clean_text = " ".join(case_text.split())
        if len(clean_text) < 25:
            continue

        # Check for keyword matches
        for pattern, label in KEYWORDS:
            if re.search(pattern, clean_text, re.IGNORECASE):
                
                # A. Extract Item Number (e.g., '1', '105', '[12]')
                item_match = re.match(r'^(?:\[\s*(\d+)\s*\]|(\d+)\.?)', clean_text)
                item_no = item_match.group(1) or item_match.group(2) if item_match else "N/A"

                # B. Extract Case Type and Number (e.g., 'WRIT-A No. 1234 of 2024' or 'CRLA/123/2023')
                case_no_match = re.search(
                    r'(?:WRIT\s*[-A-Za-z]*|CRL\.?A|CRIMINAL\s+REVISION|APPLICATION\s+U\/S\s+\d+|W\.P\.|BAIL)[\s\w\.\/\-No\.]+\d{1,6}\s*(?:OF|\/)\s*\d{2,4}', 
                    clean_text, 
                    re.IGNORECASE
                )
                case_number = " ".join(case_no_match.group(0).split()) if case_no_match else "Case Details Attached"

                # C. Extract Advocates (Usually preceded by Counsel for / Advocate:)
                advocate_match = re.search(r'(?:Counsel for [^:]+:|Advocate:|Advocate for [^:]+:)(.+)$', clean_text, re.IGNORECASE)
                advocates = advocate_match.group(1).strip() if advocate_match else "N/A"

                # D. Extract Parties (Between Case Number and Advocates)
                parties = clean_text
                if case_no_match:
                    parties = parties.replace(case_no_match.group(0), "")
                if advocate_match:
                    parties = parties.replace(advocate_match.group(0), "")
                
                parties = re.sub(r'^(?:\[\s*\d+\s*\]|\d+\.?)\s*', '', parties).strip()
                parties_snippet = " ".join(parties.split())[:350]

                # De-duplicate: Ensure this case hasn't been added yet
                case_id_key = f"{item_no}_{case_number}" if case_number != "Case Details Attached" else parties_snippet[:50]

                if case_id_key not in existing_cases:
                    new_rows.append([
                        today_str,
                        current_court,
                        item_no,
                        case_number,
                        parties_snippet,
                        label,
                        advocates[:200]
                    ])
                    existing_cases.add(case_id_key)
                break

# 4. Write back to Google Sheet
if new_rows:
    sheet.append_rows(new_rows)
    print(f"Appended {len(new_rows)} cleanly structured rows.")
else:
    print("No matching cases found today.")
