import pandas as pd
import requests
import random
import concurrent.futures
import time
import os

# Configuration
INPUT_CSV = r"c:/Users/motok/Documents/Research/tranco/tranco_JLZNY-1m.csv/top-1m.csv"
OUTPUT_CSV = "verified_1000.csv"
TARGET_COUNT = 1000
MAX_WORKERS = 20
TIMEOUT = 5

def check_url(domain):
    """
    Check if the domain is accessible via HTTPS or HTTP.
    Returns the valid URL (https preferred) or None.
    """
    protocols = ["https://", "http://"]
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    headers = {"User-Agent": ua}

    for proto in protocols:
        url = f"{proto}{domain}"
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code < 400:
                return url
        except requests.RequestException:
            continue
    return None

def main():
    if not os.path.exists(INPUT_CSV):
        print(f"Error: Input file not found at {INPUT_CSV}")
        return

    print("Loading CSV...")
    # Read only the domain column (index 1) to save memory if needed, but file isn't huge.
    # No header in top-1m.csv (Rank, Domain)
    try:
        df = pd.read_csv(INPUT_CSV, header=None, names=["rank", "domain"])
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    all_domains = df["domain"].tolist()
    total_domains = len(all_domains)
    print(f"Loaded {total_domains} domains.")

    # Shuffle domains to get random candidates
    random.shuffle(all_domains)

    valid_urls = []
    checked_count = 0
    
    print(f"Starting verification (Target: {TARGET_COUNT} valid URLs)...")
    
    # Process in batches to avoid queuing 1 million tasks
    batch_size = TARGET_COUNT * 2
    current_idx = 0

    while len(valid_urls) < TARGET_COUNT and current_idx < total_domains:
        batch = all_domains[current_idx : current_idx + batch_size]
        current_idx += batch_size
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_domain = {executor.submit(check_url, domain): domain for domain in batch}
            
            for future in concurrent.futures.as_completed(future_to_domain):
                domain = future_to_domain[future]
                checked_count += 1
                try:
                    result_url = future.result()
                    if result_url:
                        valid_urls.append({"domain": domain, "url": result_url})
                        # Live update
                        if len(valid_urls) % 10 == 0:
                            print(f"Found {len(valid_urls)}/{TARGET_COUNT} valid... (Checked: {checked_count})")
                        
                        if len(valid_urls) >= TARGET_COUNT:
                            # Cancel remaining futures involves complex logic or just break and exit
                            break
                except Exception as e:
                    pass
                
                if len(valid_urls) >= TARGET_COUNT:
                    break
        
        if len(valid_urls) >= TARGET_COUNT:
            break

    print(f"\nVerification complete. Found {len(valid_urls)} valid URLs.")
    
    # Save to CSV
    if valid_urls:
        out_df = pd.DataFrame(valid_urls)
        out_df.to_csv(OUTPUT_CSV, index=False)
        print(f"Saved verified list to: {os.path.abspath(OUTPUT_CSV)}")
    else:
        print("No valid URLs found.")

if __name__ == "__main__":
    main()
