import os
import json
import csv
import sys
import subprocess
import argparse
import re

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_CRAWLER = os.path.join(BASE_DIR, "collect", "web_crawler.py")
CLASSIFY_SCRIPT = os.path.join(BASE_DIR, "hasher", "classify_web.py")
UIHASH_SCRIPT = os.path.join(BASE_DIR, "hasher", "uihash.py")
COMPARE_SCRIPT = os.path.join(BASE_DIR, "hasher", "compare_siamese.py")
MODEL_PATH = os.path.join(BASE_DIR, "models", "siamese_e30_32_5x10.tar")

PYTHON_EXE = sys.executable

def run_command(cmd, cwd=None):
    """Run a command via subprocess."""
    print(f"Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)

def evaluate(input_file, output_dir, start_index=0, max_count=None):
    """
    Evaluate phishing pairs with simplified folder structure.
    
    Folder structure:
    output_dir/
    ├── legit/
    │   └── {domain_timestamp}/
    ├── phish/
    │   └── {domain_timestamp}/
    ├── hash_10x5x8.npy
    ├── name_10x5x8.npy
    └── results.csv
    """
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    # Load JSON data
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON {input_file}: {e}")
        return

    # Prepare output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    results_csv = os.path.join(output_dir, "results.csv")
    
    # Write CSV header if new
    if not os.path.exists(results_csv):
        with open(results_csv, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Target", "Legitimate_URL", "Phishing_URL", "Best_Score", "Best_Distance", "Legit_File", "Phish_File"])

    processed_count = 0
    legit_cache = {}  # Cache for legitimate site crawls: {url: legit_dir_path}
    
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

        # Process each phishing URL
        for j, phish_url in enumerate(phish_urls):
            print(f"\n{'='*60}")
            print(f"Processing: {target} (Legitimate vs Phishing #{j+1})")
            print(f"  Legitimate: {legit_url}")
            print(f"  Phishing #{j+1}: {phish_url}")
            print(f"{'='*60}")
            
            # Create pair-specific output directory with clear naming
            # Format: {target}_vs_phish{index}
            safe_target = target.replace(' ', '_').replace('/', '_').replace('\\', '_')
            pair_name = f"{safe_target}_vs_phish{j+1}"
            pair_output = os.path.join(output_dir, pair_name)
            
            if os.path.exists(pair_output):
                import shutil
                shutil.rmtree(pair_output)
            os.makedirs(pair_output)
            
            legit_dir = os.path.join(pair_output, "legit")
            phish_dir = os.path.join(pair_output, "phish")
            os.makedirs(legit_dir)
            os.makedirs(phish_dir)

            try:
                # 1. Crawl or Copy Legitimate Site
                if legit_url in legit_cache:
                    # Use cached legitimate site data
                    print(f"\n>>> Using cached legitimate site data from: {legit_cache[legit_url]}")
                    import shutil
                    cached_legit_dir = legit_cache[legit_url]
                    
                    # Copy all files from cached directory to new legit directory
                    for item in os.listdir(cached_legit_dir):
                        src = os.path.join(cached_legit_dir, item)
                        dst = os.path.join(legit_dir, item)
                        if os.path.isfile(src):
                            shutil.copy2(src, dst)
                        elif os.path.isdir(src):
                            shutil.copytree(src, dst)
                    
                    print(f"  Copied {len(os.listdir(legit_dir))} items from cache")
                else:
                    # Crawl legitimate site for the first time
                    print("\n>>> Crawling Legitimate Site...")
                    run_command([
                        PYTHON_EXE, WEB_CRAWLER, legit_url,
                        "--output", legit_dir,
                        "--headless",
                        "--pages", "10",
                        "--scrolls", "3",
                        "--login-priority"
                    ])
                    
                    # Cache the legitimate site directory
                    legit_cache[legit_url] = legit_dir
                    print(f"  Cached legitimate site data for: {legit_url}")
                
                # 2. Crawl Phishing Site
                print("\n>>> Crawling Phishing Site...")
                run_command([
                    PYTHON_EXE, WEB_CRAWLER, phish_url,
                    "--output", phish_dir,
                    "--headless",
                    "--pages", "10",
                    "--scrolls", "3",
                    "--login-priority"
                ])

                # 3. Classify (run on pair_output, not individual folders)
                print("\n>>> Classifying...")
                run_command([PYTHON_EXE, CLASSIFY_SCRIPT, pair_output, "--tag-only"])

                # 4. Generate Hashes (same as manual workflow)
                print("\n>>> Generating Hashes...")
                
                # Run uihash on pair_output (parent of legit/ and phish/)
                hash_output_dir = os.path.join(pair_output, "hash")
                run_command([
                    PYTHON_EXE, UIHASH_SCRIPT, pair_output, "dummy",
                    "--output_path", hash_output_dir,
                    "--num_classes", "8",
                    "--grid_size", "10,5"
                ])
                
                # Check if hash files exist
                hash_path = os.path.join(hash_output_dir, "hash_10x5x8.npy")
                name_path = os.path.join(hash_output_dir, "name_10x5x8.npy")
                
                if not os.path.exists(hash_path) or not os.path.exists(name_path):
                    print("Error: Hash generation failed.")
                    with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([target, legit_url, phish_url, "N/A", "N/A", "Error (Hash Failed)", "", ""])
                    continue
                
                # Verify hash is not empty
                import numpy as np
                h = np.load(hash_path, allow_pickle=True)
                if len(h) == 0:
                    print(f"Error: Hash is empty (shape: {h.shape})")
                    with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([target, legit_url, phish_url, "N/A", "N/A", "Error (Empty Hash)", "", ""])
                    continue
                
                print(f"  Hash files generated: {hash_path} (samples: {len(h)})")

                # 5. Compare (no threshold filtering)
                print("\n>>> Comparing...")
                cmd = [
                    PYTHON_EXE, COMPARE_SCRIPT,
                    hash_path, name_path, MODEL_PATH,
                    "--hash_size", "8,10,5",
                    "--top", "100",  # Get more results to find best match
                    "--cross",
                    "--threshold", "-2.0",  # No threshold
                    "--max_dist", "100.0"  # No distance filtering
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                print(result.stdout)


                # Parse results and find best match
                pattern = r"(\d+)\. Score: ([\d\.\-]+) \(Dist: ([\d\.\-]+)\)\s+A: (.+)\s+B: (.+)"
                matches = re.findall(pattern, result.stdout)

                if not matches:
                    print("WARNING: No comparison results found!")
                    with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([target, legit_url, phish_url, "N/A", "N/A", "Error (No Results)", "", ""])
                    continue

                # Filter for legit vs phish pairs only (exclude legit vs legit and phish vs phish)
                cross_site_matches = []
                for rank, score, distance, file_a, file_b in matches:
                    # Check if one is from legit and the other from phish
                    is_a_legit = file_a.strip().startswith('legit')
                    is_b_legit = file_b.strip().startswith('legit')
                    is_a_phish = file_a.strip().startswith('phish')
                    is_b_phish = file_b.strip().startswith('phish')
                    
                    # Only include if one is legit and the other is phish
                    if (is_a_legit and is_b_phish) or (is_a_phish and is_b_legit):
                        cross_site_matches.append((rank, score, distance, file_a, file_b))
                
                if not cross_site_matches:
                    print("WARNING: No cross-site (legit vs phish) comparison results found!")
                    with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([target, legit_url, phish_url, "N/A", "N/A", "Error (No Cross-Site Results)", "", ""])
                    continue
                
                # Find best match from cross-site pairs: highest score, lowest distance
                # Sort by score DESC, then distance ASC
                best_match = sorted(cross_site_matches, key=lambda x: (-float(x[1]), float(x[2])))[0]
                
                rank, score, distance, file_a, file_b = best_match
                
                print(f"\n>>> Best cross-site match: Score={score}, Distance={distance}")
                print(f"    {file_a.strip()} <-> {file_b.strip()}")
                
                # Save to CSV
                with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([
                        target,
                        legit_url,
                        phish_url,
                        score,
                        distance,
                        file_a.strip(),
                        file_b.strip()
                    ])
                
                print(f"\n✓ Best Match: Score={score}, Distance={distance}")

            except Exception as e:
                print(f"Exception processing pair {i}-{j}: {e}")
                import traceback
                traceback.print_exc()
                with open(results_csv, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([target, legit_url, phish_url, "N/A", "N/A", f"Error ({str(e)})", "", ""])
        
        processed_count += 1

    print(f"\n{'='*60}")
    print(f"Evaluation Complete! Results saved to: {results_csv}")
    print(f"{'='*60}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate phishing pairs with simplified workflow")
    parser.add_argument("input", nargs="?", default=os.path.join(BASE_DIR, "phising.json"),
                        help="Input JSON file path (default: phising.json)")
    parser.add_argument("--output", type=str, default=os.path.join(BASE_DIR, "eval_output"),
                        help="Output directory (default: eval_output)")
    parser.add_argument("--start", type=int, default=0, help="Start index")
    parser.add_argument("--count", type=int, default=None, help="Max items to process")
    args = parser.parse_args()

    # Convert to absolute paths
    input_file = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output)
    
    print(f"Input: {input_file}")
    print(f"Output: {output_dir}")

    evaluate(input_file=input_file, output_dir=output_dir, start_index=args.start, max_count=args.count)
