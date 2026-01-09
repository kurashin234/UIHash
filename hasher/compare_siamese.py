
import os
import sys
import argparse
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

# Add path to access mlalgos
root_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "mlalgos")) # Needed for 'import network' inside siamese.py

from mlalgos.siamese import SiameseModel
from mlalgos.network import NNParas

def compare_using_siamese(hash_file, name_file, model_path, hash_size_str="8,5,10", top_k=20, threshold=0.5, cross=False, max_dist=None):
    # Parse hash size
    try:
        c, w, h = map(int, hash_size_str.split(','))
        hash_dims = (c, w, h)
        # Verify order: SiameseModel expects (Channel, H, W) usually?
        # In siamese.py: c, h, v = args.hash_size.split(',') -> (c, h, v)
        # And if hash_size[1]==5 and hash_size[2]==10 (H=5, W=10) -> cnn5x10
        # In uihash: "5,10" means W=5, H=10.
        # So "8,5,10" means C=8, W=5, H=10.
        # In siamese.py usage: "8,5,10".
        # So c=8, h=5, v=10.
        # Wait, if uihash output is (C, H, W) = (8, 10, 5) ??
        # Let's check uihash.py output shape again.
        # uihash.py uses Nodes2Hash.
        # Nodes2Hash: self.grid_width, self.grid_height.
        # grids = np.zeros((num_classes, grid_height, grid_width))
        # So shape is (C, H, W).
        # uihash args: grid_size="5,10" -> t1(width)=5, t2(height)=10.
        # So grid_height=10, grid_width=5.
        # So shape is (C, 10, 5).
        
        # Siamese args: "8,5,10".
        # c=8, h=5, v=10.
        # So it thinks H=5, W=10.
        # This implies a mismatch if data is 10x5.
        # BUT I enabled cnn5x10 for BOTH (5,10) and (10,5).
        # So effective input to Conv2d will be (samples, 8, 10, 5) or (samples, 8, 5, 10).
        # If model expects (8, 5, 10) but gets (8, 10, 5)...
        # Conv layer logic:
        # If input is 10x5.
        # Conv2d(..., 2) -> 9x4.
        # Conv2d(..., 2) -> 8x3.
        # Flatten -> 8*3*72 = 1728.
        # If input is 5x10.
        # Conv2d -> 4x9.
        # Conv -> 3x8.
        # Flatten -> 3*8*72 = 1728.
        # The flattened size is IDENTICAL.
        # So the model doesn't crash.
        # BUT spatial meaning is flipped if I mix them up.
        # Ideally we should match.
        # If uihash produced (8, 10, 5).
        # We should tell Siamese it is (8, 10, 5).
        # So `hash_size` arg should be `8,10,5`.
        pass
    except:
        print("Invalid hash_size format. Use C,W,H e.g. 8,5,10")
        return

    print(f"Loading model from {model_path}...")
    # Initialize model
    # Note: SiameseModel __init__ tries to load model relative to itself usually, 
    # but we will manually load variables.
    # Actually, let's use SiameseModel class to load structure and weights easily if possible.
    # But SiameseModel __init__ is coupled with training paths.
    # It constructs `self.model_path` based on epoch/batch/size.
    # Parsing that from the filename is tricky.
    # Better to manually instantiate the Net and load state dict.
    
    device = torch.device("cpu")
    if torch.cuda.is_available():
        device = torch.device("cuda")

    # Determine architecture
    from mlalgos.network import SiameseNet
    
    # Logic copied from my patch in siamese.py
    if (w == 5 and h == 10) or (w == 10 and h == 5):
        cnn = NNParas(c).cnn5x10
        fc = NNParas(c).fc5x10
    elif w == 5 and h == 5:
        cnn = NNParas(c).cnn5x5
        fc = NNParas(c).fc5x5
    elif w == 10 and h == 10:
        cnn = NNParas(c).cnn10x10
        fc = NNParas(c).fc10x10
    else:
        print(f"Unsupported grid: {w}x{h}")
        return

    net = SiameseNet(cnn, fc).to(device)
    
    # Load weights
    if not os.path.exists(model_path):
        print(f"Model file not found: {model_path}")
        return
        
    state_dict = torch.load(model_path, map_location=device)
    net.load_state_dict(state_dict)
    net.eval()
    print("Model loaded successfully.")

    # Load Data
    print(f"Loading hashes from {hash_file}...")
    hashes = np.load(hash_file, allow_pickle=True)
    names = np.load(name_file, allow_pickle=True)
    
    # Reshape hashes to (N, C, H, W)
    # Current shape might be (N, C, H*W) or (N, flattened) or (N, C, H, W)
    # Check shape
    N = len(names)
    print(f"Loaded {N} samples. Shape: {hashes.shape}")
    
    # Reshape hashes to (N, C, H, W)
    # hashes shape from uihash is typically (N, C, H*W) or (N, C, H, W)
    N = len(names)
    print(f"Loaded {N} samples. Shape: {hashes.shape}")
    
    # Force reshape to (N, c, h, w) (assuming h=10, w=5 from args 8,5,10)
    # Note: uihash grid order is (C, H, W)
    try:
        hashes = hashes.reshape(N, c, h, w)
    except ValueError:
        # Fallback if dimensions don't match, maybe swap w/h?
        try:
            hashes = hashes.reshape(N, c, w, h)
        except:
             print(f"Error reshaping hash from {hashes.shape} to ({N}, {c}, {h}, {w})")
             return

    print(f"Reshaped hash shape: {hashes.shape}")
         
    # Ensure tensor
    data_tensor = torch.from_numpy(hashes).float()

    # Generate Pairs
    pairs = []
    pair_indices = []
    
    print("Generating pairs...")
    for i in range(N):
        site_i = names[i].split(' ')[0] if ' ' in names[i] else names[i].split('_')[0]
        for j in range(i + 1, N):
            site_j = names[j].split(' ')[0] if ' ' in names[j] else names[j].split('_')[0]
            
            if cross and site_i == site_j:
                continue
                
            pair_indices.append((i, j))
            
    print(f"Comparing {len(pair_indices)} pairs...")
    
    # Batch processing
    batch_size = 128
    results = []
    
    with torch.no_grad():
        for k in range(0, len(pair_indices), batch_size):
            batch = pair_indices[k:k+batch_size]
            
            idx1 = [p[0] for p in batch]
            idx2 = [p[1] for p in batch]
            
            t1 = data_tensor[idx1].to(device)
            t2 = data_tensor[idx2].to(device)
            
            # Forward
            # Network expects stacked input (2, N, C, H, W) usually?
            # siamese.py: _forward
            # _i = torch.stack((_i1, _i2), 0)
            # _o = self.net(_i)
            # output1, output2 = ...
            # distance = cosine_similarity(output1, output2)
            
            # Our SiameseNet.forward takes (input1, input2) ??
            # Check network.py SiameseNet.forward(self, i: np.ndarray) ??
            # Line 34: def forward(self, i: np.ndarray):
            # rows = i.shape[0]/2
            # splits it.
            # So it expects stacked input!
            
            # Network expects stacked input (2, N, C, H, W) because forward() splits on dim 0 and squeezes dim 0.
            # Use stack instead of cat to create the extra dimension [2, Batch, ...]
            combined = torch.stack((t1, t2), 0) # (2, Batch, C, H, W)
            output = net(combined)
            
            # Split output
            # output shape is (2, Batch, Feat).
            # We want o1=(Batch, Feat), o2=(Batch, Feat)
            o1 = output[0]
            o2 = output[1]
            
            # Compute cosine similarity along feature dimension (dim=1)
            sim = torch.cosine_similarity(o1, o2, dim=1) # (Batch,)
            
            # Compute Euclidean Distance on Raw Inputs (Mundane Filtering)
            t1_flat = t1.view(t1.size(0), -1)
            t2_flat = t2.view(t2.size(0), -1)
            euc_dist = torch.norm(t1_flat - t2_flat, dim=1) # (Batch,)

            for idx, score in enumerate(sim):
                sc = score.item()
                dst = euc_dist[idx].item()
                
                # Filter by Max Distance (if set)
                # print(f"DEBUG: Sc={sc} Dist={dst} MaxDist={max_dist} Thresh={threshold}") # Debug
                if max_dist is not None and dst > max_dist:
                    print(f"DEBUG: SKIPPING due to MaxDist: Dist={dst} > {max_dist}")
                    continue

                if sc > threshold:
                    p_idx = batch[idx]
                    results.append((sc, p_idx[0], p_idx[1], dst))
                else:
                    print(f"DEBUG: SKIPPING due to Threshold: Sc={sc} <= {threshold}")
                    p_idx = batch[idx]
                    results.append((sc, p_idx[0], p_idx[1], dst))
                    
            if k % 1000 == 0 and k > 0:
                print(f"Processed {k} pairs...")

    # Sort results
    # Sort results by Score (Desc) then Distance (Asc)
    # x[0] is score, x[3] is distance. To sort dist ascending in reverse sort, use -x[3].
    results.sort(key=lambda x: (x[0], -x[3]), reverse=True)
    
    print(f"\nTop {top_k} Similar Pairs (Threshold > {threshold}):")
    print("=" * 60)
    
    count = 0
    for score, i, j, dist in results:
        if count >= top_k:
            break
        print(f"{count+1}. Score: {score:.4f} (Dist: {dist:.4f})")
        print(f"   A: {names[i]}")
        print(f"   B: {names[j]}")
        print("-" * 60)
        count += 1
        
    if count == 0:
        print("No pairs found matching threshold.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("hash_file")
    parser.add_argument("name_file")
    parser.add_argument("model_path")
    parser.add_argument("--hash_size", default="8,5,10", help="C,W,H")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--max_dist", type=float, default=None, help="Max Euclidean Distance for filtering")
    parser.add_argument("--cross", action="store_true", help="Cross-site only")
    
    args = parser.parse_args()
    compare_using_siamese(args.hash_file, args.name_file, args.model_path, 
                          args.hash_size, args.top, args.threshold, args.cross, args.max_dist)
