#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import torch
import torch.nn as nn
import torch.optim as optim
import torch.optim.lr_scheduler as lr_scheduler
from torch.utils.data import DataLoader
import numpy as np
from scipy.spatial.distance import squareform
from losses.base import BaseTrainer
from distances import to_condensed, EuclideanDistance
from models import MNISTNet


class TripletSamplingStrategy:
    
    def triplets(self, y, distances):
        """
        Sample triplets from batch x according to labels y
        :param y: non one-hot labels for the current batch
        :param distances: a condensed distance matrix for the current batch
        :return: a tuple (anchors, positives, negatives) corresponding to the triplets built
        """
        raise NotImplementedError("a TripletSamplingStrategy should implement 'triplets'")


class BatchAll(TripletSamplingStrategy):
    """
    Batch all strategy. Create every possible triplet for a given batch
    """

    def triplets(self, y, distances):
        anchors, positives, negatives = [], [], []
        for anchor, y_anchor in enumerate(y):
            for positive, y_positive in enumerate(y):
                # if same embedding or different labels, skip
                if (anchor == positive) or (y_anchor != y_positive):
                    continue
                for negative, y_negative in enumerate(y):
                    if y_negative == y_anchor:
                        continue
                    anchors.append(anchor)
                    positives.append(positive)
                    negatives.append(negative)
        return anchors, positives, negatives


class HardestNegative(TripletSamplingStrategy):
    """
    Hardest negative strategy.
    Create every possible triplet with the hardest negative for each anchor
    """

    def triplets(self, y, distances):
        anchors, positives, negatives = [], [], []
        distances = squareform(distances.detach().cpu().numpy())
        y = y.cpu().numpy()
        for anchor, y_anchor in enumerate(y):
            # hardest negative
            d = distances[anchor]
            neg = np.where(y != y_anchor)[0]
            negative = int(neg[np.argmin(d[neg])])
            for positive in np.where(y == y_anchor)[0]:
                if positive == anchor:
                    continue
                anchors.append(anchor)
                positives.append(positive)
                negatives.append(negative)
        return anchors, positives, negatives
    
    
class HardestPositiveNegative(TripletSamplingStrategy):
    """
    Hardest positive and hardest negative strategy.
    Create a single triplet for anchor, with the hardest positive and the
        hardest negative. This can only be done if there are positives and
        negatives for every anchor.
    """

    def triplets(self, y, distances):
        anchors, positives, negatives = [], [], []
        distances = squareform(distances.detach().cpu().numpy())
        y = y.cpu().numpy()
        for anchor, y_anchor in enumerate(y):
            d = distances[anchor]
            # hardest positive
            pos = np.where(y == y_anchor)[0]
            pos = [p for p in pos if p != anchor]
            # hardest negative
            neg = np.where(y != y_anchor)[0]
            if d[pos].size > 0 and d[neg].size > 0:
                positive = int(pos[np.argmax(d[pos])])
                negative = int(neg[np.argmin(d[neg])])
                anchors.append(anchor)
                positives.append(positive)
                negatives.append(negative)
        return anchors, positives, negatives
    

class TripletLoss(nn.Module):
    """
    Triplet loss module
    Reference: https://arxiv.org/pdf/1503.03832.pdf
    :param device: a device in which to run the computation
    :param margin: a margin value to separe classes
    :param distance: a distance object to measure between the samples
    :param strategy: a TripletSamplingStrategy
    """

    def __init__(self, device, margin, distance, sampling=BatchAll()):
        super(TripletLoss, self).__init__()
        self.device = device
        self.margin = margin
        self.distance = distance
        self.sampling = sampling
    
    def calculate_distances(self, x, y):
        """
        Calculate the distances to positives and negatives for each anchor in the batch
        :param x: a tensor corresponding to a batch of size (N, d), where
            N = batch size
            d = dimension of the feature vectors
        :param y: a non one-hot label tensor corresponding to the batch
        :return: a pair (distances to positives, distances to negatives)
        """
        # Batch size
        n = x.size(0)
        # Calculate distances between every sample in the batch
        dist = self.distance.pdist(x).to(self.device)
        # Sample triplets according to the chosen strategy
        anchors, positives, negatives = self.sampling.triplets(y, dist)
        # Condense indices so we can fetch distances using the condensed triangular matrix (less memory footprint)
        pos = to_condensed(n, anchors, positives)
        neg = to_condensed(n, anchors, negatives)
        # Fetch the distances to positives and negatives
        return dist[pos], dist[neg]
    
    def forward(self, feat, logits, y):
        """
        Calculate the triplet loss
        :param feat: a tensor corresponding to a batch of size (N, d), where
            N = batch size
            d = dimension of the feature vectors
        :param logits: unused, kept for compatibility purposes
        :param y: a non one-hot label tensor corresponding to the batch
        :return: the triplet loss value
        """
        # Calculate the distances to positives and negatives for each anchor
        # Using the normalized features
        dpos, dneg = self.calculate_distances(feat, y)
        # Calculate the loss using the margin
        loss = dpos - dneg + self.margin
        # Keep only positive values
        # Return the batch mean
        return torch.mean(torch.clamp(loss, min=0.0))


class TripletTrainer(BaseTrainer):
    
    def __init__(self, trainset, testset, device, nfeat, margin=0.2, distance=EuclideanDistance(), sampling=BatchAll(), batch_size=100):
        train_loader = DataLoader(trainset, batch_size, shuffle=True, num_workers=4)
        test_loader = DataLoader(testset, batch_size, shuffle=False, num_workers=4)
        super(TripletTrainer, self).__init__(
                MNISTNet(nfeat),
                device,
                TripletLoss(device, margin, distance, sampling),
                distance,
                train_loader,
                test_loader)
        self.margin = margin
        self.distance = distance
        self.optimizers = [
                optim.SGD(self.model.parameters(), lr=0.001, momentum=0.9, weight_decay=0.0005)
        ]
        self.schedulers = [
                lr_scheduler.StepLR(self.optimizers[0], 5, gamma=0.8)
        ]
    
    def __str__(self):
        return 'Triplet Loss'
        
    def get_schedulers(self):
        return self.schedulers
        
    def get_optimizers(self):
        return self.optimizers
    
    def describe_params(self):
        return f"m={self.margin} - {self.distance}"
    