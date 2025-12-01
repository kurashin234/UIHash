import os

paths = ["./apks", ".\\apks", "apks", "path/to/apks", "path\\to\\apks"]

print(f"os.sep: {os.sep}")

for p in paths:
    # Original logic
    original_name = p.split(os.sep)[-1]
    
    # Proposed logic
    proposed_name = os.path.basename(os.path.normpath(p))
    
    print(f"Path: {p}")
    print(f"  Original: {original_name}")
    print(f"  Proposed: {proposed_name}")
