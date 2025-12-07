import os
import shutil
from glob import glob

root = "output_web"
json_files = glob(os.path.join(root, "*.json"))

print(f"Found {len(json_files)} JSON files in {root}")

for json_path in json_files:
    basename = os.path.splitext(os.path.basename(json_path))[0]
    target_dir = os.path.join(root, basename)
    
    if os.path.isdir(target_dir):
        print(f"Moving {basename} files to {target_dir}")
        try:
            shutil.move(json_path, os.path.join(target_dir, os.path.basename(json_path)))
            
            png_path = json_path.replace(".json", ".png")
            if os.path.exists(png_path):
                shutil.move(png_path, os.path.join(target_dir, os.path.basename(png_path)))
        except Exception as e:
            print(f"Error moving {basename}: {e}")
    else:
        print(f"Directory {target_dir} does not exist, skipping {basename}")
