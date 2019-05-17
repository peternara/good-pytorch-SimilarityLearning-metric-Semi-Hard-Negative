import torch
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
from distances import CosineDistance
from losses.base import Logger
from losses.arcface import arc_trainer
from losses.contrastive import contrastive_trainer
from losses.triplet import triplet_trainer
from losses.wrappers import softmax_trainer
from losses.center import center_trainer
from losses.coco import coco_trainer
import argparse


# Constants and Config
loss_options = 'softmax / contrastive / triplet / arcface / center / coco'
use_cuda = torch.cuda.is_available() and True
nfeat, nclass = 2, 10
device = torch.device('cuda' if use_cuda else 'cpu')
parser = argparse.ArgumentParser()
parser.add_argument('--mnist', type=str, help='Path to MNIST dataset')
parser.add_argument('--loss', type=str, help=loss_options)
parser.add_argument('--epochs', type=int, help='The number of epochs to run the model')
parser.add_argument('-c', '--controlled', type=bool, default=True, help='Whether to set a fixed seed to control the training environment. Default value: True')
parser.add_argument('--log-interval', type=int, default=10, help='Steps (in percentage) to show epoch progress. Default value: 10')
parser.add_argument('--batch-size', type=int, default=100, help='Batch size for training and testing')


def get_trainer(loss, callbacks):
    if loss == 'softmax':
        return softmax_trainer(train_loader, test_loader, device, nfeat, nclass, callbacks)
    elif loss == 'contrastive':
        return contrastive_trainer(train_loader, test_loader, device, nfeat, callbacks)
    elif loss == 'triplet':
        return triplet_trainer(train_loader, test_loader, device, nfeat, callbacks, margin=0, distance=CosineDistance())
    elif loss == 'arcface':
        return arc_trainer(train_loader, test_loader, device, nfeat, nclass, callbacks)
    elif loss == 'center':
        return center_trainer(train_loader, test_loader, device, nfeat, nclass, callbacks, distance=CosineDistance())
    elif loss == 'coco':
        return coco_trainer(train_loader, test_loader, device, nfeat, nclass, callbacks)
    else:
        raise ValueError(f"Loss function should be one of: {loss_options}")


# Init
args = parser.parse_args()
if args.controlled:
    torch.manual_seed(999)

# Load Dataset
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))])
trainset = datasets.MNIST(args.mnist, download=True, train=True, transform=transform)
testset = datasets.MNIST(args.mnist, download=True, train=False, transform=transform)
train_loader = DataLoader(trainset, args.batch_size, shuffle=True, num_workers=4)
test_loader = DataLoader(testset, args.batch_size, shuffle=False, num_workers=4)

callbacks = []
if args.log_interval in range(1, 101):
    callbacks.append(Logger(args.log_interval))

# Train
trainer = get_trainer(args.loss, callbacks)
trainer.train(args.epochs)
