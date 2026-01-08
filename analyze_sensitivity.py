import pandas as pd
import os
import sys

def analyze_sensitivity(csv_path):
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Failed to read CSV: {e}")
        return

    # Filter for Rank 1 only (The best match found for each pair)
    # Since we are evaluating "Is this pair phishing?", we look at the best similarity score found.
    top1 = df[df['Rank'] == 1]
    
    total_pairs = len(top1)
    if total_pairs == 0:
        print("No Rank 1 data found.")
        return

    print(f"Total Pairs Evaluated: {total_pairs}")
    print("\n--- Sensitivity Analysis (Detection Rate) ---\n")

    # Defined variations
    thresholds = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    dists = [100.0, 10.0, 5.0, 3.0, 1.0] # 100.0 effectively means "No Limit"

    # Header
    print(f"{'Score >=':<10} {'Dist <=':<10} {'Detected':<10} {'Rate (%)':<10}")
    print("-" * 45)

    for dist_limit in dists:
        for thresh in thresholds:
            # Condition: Score must be >= thresh AND Dist <= dist_limit
            # Note: Score in CSV might be N/A if failed, but we assume numeric here or handle naive
            
            # Convert to numeric, errors to NaN
            scores = pd.to_numeric(top1['Score'], errors='coerce')
            distances = pd.to_numeric(top1['Distance'], errors='coerce')

            # Count matches
            # A pair is "Detected" if it meets the criteria
            matches = ((scores >= thresh) & (distances <= dist_limit)).sum()
            rate = (matches / total_pairs) * 100

            dist_label = "None" if dist_limit == 100.0 else str(dist_limit)
            print(f"{thresh:<10} {dist_label:<10} {matches:<10} {rate:.1f}%")
        print("-" * 45)

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    target_csv = os.path.join(base_dir, "eval_output", "results_details.csv")
    analyze_sensitivity(target_csv)
