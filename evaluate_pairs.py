import os
import json
import csv
import sys
import subprocess
import shutil
import argparse
import re
import glob

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHISHING_JSON = os.path.join(BASE_DIR, "phising.json")
WEB_CRAWLER = os.path.join(BASE_DIR, "collect", "web_crawler.py")
CLASSIFY_SCRIPT = os.path.join(BASE_DIR, "hasher", "classify_web.py")
UIHASH_SCRIPT = os.path.join(BASE_DIR, "hasher", "uihash.py")
COMPARE_SCRIPT = os.path.join(BASE_DIR, "hasher", "compare_siamese.py")

MODEL_PATH = os.path.join(BASE_DIR, "models", "siamese_e30_32_5x10.tar")
EVAL_OUTPUT_DIR = os.path.join(BASE_DIR, "eval_output")
CACHE_DIR = os.path.join(EVAL_OUTPUT_DIR, "cache_legit")

PYTHON_EXE = sys.executable

def run_command(cmd, cwd=None):
    """Run a command only if safe. This script is intended for the USER to run."""
    print(f"Running command: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)

def get_latest_dir(parent_dir):
    """Get the most recently created subdirectory in parent_dir."""
    dirs = [os.path.join(parent_dir, d) for d in os.listdir(parent_dir) if os.path.isdir(os.path.join(parent_dir, d))]
    if not dirs:
        return None
    return max(dirs, key=os.path.getmtime)

def evaluate(start_index=0, max_count=None):
    if not os.path.exists(PHISHING_JSON):
        print(f"Error: {PHISHING_JSON} not found.")
        return

    # Load JSON data
    with open(PHISHING_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Prepare Directories
    if not os.path.exists(EVAL_OUTPUT_DIR):
        os.makedirs(EVAL_OUTPUT_DIR)
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    
    results_csv = os.path.join(EVAL_OUTPUT_DIR, "results.csv")
    # Always append, but if creating new, write header
    if not os.path.exists(results_csv):
        with open(results_csv, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            # Added Verdict column
            writer.writerow(["Target", "Legitimate_URL", "Phishing_URL", "Score", "Distance", "Verdict", "Legit_Path", "Phish_Path"])

    legit_cache = {}
    processed_count = 0
    
    # Target Threshold for Verdict
    TARGET_THRESHOLD = 0.8
    TARGET_MAX_DIST = 3.0

    for i, entry in enumerate(data):
        if i < start_index:
            continue
        if max_count is not None and processed_count >= max_count:
            break

        target = entry.get('target', 'Unknown')
        legit_url = entry.get('legitimate_url')
        phish_urls = entry.get('phishing_urls', [])
        
        if isinstance(phish_urls, str):
            phish_urls = [phish_urls]

        if not legit_url:
            continue

        # --- 1. PREP LEGIT SITE ---
        legit_path_source = None
        
        if legit_url in legit_cache and os.path.exists(legit_cache[legit_url]):
            print(f"Using cached legitimate site for {legit_url}")
            legit_path_source = legit_cache[legit_url]
        else:
            print(f"Crawling Legitimate URL: {legit_url}")
            existing_dirs = set(os.listdir(CACHE_DIR))
            try:
                run_command([PYTHON_EXE, WEB_CRAWLER, legit_url, "--output", CACHE_DIR, "--headless", "--pages", "10", "--scrolls", "3"])
            except subprocess.CalledProcessError:
                print("Failed to crawl legitimate URL.")
                continue

            new_dirs = set(os.listdir(CACHE_DIR)) - existing_dirs
            if new_dirs:
                created_dir_name = list(new_dirs)[0]
                legit_path_source = os.path.join(CACHE_DIR, created_dir_name)
                legit_cache[legit_url] = legit_path_source
            else:
                legit_path_source = get_latest_dir(CACHE_DIR)
                if legit_path_source:
                     legit_cache[legit_url] = legit_path_source

        if not legit_path_source:
            print("Error: Could not determine legitimate site folder.")
            continue

        # --- PROCESS PHISHING PAIRS ---
        for j, phish_url in enumerate(phish_urls):
            print(f"\n{'='*60}")
            print(f"Processing Pair {i}-{j}: {target}")
            print(f"{'='*60}")
            
            pair_id = f"{i}_{j}_{target.replace(' ', '_').replace('/', '_')}"
            pair_dir = os.path.join(EVAL_OUTPUT_DIR, pair_id)
            
            if os.path.exists(pair_dir):
                shutil.rmtree(pair_dir)
            os.makedirs(pair_dir)

            try:
                # Copy Legit
                legit_folder_name = os.path.basename(legit_path_source)
                shutil.copytree(legit_path_source, os.path.join(pair_dir, legit_folder_name))
                
                # Crawl Phish
                print(">>> Crawling Phishing URL...")
                run_command([PYTHON_EXE, WEB_CRAWLER, phish_url, "--output", pair_dir, "--headless", "--pages", "10", "--scrolls", "3"])

                subdirs = [os.path.join(pair_dir, d) for d in os.listdir(pair_dir) if os.path.isdir(os.path.join(pair_dir, d))]
                if len(subdirs) < 2:
                    print("Error: Failed to download both sites.")
                    continue

                # Classify
                print(">>> Classifying...")
                run_command([PYTHON_EXE, CLASSIFY_SCRIPT, pair_dir, "--tag-only"])

                # Hash
                print(">>> Generating Hashes...")
                run_command([PYTHON_EXE, UIHASH_SCRIPT, pair_dir, "dummy", "--output_path", pair_dir, "--num_classes", "8", "--grid_size", "10,5", "--naivexml"])
                
                hash_files = glob.glob(os.path.join(pair_dir, "hash*.npy"))
                name_files = glob.glob(os.path.join(pair_dir, "name*.npy"))

                if not hash_files:
                    print("Error: Hash generation failed.")
                    continue
                
                hash_path = hash_files[0]
                name_path = name_files[0]

                # Compare
                print(">>> Comparing...")
                # NOTE: We use threshold -1.0 internally to force output of the best score even if low,
                # so we can record it in the CSV. We will apply the user's criteria (0.8) for the "Verdict".
                cmd = [
                    PYTHON_EXE, COMPARE_SCRIPT, 
                    hash_path, name_path, MODEL_PATH, 
                    "--hash_size", "8,10,5", 
                    "--top", "50", 
                    "--cross", 
                    "--threshold", "-2.0" 
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                print(result.stdout)

                # --- Save Detailed Results to CSV (results_details.csv) ---
                details_csv = os.path.join(EVAL_OUTPUT_DIR, "results_details.csv")
                # Write header if new
                if not os.path.exists(details_csv):
                    with open(details_csv, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(["Target", "Legitimate_URL", "Phishing_URL", "Rank", "Score", "Distance", "File_A", "File_B"])

                # Regex to parse multiple pairs
                # Format:
                # 1. Score: 1.0000 (Dist: 0.0000)
                #    A: ...
                #    B: ...
                pattern = r"(\d+)\. Score: ([\d\.\-]+) \(Dist: ([\d\.\-]+)\)\s+A: (.+)\s+B: (.+)"
                matches = re.findall(pattern, result.stdout)

                if matches:
                    with open(details_csv, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        for m in matches:
                            rank = m[0]
                            sc = m[1]
                            dst = m[2]
                            file_a = m[3].strip()
                            file_b = m[4].strip()
                            writer.writerow([target, legit_url, phish_url, rank, sc, dst, file_a, file_b])
                else:
                    # If no matches found (e.g. threshold issue), maybe write one line indicating no results?
                    # Or just skip. User wants details.
                    pass

                # Extract Score (Best Match for Summary)
                score_str = "N/A"
                dist_str = "N/A"
                verdict = "Fail"

                # Use the first match from regex if available
                if matches:
                    score_str = matches[0][1]
                    dist_str = matches[0][2]
                    try:
                        sc = float(score_str)
                        dst = float(dist_str)
                        if sc >= TARGET_THRESHOLD and dst <= TARGET_MAX_DIST:
                            verdict = "Match"
                    except:
                        pass
                else:
                    # Fallback regex for single if loop failed or format weird
                    match_single = re.search(r"1\. Score: ([\d\.\-]+) \(Dist: ([\d\.\-]+)\)", result.stdout)
                    if match_single:
                        score_str = match_single.group(1)
                        dist_str = match_single.group(2)

                l_path = os.path.basename(subdirs[0])
                p_path = os.path.basename(subdirs[1]) if len(subdirs) > 1 else ""

                with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([target, legit_url, phish_url, score_str, dist_str, verdict, l_path, p_path])

            except Exception as e:
                print(f"Exception processing pair {i}-{j}: {e}")
                import traceback
                traceback.print_exc()
        
        processed_count += 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=None)
    args = parser.parse_args()

    print("Starting automated evaluation...")
    evaluate(start_index=args.start, max_count=args.count)
