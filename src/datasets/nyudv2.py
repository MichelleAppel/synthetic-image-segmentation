import os
import ssl
from urllib.request import urlopen

import mat73
import numpy as np
from PIL import Image
from skimage.segmentation import find_boundaries
from torch.utils.data import DataLoader, Dataset, random_split
from tqdm import tqdm

import torch
from torchvision.io import read_image
from src.datasets.transforms import Transform

import pytorch_lightning as pl

from skimage.morphology import binary_dilation, binary_erosion, disk, thin

class NYUDv2Dataset(Dataset):
    def __init__(self, data_root, resize=(480, 640), crop_size=(480, 480), border=4):

        self.data_root = data_root
        self.filename = "nyu_depth_v2_labeled.mat"
        self.url = "https://horatio.cs.nyu.edu/mit/silberman/nyu_depth_v2/nyu_depth_v2_labeled.mat"
        
        self.resize = resize
        self.crop_size = crop_size
        self.transforms = Transform(self.resize, self.crop_size)
        self.border = border

        self.image_paths = []
        self.edges_paths = []

        self.setup()

    def download(self, verify_ssl=False):
        # Check if the file is already downloaded
        file_path = os.path.join(self.data_root, self.filename)
        if not os.path.exists(file_path):
            # Download the .mat file
            ssl_context = None
            if not verify_ssl:
                ssl_context = ssl._create_unverified_context()

            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Get file size from the header
            with urlopen(self.url, context=ssl_context) as response:
                file_size = int(response.info().get('Content-Length', 0))

            # Download the file with a progress bar
            with urlopen(self.url, context=ssl_context) as response, open(file_path, "wb") as out_file:
                chunk_size = 1024
                total_chunks = (file_size + chunk_size - 1) // chunk_size
                for _ in tqdm(range(total_chunks), total=total_chunks, unit='KB'):
                    chunk = response.read(chunk_size)
                    out_file.write(chunk)

    def prepare_data(self):
        # Load the .mat file
        file_path = os.path.join(self.data_root, self.filename)
        data = mat73.loadmat(file_path)

        # Extract the images and instances
        images = data["images"]
        instances = data["instances"]

        # Create directories for images, instances, and edges if they don't exist
        os.makedirs(os.path.join(self.data_root, "images"), exist_ok=True)
        os.makedirs(os.path.join(self.data_root, "edges"), exist_ok=True)

        # Save the images, instances, and edges as .png files
        for i in range(images.shape[3]):
            # Save image
            image = Image.fromarray(images[:, :, :, i])
            image.save(os.path.join(self.data_root, "images", f"{i:05d}.png"))

            # Save instance
            instance = Image.fromarray(instances[:, :, i])

            # Compute and save edges
            instance_np = np.array(instance)
            edges = self.compute_edges(instance_np)
            edges_img = Image.fromarray(edges.astype(np.uint8) * 255)
            edges_img.save(os.path.join(self.data_root, "edges", f"{i:05d}.png"))

    def compute_edges(self, instance, disk_size=3):
        edges = find_boundaries(instance, mode='outer').astype(np.uint8)
        dilated_edges = binary_dilation(edges, disk(disk_size))
        eroded_edges = binary_erosion(dilated_edges, disk(disk_size))
        thinned_edges = thin(eroded_edges)
        return thinned_edges

    def setup(self):
        # Download the dataset if not already downloaded
        if not os.path.exists(os.path.join(self.data_root, self.filename)):
            self.download()

        # Load the dataset if not already loaded
        if not os.path.exists(os.path.join(self.data_root, "images")):
            self.prepare_data()

        # Generate image and edge paths
        image_dir = os.path.join(self.data_root, "images")
        edges_dir = os.path.join(self.data_root, "edges")

        self.image_paths = sorted([os.path.join(image_dir, f) for f in os.listdir(image_dir) if f.endswith(".png")])
        self.edges_paths = sorted([os.path.join(edges_dir, f) for f in os.listdir(edges_dir) if f.endswith(".png")])
        
    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):

        # Open the image file
        image_path = self.image_paths[idx]
        image = read_image(image_path).to(torch.float32) / 255.0 * 2 - 1

        # Open the edges file
        edges_path = self.edges_paths[idx]
        edges = read_image(edges_path).to(torch.float32) / 255.0

        # Crop the outer 8 pixels of each image
        border = 8
        image = image[:, border:-border, border:-border]
        edges = edges[:, border:-border, border:-border]

        data = [image, edges]

        # Apply transforms
        if self.transforms:
            data = self.transforms(data)

        return data

class NYUDv2DataModule(pl.LightningDataModule):
    def __init__(self, dataset, batch_size=1, num_workers=0, shuffle=True, split=(0.7, 0.15, 0.15)):
        super().__init__()
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.shuffle = shuffle
        self.dataset = dataset
        self.split = split

        self.setup()

    def setup(self):
        train_len = int(self.split[0] * len(self.dataset))
        val_len = int(self.split[1] * len(self.dataset))
        test_len = len(self.dataset) - train_len - val_len

        self.train_dataset, self.val_dataset, self.test_dataset = random_split(self.dataset, [train_len, val_len, test_len])

    def train_dataloader(self):
        return DataLoader(self.train_dataset, batch_size=self.batch_size, num_workers=self.num_workers, shuffle=self.shuffle)
    
    def val_dataloader(self):
        return DataLoader(self.val_dataset, batch_size=self.batch_size, num_workers=self.num_workers)
    
    def test_dataloader(self):
        return DataLoader(self.test_dataset, batch_size=self.batch_size, num_workers=self.num_workers)
