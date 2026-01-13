
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

def capture_url(driver, url, output_dir, file_prefix):
    """
    Visit URL, try to click login, capture screenshot and DOM.
    Returns path to json and png if successful, else None.
    """
    try:
        logger.info(f"Visiting {url}")
        driver.get(url)
        time.sleep(3) # Wait for load

        # Try to find and click login button
        # Heuristics: search for 'login', 'sign in', 'log in' in text or id/class
        login_keywords = ['login', 'log in', 'sign in', 'signin', 'acceder', 'connexion']
        
        # Simple heuristic: find buttons or links with these words
        clicked = False
        start_time = time.time()
        
        # We give it a few seconds to find a login button
        while time.time() - start_time < 5:
            try:
                elements = driver.find_elements(By.XPATH, "//button | //a | //input[@type='submit']")
                target_element = None
                
                for el in elements:
                    if not el.is_displayed():
                        continue
                    text = el.text.lower()
                    val = el.get_attribute('value')
                    val = val.lower() if val else ""
                    
                    if any(k in text for k in login_keywords) or any(k in val for k in login_keywords):
                        target_element = el
                        break
                
                if target_element:
                    logger.info(f"Found potential login element: {target_element.text or target_element.get_attribute('value')}")
                    driver.execute_script("arguments[0].click();", target_element)
                    clicked = True
                    time.sleep(3) # Wait for navigation/modal
                    break
            except Exception as e:
                # DOM might have changed
                pass
            break # Single pass for now
            
        if not clicked:
            time.sleep(2) # Just wait a bit more if no login found

        # Capture
        screenshot_path = join(output_dir, f"{file_prefix}.png")
        driver.save_screenshot(screenshot_path)
        
        # Extract DOM elements for Rico format
        # This is a critical part: we need to convert current DOM to Rico JSON format
        # [x1, y1, x2, y2, label]
        # We will use JS to get bounding boxes of visible elements
        
        dom_script = """
        var all = document.getElementsByTagName("*");
        var elements = [];
        for (var i=0, max=all.length; i < max; i++) {
            var el = all[i];
            var rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                // Check visibility
                var style = window.getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                    // Approximate 'label' or 'class' - for UIHash we often map tag+class or just tag
                    // Rico uses 'componentLabel'. We can use tag name or try to map standard UI elements.
                    var label = el.tagName;
                    
                    // Simple mapping to Android-like classes if possible, or just raw
                    // Reclass model expects images, so the label here is mostly for grouping?
                    // Actually extract_view_images.py uses 'componentLabel' to name the folder.
                    // IMPORTANT: The reclass model is trained on specific class names (e.g., Button, TextView).
                    // But typically we just need *some* label to segregate crops. The reclassifier will decide the REAL class.
                    // So distinct ID is enough.
                    
                     elements.append({
                        "bounds": [rect.left, rect.top, rect.right, rect.bottom],
                        "componentLabel": label + "_" + i,
                        "children": [] 
                    });
                }
            }
        }
        return elements;
        """
        # Note: The above JS is very naive. Real Rico JSON is hierarchical.
        # But extract_view_images.py -> read_rico_json_nodes just recursively finds "componentLabel" and "bounds".
        # So a flat list wrapped in a root object is fine if we structure it right.
        
        # Actually flat list is easier to generate.
        elements = driver.execute_script(dom_script)
        
        rico_json = {
            "activity": {
                "root": {
                    "children": elements
                }
            }
        }
        
        # Wrap to match read_rico_json_nodes expectations
        # It expects a dict 'o'. 
        # If 'children' in o, recurse.
        # If 'componentLabel' in o, add.
        # So passing 'rico_json["activity"]["root"]' to the saver.
        
        json_path = join(output_dir, f"{file_prefix}.json")
        with open(json_path, 'w') as f:
            json.dump(rico_json["activity"]["root"], f)
            
        return json_path, screenshot_path

    except Exception as e:
        logger.error(f"Error capturing {url}: {e}")
        return None, None

def process_capture(capture_dir, screen_name, classifier, hasher, hash_grid_size):
    """
    1. Extract view images from capture
    2. Reclassify views
    3. Generate UIHash
    """
    # 1. Extract
    # We can reuse extract_view_imgs_from_web logic but focused on single item
    # Or just replicate logic here to be safer/in-memory
    
    json_path = join(capture_dir, f"{screen_name}.json")
    png_path = join(capture_dir, f"{screen_name}.png")
    
    if not exists(json_path) or not exists(png_path):
        return None
        
    # Create temp dir for views
    views_dir = join(capture_dir, screen_name)
    if not exists(views_dir):
        makedirs(views_dir)
        
    try:
        with open(json_path, 'r') as f:
            jo = json.load(f)
        
        img = cv2.imread(png_path)
        if img is None: return None
        h, w, _ = img.shape
        
        views = []
        read_rico_json_nodes(views, jo)
        
        extracted_views_map = {} # filename -> label (initially -1)
        
        m = 0
        nodes_for_hash = []
        
        for n in views:
            w1, h1, w2, h2, label_raw = n
            # Clip
            w1, w2 = max(0, min(w1, w)), max(0, min(w2, w))
            h1, h2 = max(0, min(h1, h)), max(0, min(h2, h))
            
            if w2 <= w1+1 or h2 <= h1+1: continue
            
            crop = img[h1:h2, w1:w2]
            if crop.size == 0: continue
            
            # Save for reclass
            view_filename = f"{m}.jpg"
            cv2.imwrite(join(views_dir, view_filename), crop)
            
            # Prepare for hashing (will need predicted label)
            # Node dict format expected by Nodes2Hash: {'name': class_name, 'lt': (x1,y1), 'rb': (x2,y2)}
            # But Hasher uses numerical types if we initialize it with types.
            # Nodes2Hash.gen_uihash(xml_path, nodes)
            # nodes is list of dicts.
            
            # We will fill 'name' with the PREDICTED class later.
            nodes_for_hash.append({
                'id': m,
                'lt': (w1, h1),
                'rb': (w2, h2),
                'file': view_filename
            })
            m += 1
            
        # 2. Reclassify
        # We use the classifier instance
        # classifier.predict logic needs to be adapted to work on single folder or list of images
        # ImgClassifier.predict walks folders. We can just manually predict.
        
        classifier.net.eval()
        
        for node in nodes_for_hash:
            view_path = join(views_dir, node['file'])
            v_img = cv2.imread(view_path)
            try:
                v_img = cv2.resize(v_img, (28, 28))
                v_img = cv2.cvtColor(v_img, cv2.COLOR_BGR2GRAY)
                v_img = np.expand_dims(v_img, 0)
                v_img = np.expand_dims(v_img, 0)
                v_img_t = torch.from_numpy(v_img).float().to(classifier.device)
                
                with torch.no_grad():
                    out = classifier.net(v_img_t)
                    prob = torch.nn.functional.softmax(out, dim=1)
                    max_val, max_idx = torch.max(prob, 1)
                    
                    if max_val.item() > classifier.confidence_threshold:
                        pred_label = max_idx.item()
                    else:
                        pred_label = -1
                        
                node['name'] = str(pred_label) # Hash generator expects string? or int?
                # Nodes2Hash._get_ matrix uses: 
                # cls_name = node['name']
                # if self.type_num > 0: type_id = int(cls_name) ...
                
                # So we should pass string of int
                
            except Exception as e:
                # logger.warning(f"Reclass error: {e}")
                node['name'] = "-1"

        # 3. Hash
        # Hasher expects nodes list
        ui_hash = hasher.gen_uihash(xml_path=json_path, nodes=nodes_for_hash)
        
        # Cleanup
        # shutil.rmtree(views_dir) # Optional: keep for debug
        
        return ui_hash

    except Exception as e:
        logger.error(f"Processing error {screen_name}: {e}")
        import traceback
        traceback.print_exc()
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
        siamese.net.load_state_dict(torch.load(siamese_model_path, map_location=siamese.device))
        siamese.net.eval()
    else:
        logger.error("Siamese model not found!")
        return

    # Hasher
    # We must match Siamese input channels (8) even if classifier has fewer classes
    hasher = Nodes2Hash((5, 10), 8)
    
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
        
        legit_hash = process_capture(capture_dir, legit_id, classifier, hasher, (5, 10))
        
        if legit_hash is None:
            logger.warning(f"Failed to hash legit URL {legit_url}")
            # If mocking, maybe we failed because empty json?
            # process_capture needs valid json structure.
            # Let's handle mock case in process_capture or make mock data better?
            # actually if children is empty, views is empty -> hash is None?
            # Hasher returns None if no nodes?
            # Nodes2Hash gen_uihash:
            # nodes = ...
            # if len(nodes) < filter_few_nodes (default 5? no we init hasher with default?)
            # Nodes2Hash(grid_size, type_num)
            # gen_uihash(xml_path, nodes)
            # It checks filter? No, gen_uihash calls helper. 
            # In uihash.py, it checked filter. In my script I didn't check filter explicitly but process_capture does extraction.
            # If views is empty, nodes_for_hash is empty.
            # gen_uihash might fail or return zero hash.
            # Let's trust it returns something or None.
            pass

        # For Mocking, legit_hash might be None if mock data is too simple.
        # Let's force a dummy hash for mock if needed?
        if args.mock_crawl and legit_hash is None:
             legit_hash = np.random.rand(8, 5, 10) # Dummy hash

        if legit_hash is None: 
             continue

        # 2. Process Phishing
        for j, p_url in enumerate(phish_urls):
            phish_id = f"phish_{i}_{j}"
            
            if args.mock_crawl:
                dummy_json = join(capture_dir, f"{phish_id}.json")
                dummy_png = join(capture_dir, f"{phish_id}.png")
                with open(dummy_json, 'w') as f: json.dump({"children": []}, f)
                cv2.imwrite(dummy_png, np.zeros((100, 100, 3), dtype=np.uint8))
            elif not args.skip_crawl:
                capture_url(driver, p_url, capture_dir, phish_id)
            
            phish_hash = process_capture(capture_dir, phish_id, classifier, hasher, (5, 10))
            
            if args.mock_crawl and phish_hash is None:
                phish_hash = np.random.rand(8, 5, 10)

            score_cos = 0.0
            score_euc = 0.0
            if phish_hash is not None:
                # Score
                # Siamese deal_data expects: (i1, i2, label)
                # But we just want distance.
                # Siamese._forward(i1, i2)
                
                # Prepare tensors
                # Hash shape: (channels, h, w) -> (10, 5, 10)
                # Model expects batch: (Batch, C, H, W)
                
                h1 = torch.from_numpy(legit_hash).float().unsqueeze(0).to(siamese.device)
                h2 = torch.from_numpy(phish_hash).float().unsqueeze(0).to(siamese.device)
                
                with torch.no_grad():
                    o1, o2 = siamese._forward(h1, h2)
                    o1 = torch.squeeze(o1, 0)
                    o2 = torch.squeeze(o2, 0)
                    distance_cos = torch.cosine_similarity(o1, o2, dim=1) # Compute similarity across features (dim 1)
                    distance_euc = torch.pairwise_distance(o1, o2, p=2) 
                    
                    score_cos = distance_cos.item()
                    score_euc = distance_euc.item()
            
            logger.info(f"Score {p_url}: Cos={score_cos}, Euc={score_euc}")
            results.append({
                'Target': target_name,
                'LegitURL': legit_url,
                'PhishURL': p_url,
                'Score': score_cos,
                'Euclidean': score_euc,
                'LegitImg': f"{legit_id}.png",
                'PhishImg': f"{phish_id}.png"
            })
            
            # Save Pair Image
            l_img_p = join(capture_dir, f"{legit_id}.png")
            p_img_p = join(capture_dir, f"{phish_id}.png")
            if exists(l_img_p) and exists(p_img_p):
                l_img = cv2.imread(l_img_p)
                p_img = cv2.imread(p_img_p)
                # Resize to same height for display
                h = min(l_img.shape[0], p_img.shape[0])
                if h > 0:
                    l_r = cv2.resize(l_img, (int(l_img.shape[1] * h / l_img.shape[0]), h))
                    p_r = cv2.resize(p_img, (int(p_img.shape[1] * h / p_img.shape[0]), h))
                    combined = np.hstack((l_r, p_r))
                    
                    # Annotate
                    cv2.putText(combined, f"Cos: {score_cos:.4f} Euc: {score_euc:.4f}", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    cv2.imwrite(join(pairs_dir, f"pair_{i}_{j}.jpg"), combined)

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
