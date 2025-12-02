"""
Tag-based Classifier for Web UIHash
Generates classify.txt by mapping HTML tags to UIHash class IDs.
"""

import os
import argparse
from os import listdir, walk
from os.path import join, exists

# UIHash Class Mapping (based on nodes2hash.py logic)
# 0: Button
# 1: CheckBox/Radio
# 2: EditText (Input)
# 3: ListView
# 4: Tab
# 5: TextView
# 6: Toggle/Switch
# 7: Spinner/Bar/Other (Image, Icon, etc.)

TAG_MAP = {
    "button": 0,
    "a": 0, # Links are often buttons
    "input": 2,
    "textarea": 2,
    "select": 7, # Spinner-like
    "img": 7,
    "svg": 7,
    "label": 5,
    "span": 5,
    "p": 5,
    "h1": 5, "h2": 5, "h3": 5, "h4": 5, "h5": 5, "h6": 5,
    "div": 7, # Default container/other
    "li": 3, # List item
    "ul": 3,
    "ol": 3,
    "form": 7,
    "nav": 7,
    "header": 7,
    "footer": 7,
    "iframe": 7
}

def reclass_web(input_path: str):
    """
    Scan input_path for subdirectories (screens) and generate classify.txt
    """
    print(f"Reclassifying Web UIs in {input_path}...")
    
    # Find screen directories (those starting with web_)
    dirs = [d for d in listdir(input_path) if os.path.isdir(join(input_path, d)) and d.startswith("web_")]
    total = len(dirs)
    
    for k, d in enumerate(dirs):
        dir_path = join(input_path, d)
        classify_file = join(dir_path, "classify.txt")
        
        # Find images
        imgs = [f for f in listdir(dir_path) if f.endswith(".jpg")]
        labels = {}
        
        for img_file in imgs:
            # Filename format: {id}_{tag}.jpg
            # e.g., 12_button.jpg, 5_div.jpg
            try:
                parts = img_file[:-4].split('_', 1)
                if len(parts) < 2:
                    continue
                
                # Extract tag (remove any extra sanitization if needed)
                tag = parts[1]
                
                # Map tag to class ID
                # Default to 7 (Other) if unknown
                class_id = TAG_MAP.get(tag, 7)
                
                # Format: "index_originalType": reidentifiedType
                # index is the first part of filename
                index = parts[0]
                key = f"{index}_{tag}"
                labels[key] = class_id
                
            except Exception as e:
                print(f"Error parsing {img_file}: {e}")
        
        # Write classify.txt
        with open(classify_file, 'w') as f:
            f.write(str(labels))
            
        if (k+1) % 10 == 0:
            print(f"Processed {k+1}/{total}")
            
    print(f"Done! Generated classify.txt for {total} screens.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tag-based Classifier for Web UIHash")
    parser.add_argument("input_path", help="Path to output_web directory")
    args = parser.parse_args()
    
    reclass_web(args.input_path)
