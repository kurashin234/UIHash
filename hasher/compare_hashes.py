"""
Compare UI Hashes using Cosine Similarity.
Finds similar Web UIs based on the generated UIHash vectors.
"""

import numpy as np
import argparse
import os
from os.path import join, exists

def compare_hashes(hash_file: str, name_file: str, top_k: int = 10, threshold: float = 0.9, cross_site_only: bool = False):
    print(f"Loading hashes from {hash_file}...")
    if not exists(hash_file) or not exists(name_file):
        print("Error: Hash or Name file not found.")
        return

    # Load data
    hashes = np.load(hash_file, allow_pickle=True)
    names = np.load(name_file, allow_pickle=True)
    
    # Flatten hashes if they are 3D (N, H, W) -> (N, H*W)
    # The hash shape from uihash.py might be (N, Channels, H*W) or similar depending on grid
    # Let's inspect the shape first
    print(f"Original hash shape: {hashes.shape}")
    
    # Flatten to 2D (N, Features)
    if len(hashes.shape) > 2:
        N = hashes.shape[0]
        hashes = hashes.reshape(N, -1)
    
    print(f"Flattened hash shape: {hashes.shape}")
    print(f"Number of UIs: {len(names)}")

    # Normalize vectors for Cosine Similarity
    # CosSim(A, B) = dot(A, B) / (norm(A) * norm(B))
    # If we normalize A and B first, then CosSim(A, B) = dot(A, B)
    norm = np.linalg.norm(hashes, axis=1, keepdims=True)
    # Avoid division by zero
    norm[norm == 0] = 1e-10
    normalized_hashes = hashes / norm

    # Compute Similarity Matrix
    print("Computing similarity matrix...")
    sim_matrix = np.dot(normalized_hashes, normalized_hashes.T)
    
    # Mask diagonal to ignore self-similarity
    np.fill_diagonal(sim_matrix, 0)

    # Filter same-site comparisons if requested
    if cross_site_only:
        print("Filtering out same-site comparisons...")
        for i in range(len(names)):
            site_i = names[i].split()[0]
            for j in range(i + 1, len(names)):
                site_j = names[j].split()[0]
                if site_i == site_j:
                    sim_matrix[i][j] = 0
                    sim_matrix[j][i] = 0
    
    max_sim = np.max(sim_matrix)
    print(f"Maximum similarity found: {max_sim:.4f}")
    print(f"Average similarity: {np.mean(sim_matrix):.4f}")

    # Find top pairs
    print(f"\nTop {top_k} Similar Pairs (Threshold > {threshold}):")
    print("-" * 60)
    
    # We only care about upper triangle (excluding diagonal) to avoid duplicates and self-matches
    # Get indices where similarity > threshold
    # Note: This might be large if threshold is low.
    
    pairs = []
    N = len(names)
    for i in range(N):
        for j in range(i + 1, N):
            score = sim_matrix[i, j]
            if score > threshold:
                pairs.append((score, i, j))
    
    # Sort by score descending
    pairs.sort(key=lambda x: x[0], reverse=True)
    
    count = 0
    for score, i, j in pairs:
        if count >= top_k:
            break
        
        name_i = names[i]
        name_j = names[j]
        
        # Clean up names (remove redundant parts if needed)
        # Format in uihash.py is "pkg xml"
        
        print(f"[{score:.4f}]")
        print(f"  A: {name_i}")
        print(f"  B: {name_j}")
        print("-" * 60)
        count += 1
        
    if count == 0:
        print("No pairs found matching the threshold.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare UI Hashes")
    parser.add_argument("hash_file", help="Path to hash.npy")
    parser.add_argument("name_file", help="Path to name.npy")
    parser.add_argument("--top", "-k", type=int, default=20, help="Number of pairs to show")
    parser.add_argument("--threshold", "-t", type=float, default=0.8, help="Similarity threshold (0.0-1.0)")
    parser.add_argument("--cross", action="store_true", help="Only compare cross-site (different domain/session) pairs")
    
    args = parser.parse_args()
    compare_hashes(args.hash_file, args.name_file, args.top, args.threshold, args.cross)
