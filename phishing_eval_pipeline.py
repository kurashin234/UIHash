
import os
import sys
import json
import time
import argparse
import csv
import logging
import shutil
from os.path import join, exists, abspath, dirname
from os import makedirs
from typing import List, Tuple, Dict
import numpy as np
import cv2
import torch
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Add project root to sys.path
curpath = abspath(dirname(__file__))
if curpath not in sys.path:
    sys.path.append(curpath)

# Import existing modules
# We wrap these in try-except to handle potential import issues if paths are slightly off,
# but since we are in root, they should work.
try:
    from hasher.extract_view_images import read_rico_json_nodes
    from hasher.reclass import ImgClassifier
    from hasher.nodes2hash import Nodes2Hash
    from mlalgos.siamese import SiameseModel
    from xml2nodes import XMLReader # Should be available via sys.path trick in original scripts, but we are in root
    # If xml2nodes is in hasher/, we might need to adjust.
    # Checking file structure: xml2nodes.py is in hasher/
    # But wait, in extract_view_images.py it says: from xml2nodes import XMLReader
    # and sys.path.append(rootpath).
    # If we run from root, we need to make sure we can import these.
    # Let's check where xml2nodes.py is.
    # Based on listing, it is in 'hasher'.
except ImportError:
    # Adjust path for imports if needed
    sys.path.append(join(curpath, 'hasher'))
    sys.path.append(join(curpath, 'mlalgos'))
    sys.path.append(join(curpath, 'util'))
    from hasher.extract_view_images import read_rico_json_nodes
    from hasher.reclass import ImgClassifier
    from hasher.nodes2hash import Nodes2Hash
    from hasher.xml2nodes import XMLReader
    from hasher.classify_web import TAG_MAP # Import TAG_MAP
    from mlalgos.siamese import SiameseModel

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("phishing_eval.log")
    ]
)
logger = logging.getLogger(__name__)

def setup_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    # Try to use webdriver_manager
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        logger.error(f"Failed to setup driver with webdriver_manager: {e}")
        # Fallback for some environments where chrome might be in path
        driver = webdriver.Chrome(options=options)
    return driver

def scroll_page(driver):
    """Scroll down 3 times to capture more content."""
    for _ in range(3):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

def extract_dom_to_rico(driver, output_dir, file_prefix):
    """Extract DOM and save as Rico JSON."""
    dom_script = """
    var all = document.getElementsByTagName("*");
    var elements = [];
    for (var i=0, max=all.length; i < max; i++) {
        var el = all[i];
        var rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            var style = window.getComputedStyle(el);
            if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                var label = el.tagName;
                 elements.push({
                    "bounds": [rect.left, rect.top, rect.right, rect.bottom],
                    "componentLabel": label + "_" + i,
                    "children": [] 
                });
            }
        }
    }
    return elements;
    """
    try:
        elements = driver.execute_script(dom_script)
        rico_json = {
            "activity": {
                "root": {
                    "children": elements
                }
            }
        }
        json_path = join(output_dir, f"{file_prefix}.json")
        with open(json_path, 'w') as f:
            json.dump(rico_json["activity"]["root"], f)
        return json_path
    except Exception as e:
        logger.error(f"DOM extraction failed: {e}")
        return None

def crawl_target(driver, start_url, output_root, max_pages=10):
    """
    Crawl up to max_pages from start_url.
    Prioritize login links.
    Save each page to output_root/page_N/
    """
    logger.info(f"Crawling target: {start_url} (Max {max_pages} pages)")
    
    visited_urls = set()
    queue = [start_url]
    pages_captured = 0
    
    # Store captured page paths
    captured_pages = []
    
    while queue and pages_captured < max_pages:
        url = queue.pop(0)
        if url in visited_urls:
            continue
        visited_urls.add(url)
        
        try:
            logger.info(f"Visiting ({pages_captured+1}/{max_pages}): {url}")
            driver.get(url)
            time.sleep(3)
            
            # Scroll
            scroll_page(driver)
            time.sleep(1)
            
            # Setup Page Directory
            page_dir = join(output_root, f"page_{pages_captured}")
            if not exists(page_dir):
                makedirs(page_dir)
            
            # Capture
            screenshot_path = join(page_dir, "screenshot.png")
            driver.save_screenshot(screenshot_path)
            json_path = extract_dom_to_rico(driver, page_dir, "view_hierarchy") # Standard name inside page dir
            
            if json_path and exists(screenshot_path):
                 captured_pages.append(page_dir)
                 pages_captured += 1
            
            # Collect Links for next steps
            if pages_captured < max_pages:
                try:
                    elems = driver.find_elements(By.TAG_NAME, "a")
                    new_links = []
                    for el in elems:
                        href = el.get_attribute("href")
                        if href and href.startswith("http") and href not in visited_urls:
                            # Prioritize Login
                            if any(k in href.lower() or (el.text and k in el.text.lower()) for k in ['login', 'sign in', 'signin', 'account']):
                                queue.insert(0, href) # BFS Priority
                            else:
                                new_links.append(href)
                    
                    # Add non-priority links to end (BFS)
                    # Shuffle new_links for randomness? User said "random"
                    import random
                    random.shuffle(new_links)
                    queue.extend(new_links)
                    
                except Exception as e:
                    logger.warning(f"Link extraction error: {e}")

        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
    
    return captured_pages

def process_page_folder(page_dir, hasher):
    """
    Process a single page directory:
    1. Read view_hierarchy.json
    2. Generate classify.txt based on Tags (no images)
    3. Calculate Hash using classify.txt (Nodes2Hash)
    """
    json_path = join(page_dir, "view_hierarchy.json")
    png_path = join(page_dir, "screenshot.png")
    
    if not exists(json_path) or not exists(png_path):
        return None

    try:
        # Load JSON
        with open(json_path, 'r') as f:
            jo = json.load(f)
            
        # Extract Views
        views = []
        read_rico_json_nodes(views, jo)
        
        # Generate classify.txt content
        # Format: {"0_tag": class_id, "1_tag": class_id, ...}
        classify_dict = {}
        
        nodes_for_hash = []
        
        # We need image dims for clipping
        img = cv2.imread(png_path)
        if img is None: return None
        h, w, _ = img.shape
        
        for idx, n in enumerate(views):
            w1, h1, w2, h2, label_raw = n
            w1, h1, w2, h2 = int(w1), int(h1), int(w2), int(h2)
            
            w1, w2 = max(0, min(w1, w)), max(0, min(w2, w))
            h1, h2 = max(0, min(h1, h)), max(0, min(h2, h))
             
            if w2 <= w1+1 or h2 <= h1+1: continue
            
            # Tag Logic
            tag_name = label_raw.split('_')[0].lower()
            pred_id = TAG_MAP.get(tag_name, 7) # Default Other
            
            # Add to classify dict
            # Key format used by Nodes2Hash typically: "{index}_{class}" or just unique string?
            # Looking at Nodes2Hash: key.split('_', 1) -> index, original_type
            # So key should be f"{idx}_{label_raw}"
            # And value should be pred_id
            
            key = f"{idx}_{label_raw}"
            classify_dict[key] = pred_id
            
            # We also need to construct nodes list for hashing or let Nodes2Hash read the file
            # If we create classify.txt, Nodes2Hash can read it.
            # But we can also pass 'nodes' explicitly with 'name' set to predicted ID to skip file read/parsing if we want.
            # However, user explicitly asked to "generate classify.txt file".
            
            nodes_for_hash.append({
                'name': str(pred_id), # Pass ID string as name, our patched Nodes2Hash handles this
                'lt': (w1, h1),
                'rb': (w2, h2)
            })
            
        # Save classify.txt
        classify_path = join(page_dir, "classify.txt")
        with open(classify_path, 'w') as f:
            f.write(str(classify_dict))
            
        # Generate Hash
        # We pass nodes_for_hash so it doesn't need to re-parse.
        # And since we patched Nodes2Hash to allow missing classify.txt if names are int,
        # OR if classify.txt exists it uses it.
        # Since we just wrote classify.txt, standard logic works too.
        # But passing nodes is faster.
        hash_vec = hasher.gen_uihash(json_path, nodes_for_hash)
        
        return hash_vec

    except Exception as e:
        logger.error(f"Error processing {page_dir}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('json_config', help="Path to phising.json")
    parser.add_argument('--output', '-o', default='output_eval_web', help="Output directory")
    parser.add_argument('--test', action='store_true', help="Run only first item")
    parser.add_argument('--skip-crawl', action='store_true', help="Skip crawling if data exists")
    parser.add_argument('--mock-crawl', action='store_true', help="Mock crawling for testing")
    args = parser.parse_args()
    
    with open(args.json_config, 'r') as f:
        targets = json.load(f)
        
    if args.test:
        targets = targets[:1]
        
    capture_dir = join(args.output, 'capture')
    pairs_dir = join(args.output, 'pairs')
    if not exists(capture_dir): makedirs(capture_dir)
    if not exists(pairs_dir): makedirs(pairs_dir)
    
    # Setup Driver
    if not args.skip_crawl and not args.mock_crawl:
        driver = setup_driver()
    else:
        driver = None
    
    # Setup Models
    # Paths (Hardcoded based on system exploration)
    project_root = curpath
    dataset_path = join(project_root, "output_web_train", "dataset") # Contains class folders
    # Check if dataset exists, if not we might fallback or fail
    if not exists(dataset_path):
        logger.warning(f"Dataset path {dataset_path} not found. Reclassification might fail if classes unknown.")
    
    # Classifier
    # Checkpoint inspection to determine number of classes
    model_path = join(project_root, "models", "reclass_e30_128.tar") # verified existence
    if not exists(model_path):
        logger.error("Reclass model not found!")
        return

    try:
        # Load state dict to infer classes
        state = torch.load(model_path, map_location='cpu')
        num_classes = state['resnet.fc.weight'].shape[0]
        logger.info(f"Inferred {num_classes} classes from checkpoint")
    except Exception as e:
        logger.error(f"Failed to inspect checkpoint: {e}")
        return

    # Monkeypatch ImgDataSet to use inferred class num (avoiding empty dataset issue)
    from hasher import reclass
    class MockDataSet:
        def __init__(self, path):
            self.class_num = num_classes
            self.class_names = [str(i) for i in range(num_classes)]
            self.data = []
        def __len__(self): return 0
        def __getitem__(self, idx): return None
        
    original_dataset_cls = reclass.ImgDataSet
    reclass.ImgDataSet = MockDataSet
    
    try:
        classifier = ImgClassifier(dataset_path, epoch=30, batch_size=128, confidence_threshold=0.95)
        logger.info(f"Loading reclass model from {model_path}")
        classifier.net.load_state_dict(state)
        classifier.net.to('cpu')
    finally:
        reclass.ImgDataSet = original_dataset_cls # Restore


    # Load Siamese Model
    siamese_model_path = join(project_root, "models", "siamese_e30_32_5x10.tar")
    # Hash size 5x10 (10 channels?) -> Wait, file is 5x10.
    # SiameseModel init args: hash_size=(10, 5, 5) ? 
    # Filename suggests 5x10. usually (channels, h, w).
    # Let's check siamese.py defaults: (10, 5, 5).
    # If filename is siamese_e30_32_5x10.tar, it likely matches hash_size=(10, 5, 10)? OR (10,5,5)?
    # Looking at directory list: siamese_e30_32_5x10.tar
    # The code constructs filename: f"siamese_e{self.epoch}_{self.batch_size}_{hash_size[1]}x{hash_size[2]}.tar"
    # So hash_size[1]=5, hash_size[2]=10.
    # So we should init SiameseModel with hash_size=(10, 5, 10).
    
    siamese = SiameseModel(hash_size=(8, 5, 10), epoch=30, batch_size=32, load_labelled_dataset=False)
    if exists(siamese_model_path):
        logger.info(f"Loading siamese model from {siamese_model_path}")
        siamese.net.load_state_dict(torch.load(siamese_model_path, map_location='cpu'))
        siamese.net.to('cpu')
        siamese.net.eval()
    else:
        logger.error("Siamese model not found!")
        return

    # Hasher
    # We must match Siamese input channels (8) even if classifier has fewer classes
    # Siamese model expects 5x10 (HxW). So we need Nodes2Hash to produce W=10, H=5.
    # Nodes2Hash args are (h_tick, v_tick) -> (10, 5)
    hasher = Nodes2Hash((10, 5), 8)
    
    results = []
    
    for i, target in enumerate(targets):
        target_name = target.get('target', f'target_{i}')
        legit_url = target.get('legitimate_url')
        phish_urls = target.get('phishing_urls', [])
        
        logger.info(f"Processing Target: {target_name}")
        
        # 1. Crawl/Process Legit
        legit_id = f"legit_{i}"
        
        if args.mock_crawl:
            # Generate dummy data
            dummy_json = join(capture_dir, f"{legit_id}.json")
            dummy_png = join(capture_dir, f"{legit_id}.png")
            if not exists(dummy_json):
                with open(dummy_json, 'w') as f:
                     # Minimal Rico JSON
                     json.dump({"children": []}, f)
            if not exists(dummy_png):
                # Black image
                cv2.imwrite(dummy_png, np.zeros((100, 100, 3), dtype=np.uint8))
        elif not args.skip_crawl:
            capture_url(driver, legit_url, capture_dir, legit_id)
        
        if args.skip_crawl:
            logger.info("Skipping crawl, using existing data")
        
        # Process Views and Hash (Tag-Only default)
        legit_hash = process_capture(capture_dir, legit_id, classifier, hasher, (5, 10), tag_only=True)
        
        if legit_hash is not None:
             # Reshape to (C, H, W) for Siamese model
             # Output of hasher is (C, H*W). We need (8, 5, 10).
             try:
                legit_hash = legit_hash.reshape(8, 5, 10)
             except Exception as e:
                logger.error(f"Reshape failed: {e}")
                legit_hash = None
        
        if legit_hash is None:
            logger.warning(f"Failed to hash legit URL {legit_url}")
        for i, target in enumerate(targets):
            target_name = target.get('target', f'target_{i}')
            legit_url = target.get('legitimate_url')
            phish_urls = target.get('phishing_urls', [])
            
            logger.info(f"Processing Target: {target_name}")
            
            # === CRAWL LEGIT ===
            legit_capture_root = join(args.output, "capture", f"legit_{i}")
            legit_pages = []
            
            if not args.skip_crawl:
                 legit_pages = crawl_target(driver, legit_url, legit_capture_root, max_pages=10)
            else:
                 # If skipping crawl, assume directories exist
                 if exists(legit_capture_root):
                     legit_pages = [join(legit_capture_root, d) for d in os.listdir(legit_capture_root) if d.startswith('page_')]
            
            # Process Legit Hashes
            legit_hashes = []
            for p_dir in legit_pages:
                 h = process_page_folder(p_dir, classifier, hasher, (5, 10), tag_only=True)
                 if h is not None:
                      try:
                          h = h.reshape(8, 5, 10)
                          legit_hashes.append((p_dir, h))
                      except: pass
            
            if not legit_hashes:
                 logger.warning(f"No valid hashes for legit target {target_name}. Using Dummy if mock.")
                 if args.mock_crawl:
                     legit_hashes.append(("mock_legit", np.random.rand(8, 5, 10)))

            # === PROCESS PHISHING TARGETS ===
            for j, p_url in enumerate(target.get('phishing_urls', [])):
                phish_capture_root = join(args.output, "capture", f"phish_{i}_{j}")
                phish_pages = []
                
                if not args.skip_crawl:
                    phish_pages = crawl_target(driver, p_url, phish_capture_root, max_pages=10)
                else:
                     if exists(phish_capture_root):
                         phish_pages = [join(phish_capture_root, d) for d in os.listdir(phish_capture_root) if d.startswith('page_')]
                
                phish_hashes = []
                for p_dir in phish_pages:
                    h = process_page_folder(p_dir, classifier, hasher, (5, 10), tag_only=True)
                    if h is not None:
                        try:
                            h = h.reshape(8, 5, 10)
                            phish_hashes.append((p_dir, h))
                        except: pass
                
                if args.mock_crawl and not phish_hashes:
                     phish_hashes.append(("mock_phish", np.random.rand(8, 5, 10)))
                
                # === CROSS COMPARE ===
                best_score_cos = -1.0
                best_score_euc = 9999.0
                best_pair_paths = (None, None)
                
                if not legit_hashes or not phish_hashes:
                    logger.warning(f"Skipping comparison for {p_url} due to missing data")
                    continue

                for l_path, l_hash in legit_hashes:
                    for p_path, p_hash in phish_hashes:
                        # Siamese Forward
                        h1 = torch.from_numpy(l_hash).float().unsqueeze(0).to(siamese.device)
                        h2 = torch.from_numpy(p_hash).float().unsqueeze(0).to(siamese.device)
                        
                        with torch.no_grad():
                            o1, o2 = siamese._forward(h1, h2)
                            o1 = torch.squeeze(o1, 0)
                            o2 = torch.squeeze(o2, 0)
                            
                            d_cos = torch.cosine_similarity(o1, o2, dim=0)
                            d_euc = torch.pairwise_distance(o1.unsqueeze(0), o2.unsqueeze(0), p=2)
                            
                            sc = d_cos.item()
                            se = d_euc.item()
                            
                            # Logic: We want MAX Cosine Similarity (closest to 1) 
                            # or MIN Euclidean Distance (closest to 0).
                            # Usually they correlate. Let's pick based on Cosine.
                            if sc > best_score_cos:
                                best_score_cos = sc
                                best_score_euc = se
                                best_pair_paths = (l_path, p_path)

                logger.info(f"Best Match {p_url}: Cos={best_score_cos}, Euc={best_score_euc}")
                
                # Save Result
                res_entry = {
                    'Target': target_name,
                    'LegitURL': legit_url,
                    'PhishURL': p_url,
                    'Score': best_score_cos,
                    'Euclidean': best_score_euc,
                    'LegitImg': "see_pairs",
                    'PhishImg': "see_pairs"
                }
                
                if best_pair_paths[0] and best_pair_paths[1]:
                    # Copy images to pairs dir and annotate
                    try:
                        l_img_src = join(best_pair_paths[0], "screenshot.png")
                        p_img_src = join(best_pair_paths[1], "screenshot.png")
                        
                        if exists(l_img_src) and exists(p_img_src):
                            l_img = cv2.imread(l_img_src)
                            p_img = cv2.imread(p_img_src)
                            
                            # Resize to match height
                            h = min(l_img.shape[0], p_img.shape[0])
                            l_r = cv2.resize(l_img, (int(l_img.shape[1] * h / l_img.shape[0]), h))
                            p_r = cv2.resize(p_img, (int(p_img.shape[1] * h / p_img.shape[0]), h))
                            
                            combined = np.hstack((l_r, p_r))
                            cv2.putText(combined, f"Cos: {best_score_cos:.4f} Euc: {best_score_euc:.4f}", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                            
                            pair_filename = f"pair_{i}_{j}.jpg"
                            cv2.imwrite(join(pairs_dir, pair_filename), combined)
                            res_entry['LegitImg'] = best_pair_paths[0]
                            res_entry['PhishImg'] = best_pair_paths[1]
                    except Exception as e:
                        logger.error(f"Error saving pair image: {e}")

                results.append(res_entry)

    if not args.skip_crawl and not args.mock_crawl and driver:
        driver.quit()
        
    # Write CSV
    csv_path = join(args.output, "phishing_eval_results.csv")
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Target', 'LegitURL', 'PhishURL', 'Score', 'Euclidean', 'LegitImg', 'PhishImg'])
        writer.writeheader()
        writer.writerows(results)
    
    logger.info(f"Done. Results saved to {csv_path}")

if __name__ == "__main__":
    main()
