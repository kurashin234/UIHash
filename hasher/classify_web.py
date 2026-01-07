
import os
import sys
import json
import cv2
import torch
import numpy as np
import argparse
from glob import glob

# Add current directory to path to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from reclass import ImgNet
except ImportError:
    # If running from root, hasher.reclass
    from hasher.reclass import ImgNet


# UIHash Class Mapping (based on nodes2hash.py logic)
# 0: Button, 1: CheckBox/Radio, 2: Input, 3: ListView, 4: Tab, 5: TextView, 6: Switch, 7: Other
TAG_MAP = {
    "button": 0, "a": 0, 
    "input": 2, "textarea": 2,
    "select": 7, "img": 7, "svg": 7,
    "label": 5, "span": 5, "p": 5,
    "h1": 5, "h2": 5, "h3": 5, "h4": 5, "h5": 5, "h6": 5,
    "div": -1,  # Too noisy, ignore Generic Containers
    "li": 3, "ul": 3, "ol": 3,
    "form": -1, "nav": -1, "header": -1, "footer": -1, "iframe": -1,  # Ignore Frame/Structure
    "body": -1, # Ignore Background
    "main": -1, "section": -1, "article": -1, "aside": -1 # Ignore Semantic Structure
}

def classify_web_elements(input_dir, model_path, threshold=0.95, device='cpu', tag_only=False):
    net = None
    if not tag_only:
        print(f"Loading model from {model_path}...")
        try:
            checkpoint = torch.load(model_path, map_location=device)
            state_dict = checkpoint
            if 'resnet.fc.weight' in state_dict:
                class_num = state_dict['resnet.fc.weight'].shape[0]
                print(f"Detected {class_num} classes from model.")
            else:
                class_num = 15
            net = ImgNet(class_num)
            net.load_state_dict(state_dict)
            net.to(device)
            net.eval()
        except Exception as e:
            print(f"Failed to load model: {e}")
            return
    else:
        print("Using Tag-based classification (Naive Mode).")

    print(f"Scanning {input_dir}...")
    
    total_files = 0
    total_elements = 0
    
    for root, dirs, files in os.walk(input_dir):
        if "hash" in root:
            continue
            
        json_files = [f for f in files if f.endswith('.json')]
        
        for json_file in json_files:
            if not json_file.startswith('web_'):
                continue
                
            json_path = os.path.join(root, json_file)
            png_path = json_path.replace('.json', '.png')
            
            if not os.path.exists(png_path):
                continue
                
            total_files += 1
            
            target_subdir_name = json_file.replace('.json', '')
            target_subdir_path = os.path.join(root, target_subdir_name)
            
            if not os.path.exists(target_subdir_path):
                os.makedirs(target_subdir_path, exist_ok=True)
                
            classify_file = os.path.join(target_subdir_path, "classify.txt")
            
            # Load Image (only needed if NOT tag_only, but used for bounds filtering regardless)
            full_img = cv2.imread(png_path, 1)
            if full_img is None:
                continue
            h_img, w_img, _ = full_img.shape
            
            # Load JSON components
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            elements = []
            def flatten(node):
                if isinstance(node, dict):
                    label = node.get('componentLabel', 'unknown')
                    bounds = node.get('bounds', [0,0,0,0])
                    # Store raw tag if available (might be in label or separate field)
                    # The extractor puts the tag in 'componentLabel' usually?
                    # Let's check web_crawler.py:
                    # In _extract_dom_js: label = tagName.toLowerCase()
                    # Then Python saves 'componentLabel': dom['label']
                    # So 'label' IS the tag name.
                    elements.append({'label': label, 'bounds': bounds})
                    if 'children' in node:
                        for c in node['children']:
                            flatten(c)
                elif isinstance(node, list):
                    for item in node:
                        flatten(item)
            
            flatten(data)
            
            results = {}
            
            for idx, el in enumerate(elements):
                x1, y1, x2, y2 = el['bounds']
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w_img, x2), min(h_img, y2)
                
                # Basic size filter
                if x2 <= x1 or y2 <= y1:
                    continue
                
                final_label = -1
                
                if tag_only:
                    # Naive logic
                    tag = el['label'].lower()
                    # Remove any extra info if format is "tag class class"
                    # But crawler usually saves clean tag name or minimal info.
                    # Split by space just in case
                    tag_clean = tag.split(' ')[0]
                    final_label = TAG_MAP.get(tag_clean, 7) # Default to 7 (Other)
                else:
                    # CNN Logic
                    crop_img = full_img[y1:y2, x1:x2]
                    if crop_img.size == 0:
                        continue
                    
                    try:
                        crop_img = cv2.resize(crop_img, (28, 28))
                        crop_img = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
                    except Exception:
                        continue
                    
                    img_tensor = torch.from_numpy(crop_img).float()
                    img_tensor = img_tensor.unsqueeze(0).unsqueeze(0)
                    img_tensor = img_tensor.to(device)
                    
                    with torch.no_grad():
                        output = net(img_tensor)
                        probs = torch.softmax(output, dim=1)
                        score, pred_label = torch.max(probs, dim=1)
                        
                        pred_label = int(pred_label.item())
                        score = float(score.item())

                        # Remap from Training IDs (Alphabetical) to UIHash IDs (Standard)
                        # Dataset: 0:button, 1:img, 2:input, 3:text
                        # UIHash:  0:button, 7:img, 2:input, 5:text
                        label_map = {0: 0, 1: 7, 2: 2, 3: 5}
                        if pred_label in label_map:
                            pred_label = label_map[pred_label]
                    
                    final_label = pred_label if score > threshold else -1
                
                key_name = f"{idx}_{el['label']}"
                results[key_name] = final_label
                total_elements += 1
                
            with open(classify_file, 'w', encoding='utf-8') as f:
                f.write(str(results))
            
            print(f"Processed {json_file}: {len(results)} elements -> {classify_file}")
 
    print(f"Done. Scanned {total_files} files, Classified {total_elements} elements.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input_dir', help='Path to output_web')
    parser.add_argument('--model', default='models/reclass_e5_128.tar', help='Path to trained model')
    parser.add_argument('--threshold', type=float, default=0.95, help='Confidence threshold')
    parser.add_argument('--tag-only', action='store_true', help='Use HTML tags for classification instead of CNN')
    
    args = parser.parse_args()
    
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    classify_web_elements(args.input_dir, args.model, args.threshold, device, args.tag_only)
