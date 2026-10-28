from curl_cffi import requests
import time
import re
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import unquote
import os
import concurrent.futures
import threading

# ---------------- CONFIG ----------------

# ---------------- CONFIG ----------------
# Defaults
DEFAULT_KEYWORD = "tobacco"
DEFAULT_CITY = "New York, NY"
DEFAULT_PAGES = 1
DELAY = 1  # Reduced delay per thread, but concurrency adds up
OUTPUT_FILE = "leads.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

# ---------------- HELPERS ----------------
def get_business_profiles(keyword, city, pages, progress_callback=None, start_progress=0, end_progress=10):
    print(f"🔍 Searching for '{keyword}'...")
    profiles = set()

    for page in range(1, pages + 1):
        if progress_callback:
            # Map page progress to the allocated range [start_progress, end_progress]
            percent_complete = page / pages
            current_progress = start_progress + int(percent_complete * (end_progress - start_progress))
            progress_callback(f"Searching '{keyword}' (Page {page}/{pages})...", current_progress)
            
        url = f"https://www.yellowpages.com/search?search_terms={keyword}&geo_location_terms={city}&page={page}"
        print(f"   📄 Scraping page {page}: {url}")

        time.sleep(DELAY)
        try:
            res = requests.get(url, headers=HEADERS, timeout=10, impersonate="chrome")
            if res.status_code != 200:
                print(f"⚠️ Failed to retrieve page {page}. Status Code: {res.status_code}")
                continue
        except Exception as e:
            print(f"⚠️ Request failed: {e}")
            continue

        soup = BeautifulSoup(res.text, "html.parser")
        
        # Yellow Pages usually lists results in divs with class "result" or "v-card"
        # The business name link typically has class "business-name"
        for a in soup.find_all("a", class_="business-name", href=True):
            href = a["href"]
            if href.startswith("/"):
                profiles.add("https://www.yellowpages.com" + href)

    print(f"✅ Found {len(profiles)} business profiles")
    return list(profiles)


def extract_contact_from_profile(profile_url):
    print(f"➡️ Visiting profile: {profile_url}")
    time.sleep(DELAY)

    try:
        res = requests.get(profile_url, headers=HEADERS, timeout=10, impersonate="chrome")
        if res.status_code != 200:
             return None, None, None
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception:
        return None, None, None

    website = None
    phone = None

    # Extract website
    # Typically in a link with text "Website" or class "website-link"
    website_tag = soup.find("a", class_="website-link", href=True)
    if not website_tag:
        # Fallback: look for any link with 'Visit Website' text or similar if class changes
         website_tag = soup.find("a", string=lambda t: t and "website" in t.lower(), href=True)
    
    if website_tag:
        website = website_tag["href"]

    # Extract phone
    # Typically in a link/paragraph with class "phone"
    phone_tag = soup.find("a", class_="phone", href=True)
    if phone_tag:
        phone = phone_tag.get_text(strip=True)
    else:
        # Fallback
        phone_tag = soup.find("p", class_="phone")
        if phone_tag:
             phone = phone_tag.get_text(strip=True)

    email = scrape_email_from_website(website)

    return website, phone, email


def scrape_email_from_website(website):
    if not website:
        return None

    print(f"   🌐 Scraping website: {website}")
    time.sleep(DELAY)

    try:
        # Simple check to ensure we don't scrape internal YP links if something went wrong
        if "yellowpages.com" in website:
            return None

        res = requests.get(website, headers=HEADERS, timeout=10, impersonate="chrome")
        emails = re.findall(EMAIL_REGEX, res.text)
        # simplistic filter
        valid_emails = [e for e in emails if not e.endswith(".png") and not e.endswith(".jpg") and len(e) < 50]
        return valid_emails[0] if valid_emails else None
    except Exception:
        return None



# ---------------- MAIN ----------------
def run(keyword=DEFAULT_KEYWORD, city=DEFAULT_CITY, pages=DEFAULT_PAGES, progress_callback=None):
    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    profiles = set()
    total_keywords = len(keywords)
    
    # Phase 1: Search (0-20%)
    for idx, k in enumerate(keywords):
        # Calculate progress range for this keyword
        # e.g. if 2 keywords: Kw1 is 0-10%, Kw2 is 10-20%
        segment_size = 20 / total_keywords
        start_prog = int(idx * segment_size)
        end_prog = int((idx + 1) * segment_size)
        
        if progress_callback:
            progress_callback(f"Searching for '{k}' ({idx+1}/{total_keywords})...", start_prog)
            
        p = get_business_profiles(k, city, pages, progress_callback, start_progress=start_prog, end_progress=end_prog)
        profiles.update(p)
        
    leads = []
    
    # Phase 2: Extraction (20-100%)
    total_profiles = len(profiles)
    processed_count = 0
    lock = threading.Lock()

    def process_profile(profile):
        nonlocal processed_count
        try:
            website, phone, email = extract_contact_from_profile(profile)
            
            with lock:
                processed_count += 1
                if progress_callback:
                    # Allocate 20-95% for profile extraction
                    progress = 20 + int((processed_count / total_profiles) * 75)
                    progress_callback(f"Extracting profile {processed_count}/{total_profiles}...", progress)
            
            # Only return valid leads
            if website or phone or email:
                lead = {
                    "profile_url": profile,
                    "website": website,
                    "phone": phone,
                    "email": email
                }
                print("✅ Lead collected:", lead)
                return lead
            else:
                 print("   ⚠️ No contact info found.")
                 return None
        except Exception as e:
            print(f"Error processing profile {profile}: {e}")
            return None

    # Use ThreadPoolExecutor for concurrent execution
    # max_workers=10 means up to 10 profiles processed at once
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        leads_futures = [executor.submit(process_profile, profile) for profile in profiles]
        
        for future in concurrent.futures.as_completed(leads_futures):
            result = future.result()
            if result:
                leads.append(result)
             
    if progress_callback:
        progress_callback("Saving data...", 95)

    if leads:
        df = pd.DataFrame(leads)
        df.drop_duplicates(subset=["profile_url"], inplace=True)
        df.to_csv(OUTPUT_FILE, index=False)
        abs_path = os.path.abspath(OUTPUT_FILE)
        print(f"\n🎉 Done! Leads saved to {abs_path}")
        print(f"📊 Total unique leads: {len(df)}")
        return abs_path
    else:
        print("\n❌ No leads found.")
        return None

if __name__ == "__main__":
    run()
