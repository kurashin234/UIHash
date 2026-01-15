import json
import csv
import random
import os

PHISHING_JSON = "phising.json"
VERIFIED_CSV = "verified_1000.csv"
OUTPUT_JSON = "UnrelatedSite.json"
URLS_PER_ENTRY = 15  # "Tens" -> 10-20. 15 is a good balance.

def main():
    # 1. Load Verified URLs
    if not os.path.exists(VERIFIED_CSV):
        print(f"Error: {VERIFIED_CSV} not found.")
        return

    verified_urls = []
    with open(VERIFIED_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if 'url' in row and row['url']:
                verified_urls.append(row['url'])
    
    print(f"Loaded {len(verified_urls)} verified URLs.")
    
    # 2. Load Phishing Data
    if not os.path.exists(PHISHING_JSON):
        print(f"Error: {PHISHING_JSON} not found.")
        return

    with open(PHISHING_JSON, 'r', encoding='utf-8') as f:
        phising_data = json.load(f)
        
    print(f"Loaded {len(phising_data)} legitimate entries.")

    # 3. Distribute Random URLs
    # Shuffle the pool
    random.shuffle(verified_urls)
    
    pool_index = 0
    pool_size = len(verified_urls)
    
    unrelated_data = []
    
    for entry in phising_data:
        target = entry.get('target')
        legit_url = entry.get('legitimate_url')
        
        # Pick N random URLs
        selected_urls = []
        for _ in range(URLS_PER_ENTRY):
            selected_urls.append(verified_urls[pool_index])
            pool_index += 1
            # Wrap around if we run out (minimal overlap, but some if slots > pool)
            if pool_index >= pool_size:
                random.shuffle(verified_urls) # Reshuffle for next pass
                pool_index = 0
        
        new_entry = {
            "target": target,
            "legitimate_url": legit_url,
            "phishing_urls": selected_urls
        }
        unrelated_data.append(new_entry)

    # 4. Save
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(unrelated_data, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully created {OUTPUT_JSON} with {len(unrelated_data)} entries.")
    print(f"Each entry has {URLS_PER_ENTRY} random URLs from the verified pool.")

if __name__ == "__main__":
    main()
