#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import torch
import torch.nn as nn
import torch.optim as optim
import torch.optim.lr_scheduler as lr_scheduler
from CenterLoss import CenterLoss
from ContrastiveLoss import ContrastiveLoss
from arcface import ArcLinear
import visual

class CenterTrainer:
    
    def __init__(self, model, device, loss_weight=1):
        self.loss_weight = loss_weight
        self.device = device
        self.model = model.to(device)
        self.nllloss = nn.NLLLoss().to(device)
        self.centerloss = CenterLoss(10, 2).to(device)
        self.optimizer4nn = optim.SGD(model.parameters(), lr=0.001, momentum=0.9, weight_decay=0.0005)
        self.optimzer4center = optim.SGD(self.centerloss.parameters(), lr=0.5)
    
    def train(self, epoch, loader):
        print("Training... Epoch = %d" % epoch)
        ip1_loader = []
        idx_loader = []
        for i, (data, target) in enumerate(loader):
            data, target = data.to(self.device), target.to(self.device)
    
            ip1, pred = self.model(data)
            loss = self.nllloss(pred, target) + self.loss_weight * self.centerloss(target, ip1)
    
            self.optimizer4nn.zero_grad()
            self.optimzer4center.zero_grad()
    
            loss.backward()
    
            self.optimizer4nn.step()
            self.optimzer4center.step()
    
            ip1_loader.append(ip1)
            idx_loader.append((target))
    
        feat = torch.cat(ip1_loader, 0)
        labels = torch.cat(idx_loader, 0)
        visual.visualize(feat.data.cpu().numpy(), labels.data.cpu().numpy(),
                         "Epoch = {}".format(epoch), "epoch={}".format(epoch))


class ArcTrainer:
    
    def __init__(self, model, device, nfeat, nclass, margin=0.2, s=7.0):
        self.margin = margin
        self.s = s
        self.device = device
        self.model = model.to(device)
        self.arc = ArcLinear(nfeat, nclass, margin, s).to(device)
        self.lossfn = nn.CrossEntropyLoss().to(device)
        self.optim_nn = optim.SGD(self.model.parameters(), lr=0.001, momentum=0.9, weight_decay=0.0005)
        self.optim_arc = optim.SGD(self.arc.parameters(), lr=0.01)
        self.sheduler = lr_scheduler.StepLR(self.optim_nn, 20, gamma=0.5)
        self.losses, self.accuracies = [], []
        self.best_acc = 0.8
    
    def train(self, epoch, loader, test_loader, log_interval=20):
        self.sheduler.step()
        test_total = len(test_loader.dataset)
        total_loss, correct, total = 0, 0, 0
        for i, (x, y) in enumerate(loader):
            x, y = x.to(self.device), y.to(self.device)
            
            # Feed Forward
            feat = self.model(x)
            logits = self.arc(feat, y)
            loss = self.lossfn(logits, y)
            
            total_loss += loss
            _, predicted = torch.max(logits.data, 1)
            total += y.size(0)
            correct += (predicted == y.data).sum()
            
            # Backprop
            self.optim_nn.zero_grad()
            self.optim_arc.zero_grad()
            
            loss.backward()
            
            self.optim_nn.step()
            self.optim_arc.step()
            
            # Logging
            if i % log_interval == 0:
                print(f"Train Epoch: {epoch} [{100. * i / len(loader):.0f}%]\tLoss: {loss.item():.6f}")
        
        test_correct = self.eval(test_loader)
        loss = total_loss / len(loader)
        acc = 100 * test_correct / test_total
        self.losses.append(loss)
        self.accuracies.append(acc)
        print(f"--------------- Epoch {epoch} Results ---------------")
        print(f"Training Accuracy = {100 * correct / total:.0f}%")
        print(f"Mean Training Loss: {loss:.6f}")
        print(f"Test Accuracy: {test_correct} / {test_total} ({acc:.0f}%)")
        print("-----------------------------------------------")
        if acc > self.best_acc:
            plot_name = f"test-feat-epoch-{epoch}"
            print(f"New Best Test Accuracy! Saving plot as {plot_name}")
            self.best_acc = acc
            self.visualize(test_loader, f"Test Embeddings (Epoch {epoch}) - {acc:.0f}% Accuracy - m={self.margin} s={self.s}", plot_name)
        
    def eval(self, loader):
        correct = 0
        with torch.no_grad():
            for x, y in loader:
                x, y = x.to(self.device), y.to(self.device)
                feat = self.model(x)
                logits = self.arc(feat, y)
                _, predicted = torch.max(logits.data, 1)
                correct += (predicted == y.data).sum()
        return correct
    
    def visualize(self, loader, title, filename):
        embs, targets = [], []
        with torch.no_grad():
            for x, target in loader:
                x, target = x.to(self.device), target.to(self.device)
                embs.append(self.model(x))
                targets.append(target)
        embs = torch.cat(embs, 0).type(torch.FloatTensor).data.cpu().numpy()
        targets = torch.cat(targets, 0).type(torch.FloatTensor).cpu().numpy()
        visual.visualize(embs, targets, title, filename)


class ContrastiveTrainer:
    
    def __init__(self, model, device, margin=1.0, distance='euclidean'):
        self.device = device
        self.model = model.to(device)
        self.loss_fn = ContrastiveLoss(margin, distance).to(device)
        self.optimizer = optim.Adam(model.parameters())
        self.sheduler = lr_scheduler.StepLR(self.optimizer,20,gamma=0.8)
        self.losses, self.accuracies = [], []
    
    def train(self, epoch, loader, test_loader, visu_loader, report_interval=1000):
        print("[Epoch %d]" % epoch)
        self.sheduler.step()
        running_loss = 0.0
        total_loss = 0.0
        best_acc = 0.0
        for i, (data1, data2, y, _, _) in enumerate(loader):
            data1, data2, y = data1.to(self.device), data2.to(self.device), y.to(self.device)
            
            emb1 = self.model(data1)
            emb2 = self.model(data2)
            loss = self.loss_fn(y, emb1, emb2)
            running_loss += loss
            total_loss += loss
            
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
            
            if i % report_interval == report_interval-1:
                print("[%d batches] Loss = %.4f" % (i+1, running_loss / report_interval))
                running_loss = 0.0
        
        acc = self.eval(test_loader)
        loss = total_loss / len(loader)
        self.losses.append(loss)
        self.accuracies.append(acc)
        print("Training Loss: %.4f" % loss)
        print("Test Accuracy: {}%".format(acc))
        if acc > best_acc:
            best_acc = acc
            self.visualize(visu_loader, "epoch={}-acc={}".format(epoch, acc))
    
    def eval(self, loader):
        correct, total = 0.0, 0.0
        with torch.no_grad():
            for x1, x2, y, _, _ in loader:
                x1, x2, y = x1.to(self.device), x2.to(self.device), y.to(self.device)
                emb1 = self.model(x1)
                emb2 = self.model(x2)
                dist = self.loss_fn.distance(emb1, emb2)
                preds = torch.where(dist < self.loss_fn.margin, torch.zeros_like(dist), torch.ones_like(dist))
                correct += (preds == y).sum()
                total += y.size(0)
        return 100 * correct / total
    
    def visualize(self, loader, filename):
        embs, targets = [], []
        with torch.no_grad():
            for x, target in loader:
                x, target = x.to(self.device), target.to(self.device)
                embs.append(self.model(x))
                targets.append(target)
        embs = torch.cat(embs, 0).type(torch.FloatTensor).data.cpu().numpy()
        targets = torch.cat(targets, 0).type(torch.FloatTensor).cpu().numpy()
        visual.visualize(embs, targets, "Test Embeddings", filename)
                
    
    def train_online_recomb(self, epoch, loader, xtest, ytest):
        print("Training... Epoch = %d" % epoch)
        for i, (x, y) in enumerate(loader):
            x, y = x.to(self.device).unsqueeze(1), y.to(self.device)
            x1, x2, simil = self.build_pairs(x, y)
            x1, x2, simil = x1.to(self.device), x2.to(self.device), simil.to(self.device)
            emb1 = self.model(x1)
            emb2 = self.model(x2)
            loss = self.loss_fn(simil, emb1, emb2)
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
        embs = self.model(xtest).data.cpu().numpy()
        visual.visualize(embs, ytest.cpu().numpy(), "Epoch = {}".format(epoch), "epoch={}".format(epoch))
    
    def build_pairs(self, X, Y):
        n = Y.size(0)
        fst, snd = [], []
        Ypairs = []
        for i in range(n-1):
            added = []
            for j in range(i+1, n):
                label = Y[j]
                if i != j and label not in added:
                    fst.append(X[i])
                    snd.append(X[j])
                    Ypairs.append(0 if Y[i] == Y[j] else 1)
                    added.append(label)
                if len(added) == 10:
                    break
        pairs1 = torch.cat(fst, 0).type(torch.FloatTensor)
        pairs2 = torch.cat(snd, 0).type(torch.FloatTensor)
        return pairs1, pairs2, torch.FloatTensor(Ypairs)
