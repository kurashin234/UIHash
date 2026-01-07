
import os
import sys
import numpy as np
from itertools import combinations
import argparse

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def generate_siamese_web_dataset(hash_path_prefix, output_dataset_name="WebSiamese"):
    """
    Generate Positive and Negative pairs from hash files.
    hash_path_prefix example: "output_web/hash/hash_5x10x8" (without .npy)
    """
    
    hash_file = f"{hash_path_prefix}.npy"
    name_file = hash_path_prefix.replace("hash_", "name_") + ".npy"
    
    if not os.path.exists(hash_file) or not os.path.exists(name_file):
        print(f"Error: Hash files not found: {hash_file}")
        return

    print(f"Loading hashes from {hash_file}...")
    hashes = np.load(hash_file, allow_pickle=True)
    names = np.load(name_file, allow_pickle=True)
    
    print(f"Total samples: {len(names)}")
    
    # Group indices by Domain
    # Name format usually: "www_domain_com_timestamp/web_timestamp_scroll"
    # Or whatever uihash.py produced.
    # Let's assume the first part of the slash corresponds to the crawl session.
    # To find "Same Page", we need to strip the timestamp from the folder name?
    # Crawler format: domain_safe + "_" + timestamp.
    # Example: "www_yahoo_co_jp_1765680931" -> "www_yahoo_co_jp" is the domain.
    # We split by '_' and take everything up to the last digit part?
    # Or simply: remove the last underscore-separated number.
    
    domain_groups = {}
    
    def _extract_folder(name):
        if ' ' in name:
            folder = name.split(' ')[0]
        else:
            name = name.replace('\\', '/')
            parts = name.split('/')
            if len(parts) >= 2:
                folder = parts[-2]
            else:
                folder = os.path.dirname(name)
            if not folder:
                folder = name
        return folder

    domain_groups = {}
    
    for idx, name in enumerate(names):
        folder = _extract_folder(name)

        # folder is "www_google_com_12345"
        # We split by '_' to remove the trailing timestamp
        seg = folder.split('_')
        # Check if last part is digits (timestamp)
        if len(seg) > 1 and seg[-1].isdigit():
            domain = "_".join(seg[:-1])
        else:
            domain = folder
            
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(idx)
        
    print(f"Found {len(domain_groups)} unique domains.")
    
    # Generate Pairs
    positive_pairs = []
    negative_pairs = []
    
    # 1. Positive Pairs (Same Domain)
    for domain, indices in domain_groups.items():
        if len(indices) < 2:
            continue

        # Let's refine extraction: separate by Capture ID (Folder).
        captures = {} # folder -> [idx, scroll_id]
        for idx in indices:
            name = names[idx]
            folder = _extract_folder(name)
            
            # Extract scroll_id from filename portion
            # name might be "folder/file" or "folder file"
            if ' ' in name:
                filename = name.split(' ')[1]
            else:
                filename = os.path.basename(name)
                
            # filename: web_12345_1.json -> get '1'
            try:
                scroll_id = int(filename.split('_')[-1].split('.')[0])
            except:
                scroll_id = -1
                
            if folder not in captures:
                captures[folder] = []
            captures[folder].append((idx, scroll_id))
            
        # If we have >1 capture for this domain
        folder_list = list(captures.keys())
        if len(folder_list) < 2:
            print(f"Skipping {domain}: Only 1 capture session.")
            continue
            
        # Pair matching items between captures
        for f1, f2 in combinations(folder_list, 2):
            # Try to match scroll IDs
            c1_scrolls = {s: i for i, s in captures[f1]}
            c2_scrolls = {s: i for i, s in captures[f2]}
            
            common_scrolls = set(c1_scrolls.keys()) & set(c2_scrolls.keys())
            
            for s in common_scrolls:
                positive_pairs.append([c1_scrolls[s], c2_scrolls[s], 1]) # 1 = Similar

    # 2. Negative Pairs (Different Domains)
    # Collect all indices
    all_indices = list(range(len(names)))
    import random
    
    num_neg = len(positive_pairs) * 1  # Balance dataset 1:1 or 1:2?
    if num_neg == 0 and len(names) > 0:
        print("Warning: No positive pairs found. Generating random negatives only for testing?")
        num_neg = 100
        
    print(f"Generating {num_neg} negative pairs...")
    
    domains_list = list(domain_groups.keys())
    if len(domains_list) < 2:
        print("Error: Need at least 2 different domains for negative pairs.")
        pass # Can't make negatives if only 1 domain
        
    count = 0
    while count < num_neg:
        d1, d2 = random.sample(domains_list, 2)
        # Pick random view from each
        idx1 = random.choice(domain_groups[d1])
        idx2 = random.choice(domain_groups[d2])
        negative_pairs.append([idx1, idx2, 0]) # 0 = Dissimilar
        count += 1
        
    # Combine and Save
    all_pairs = positive_pairs + negative_pairs
    random.shuffle(all_pairs)
    
    print(f"Total Pairs: {len(all_pairs)} (Pos: {len(positive_pairs)}, Neg: {len(negative_pairs)})")
    
    # Save as NPZ
    # Format expected by LabelledDataSet:
    # keys: 'data', 'name'
    # data: list of [hash1, hash2, label] (Wait, LabelledDataSet expects this in .data?)
    # CHECK dataset.py:
    # self.data = np.load...
    # sim_pairs = [[i[3], i[4], 1] for i in sim] (hash1, hash2, 1)
    
    # So we need to construct the actual data array with full hashes
    final_data = []
    final_names = []
    
    for p in all_pairs:
        idx1, idx2, label = p
        h1 = hashes[idx1]
        h2 = hashes[idx2]
        final_data.append([h1, h2, label])
        final_names.append([names[idx1], names[idx2], label]) # Meta info
        
    # Save directory
    output_dir = os.path.join(os.path.dirname(hash_path_prefix), "..", "dataset") # ../dataset
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
    # Filename format expected by siamese.py LabelledDataSet:
    # f"{npz_prefix}_{size_str}.npz"
    # We will let user specify prefix.
    # size_str is suffix of hash file (e.g. 5x10x8)
    # Extract size_str from input path
    # hash_path_prefix: "output_web/hash/hash_5x10x8"
    size_str = hash_path_prefix.split('_')[-1] # "5x10x8" (hopefully)
    
    save_path = os.path.join(output_dir, f"{output_dataset_name}_{size_str}.npz")
    
    np.savez(save_path, data=np.array(final_data, dtype=object), name=np.array(final_names, dtype=object))
    print(f"Saved dataset to {save_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("hash_prefix", help="Path prefix to hash file, e.g. output_web/hash/hash_5x10x8")
    parser.add_argument("--name", default="WebSiamese", help="Dataset name prefix")
    args = parser.parse_args()
    
    generate_siamese_web_dataset(args.hash_prefix, args.name)
