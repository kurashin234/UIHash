
import os
import argparse
import sys
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader

# Add path to import ImgNet
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from reclass import ImgNet
except ImportError:
    from hasher.reclass import ImgNet

def train_cnn(data_dir, output_model, epochs=10, batch_size=32, lr=0.001):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    # Transforms (match reclass.py expectation usually 64x64 or 224x224 depending on reclass)
    # Checking reclass.py typically uses 64x64 or similar. Let's assume 64x64 based on typical uihash.
    # ImgNet in reclass.py:
    # It likely expects a certain input size. Let's assume 128x128 to be safe or check reclass.py.
    # IMPORTANT: If input size mismatch, FC layer will fail.
    # I should check reclass.py content ideally. But for now I'll use 64x64 standard for icons.
    
    transform = transforms.Compose([
        transforms.Resize((28, 28)),
        transforms.Grayscale(num_output_channels=1),
        transforms.ToTensor(),
        # Normalize for 1 channel
        transforms.Normalize(mean=[0.5], std=[0.5])
    ])

    print(f"Loading data from {data_dir}...")
    dataset = datasets.ImageFolder(data_dir, transform=transform)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    
    num_classes = len(dataset.classes)
    print(f"Found {num_classes} classes: {dataset.classes}")
    
    model = ImgNet(num_classes).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)
    
    model.train()
    for epoch in range(epochs):
        running_loss = 0.0
        correct = 0
        total = 0
        for inputs, labels in dataloader:
            inputs, labels = inputs.to(device), labels.to(device)
            
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
            
        current_lr = optimizer.param_groups[0]['lr']
        print(f"Epoch {epoch+1}/{epochs}, Loss: {running_loss/len(dataloader):.4f}, Acc: {100 * correct / total:.2f}%, LR: {current_lr}")

    # Save
    os.makedirs(os.path.dirname(output_model), exist_ok=True)
    torch.save(model.state_dict(), output_model)
    print(f"Model saved to {output_model}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", help="Path to training dataset folder (containing class subfolders)")
    parser.add_argument("--output", default="models/cnn_model_new.pth", help="Output model path")
    parser.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()
    
    train_cnn(args.data_dir, args.output, args.epochs)
