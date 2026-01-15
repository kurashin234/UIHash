import os
import csv
import json
import subprocess
import sys
import concurrent.futures
import glob
import numpy as np
import torch
import argparse
from urllib.parse import urlparse

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERIFIED_CSV = os.path.join(BASE_DIR, "../tranco/verified_1000.csv")
PHISHING_JSON = os.path.join(BASE_DIR, "phising.json")

# Scripts
WEB_CRAWLER = os.path.join(BASE_DIR, "collect", "web_crawler.py")
CLASSIFY_SCRIPT = os.path.join(BASE_DIR, "hasher", "classify_web.py")
UIHASH_SCRIPT = os.path.join(BASE_DIR, "hasher", "uihash.py")
MODEL_PATH = os.path.join(BASE_DIR, "models", "siamese_e30_32_5x10.tar")

# Output Directories
EVAL_CONTROL_DIR = os.path.join(BASE_DIR, "eval_control")
RANDOM_DIR = os.path.join(EVAL_CONTROL_DIR, "random")
LEGIT_DIR = os.path.join(EVAL_CONTROL_DIR, "legit")

PYTHON_EXE = sys.executable

# Constants
MAX_WORKERS = 4 # Parallel crawlers
PAGES = 10
SCROLLS = 3

def run_command(cmd, cwd=None, quiet=True):
    """Run via subprocess."""
    try:
        # if not quiet:
        #     print(f"Running: {' '.join(cmd)}")
        subprocess.check_call(cmd, cwd=cwd, stdout=subprocess.DEVNULL if quiet else None, stderr=subprocess.DEVNULL if quiet else None)
        return True
    except subprocess.CalledProcessError:
        return False

def crawl_site(url, output_dir):
    """Worker function to crawl a single site."""
    print(f"Crawling: {url}")
    # --headless is essential for parallel
    cmd = [PYTHON_EXE, WEB_CRAWLER, url, "--output", output_dir, "--headless", "--pages", str(PAGES), "--scrolls", str(SCROLLS)]
    success = run_command(cmd, quiet=True)
    if success:
        print(f"Done: {url}")
    else:
        print(f"Failed: {url}")
    return success

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def load_random_urls():
    if not os.path.exists(VERIFIED_CSV):
        print(f"Error: {VERIFIED_CSV} not found. Run sample_and_verify.py first.")
        return []
    urls = []
    with open(VERIFIED_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
             if 'url' in row:
                 urls.append(row['url'])
    return urls

def load_legit_urls():
    if not os.path.exists(PHISHING_JSON):
        print(f"Error: {PHISHING_JSON} not found.")
        return []
    with open(PHISHING_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    urls = []
    for entry in data:
        if entry.get('legitimate_url'):
            urls.append(entry['legitimate_url'])
    # Deduplicate
    return list(set(urls))

def generate_hashes(target_dir):
    """Run classify and uihash on a directory."""
    print(f"Generating hashes for {target_dir}...")
    
    # 1. Classify
    print("  Running Classify...")
    run_command([PYTHON_EXE, CLASSIFY_SCRIPT, target_dir, "--tag-only"], quiet=False)
    
    # 2. UIHash
    print("  Running UIHash...")
    # uihash.py takes input_path. If we pass the parent dir (e.g. random), it iterates all subdirs.
    # Output path also set to target_dir.
    # Using filter 1 to match evaluate_pairs logic
    run_command([PYTHON_EXE, UIHASH_SCRIPT, target_dir, "dummy", "--output_path", target_dir, "--num_classes", "8", "--grid_size", "10,5", "--naivexml", "--filter", "1"], quiet=False)
    
    hash_file = os.path.join(target_dir, "hash_10x5x8.npy")
    name_file = os.path.join(target_dir, "name_10x5x8.npy")
    
    if os.path.exists(hash_file) and os.path.exists(name_file):
        return hash_file, name_file
    else:
        print(f"Error: Hash generation failed for {target_dir}")
        return None, None

def compare_hashes(legit_h_path, legit_n_path, random_h_path, random_n_path, output_csv):
    """Compare Legit hashes against Random hashes."""
    print("Loading models and data for comparison...")
    
    # Imports for Model
    sys.path.append(os.path.join(BASE_DIR)) # for mlalgos
    from mlalgos.network import SiameseNet, NNParas
    
    device = torch.device("cpu") # use cpu for simple comparison or cuda if avail
    if torch.cuda.is_available():
        device = torch.device("cuda")

    # Load Model ( Hardcoded 8,5,10 logic from compare_siamese.py )
    c = 8
    cnn = NNParas(c).cnn5x10
    fc = NNParas(c).fc5x10
    net = SiameseNet(cnn, fc).to(device)
    
    if not os.path.exists(MODEL_PATH):
        print("Model not found.")
        return
        
    net.load_state_dict(torch.load(MODEL_PATH, map_location=device))
    net.eval()
    
    # Load Data
    l_hashes = np.load(legit_h_path, allow_pickle=True)
    l_names = np.load(legit_n_path, allow_pickle=True)
    
    r_hashes = np.load(random_h_path, allow_pickle=True)
    r_names = np.load(random_n_path, allow_pickle=True)
    
    # Reshape (N, 8, 5, 10) or (N, 8, 10, 5) depending on save format.
    # Assuming standard flow typically saves (N, 8, 10, 5) but model expects (N, 8, 5, 10) maybe?
    # Let's try reshape to (N, 8, 10, 5) first.
    try:
        l_hashes = l_hashes.reshape(len(l_hashes), 8, 10, 5)
        r_hashes = r_hashes.reshape(len(r_hashes), 8, 10, 5)
    except:
        # Try swap if fail
        l_hashes = l_hashes.reshape(len(l_hashes), 8, 5, 10)
        r_hashes = r_hashes.reshape(len(r_hashes), 8, 5, 10)
        
    l_tensor = torch.from_numpy(l_hashes).float().to(device)
    r_tensor = torch.from_numpy(r_hashes).float().to(device)
    
    print(f"Comparing {len(l_names)} Legit vs {len(r_names)} Random...")
    
    results = []
    
    # Compare
    # Loop over legit (smaller set)
    with torch.no_grad():
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Legit_Site", "Random_Site", "Score", "Distance", "Rank_in_Random"])
            
            for i in range(len(l_names)):
                l_name = l_names[i]
                l_vec = l_tensor[i].unsqueeze(0) # (1, 8, 10, 5)
                
                # Expand l_vec to match r_tensor size
                l_vec_expanded = l_vec.expand(len(r_names), -1, -1, -1)
                
                # Forward pass - processing all randoms at once might be too heavy if 1000 is large
                # Batch it? 1000 is small enough for inference usually.
                
                # Prepare stack: (2, N, 8, 10, 5)
                combined = torch.stack((l_vec_expanded, r_tensor), 0)
                
                output = net(combined)
                o1, o2 = output[0], output[1]
                
                sim = torch.cosine_similarity(o1, o2, dim=1)
                
                # Euclidean
                t1_flat = l_vec_expanded.view(len(r_names), -1)
                t2_flat = r_tensor.view(len(r_names), -1)
                dist = torch.norm(t1_flat - t2_flat, dim=1)
                
                # Collect top matches for this legit site
                # We want to see if any random site looks like this legit site.
                # Sort by Score Desc
                
                scores = sim.cpu().numpy()
                dists = dist.cpu().numpy()
                
                # Create list of (score, dist, r_idx)
                site_results = []
                for j in range(len(r_names)):
                    site_results.append((scores[j], dists[j], j))
                
                site_results.sort(key=lambda x: x[0], reverse=True)
                
                # Save top 10 most similar random sites for this legit site
                for k in range(min(10, len(site_results))):
                    sc, dst, idx = site_results[k]
                    r_name = r_names[idx]
                    writer.writerow([l_name, r_name, f"{sc:.4f}", f"{dst:.4f}", k+1])
                    if k == 0:
                        print(f"Legit: {l_name} -> Top Random: {r_name} (Sc: {sc:.3f})")

def main():
    ensure_dir(EVAL_CONTROL_DIR)
    ensure_dir(RANDOM_DIR)
    ensure_dir(LEGIT_DIR)
    
    # 1. URLs
    rand_urls = load_random_urls()
    legit_urls = load_legit_urls()
    
    print(f"Loaded {len(rand_urls)} Random URLs, {len(legit_urls)} Legit URLs.")
    
    if not rand_urls:
         print("No random URLs. Aborting.")
         return
         
    # 2. Crawl Random (Parallel)
    # Check if already crawled to avoid re-doing 16 hours of work
    existing_random = len(os.listdir(RANDOM_DIR))
    if existing_random < len(rand_urls):
        print(f"Starting Crawl for {len(rand_urls)} Random sites with {MAX_WORKERS} workers...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            full_list = [(url, RANDOM_DIR) for url in rand_urls]
            executor.map(lambda p: crawl_site(*p), full_list)
    else:
        print("Random sites appear to be already crawled (skipping).")

    # 3. Crawl Legit
    # Check if we can reuse cache from eval_output/cache_legit?
    # For now, let's crawl fresh or rely on user copying.
    # Actually, legit sites are few (~10-20?). Parallel crawl is fast.
    print(f"Starting Crawl for {len(legit_urls)} Legit sites...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        full_list = [(url, LEGIT_DIR) for url in legit_urls]
        executor.map(lambda p: crawl_site(*p), full_list)
        
    # 4. Hash
    r_h, r_n = generate_hashes(RANDOM_DIR)
    l_h, l_n = generate_hashes(LEGIT_DIR)
    
    if not (r_h and l_h):
        print("Hashing failed.")
        return
        
    # 5. Compare
    output_csv = os.path.join(EVAL_CONTROL_DIR, "control_results.csv")
    compare_hashes(l_h, l_n, r_h, r_n, output_csv)
    print(f"Control Experiment Complete. Results: {output_csv}")

if __name__ == "__main__":
    main()
