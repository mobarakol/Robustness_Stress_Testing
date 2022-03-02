import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
import pandas as pd
import numpy as np
import torchvision
import torchvision.transforms as T
from torchvision import models
import pytorch_lightning as pl

from pytorch_lightning.loggers import TensorBoardLogger
from pytorch_lightning.callbacks import ModelCheckpoint
from skimage.io import imread
from skimage.io import imsave
from tqdm import tqdm
from argparse import ArgumentParser
#perturbation libs
import torchvision.transforms.functional as TF
from PIL import Image, ImageEnhance

image_size = (224, 224)
num_classes = 14
batch_size = 150
epochs = 20
num_workers = 4
img_data_dir = '<path_to_data>/CheXpert-v1.0/'

class perturbation_classes:
    def __init__(self, pfactor=0.8):
        self.pfactor = pfactor
    
    def gamma_correction(self, img):
        return TF.adjust_gamma(img, self.pfactor, gain=1)
    
    def contrast(self, img):      
        return TF.adjust_contrast(img, self.pfactor)
    
    def brightness(self, img):
        return TF.adjust_brightness(img, self.pfactor)
    
    def sharpness(self, img):
        #return TF.adjust_sharpness(img, self.pfactor)
        img = np.transpose(img.numpy(),(1,2,0))
        img = Image.fromarray(img)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(self.pfactor)
        return torch.from_numpy(np.array(img)).permute(2, 0, 1)

    def gaussian_blur(self, img):
        return TF.gaussian_blur(img, kernel_size=self.pfactor)

class CheXpertDataset(Dataset):
    def __init__(self, csv_file_img, image_size, augmentation=False, pseudo_rgb = True, img_data_dir=None, 
            pfactor=None, ptech=None, subgrp=None):
        self.data = pd.read_csv(csv_file_img)
        self.image_size = image_size
        self.do_augment = augmentation
        self.pseudo_rgb = pseudo_rgb

        self.labels = [
            'No Finding',
            'Enlarged Cardiomediastinum',
            'Cardiomegaly',
            'Lung Opacity',
            'Lung Lesion',
            'Edema',
            'Consolidation',
            'Pneumonia',
            'Atelectasis',
            'Pneumothorax',
            'Pleural Effusion',
            'Pleural Other',
            'Fracture',
            'Support Devices']

        self.augment = T.Compose([
            T.RandomHorizontalFlip(p=0.5),
            T.RandomApply(transforms=[T.RandomAffine(degrees=15, scale=(0.9, 1.1))], p=0.5),
        ])

        self.perturb =  getattr(perturbation_classes(pfactor=pfactor), ptech)
        self.subgrp=subgrp
        print('Perturbation:',self.subgrp)
        self.samples = []
        for idx, _ in enumerate(tqdm(range(len(self.data)), desc='Loading Data')):
            img_path = img_data_dir + self.data.loc[idx, 'path_preproc']
            img_label = np.zeros(len(self.labels), dtype='float32')
            race_label = np.array(self.data.loc[idx, 'race_label'], dtype='int64')
            for i in range(0, len(self.labels)):
                img_label[i] = np.array(self.data.loc[idx, self.labels[i].strip()] == 1, dtype='float32')

            sample = {'image_path': img_path, 'label': img_label, 'race_label': race_label}
            self.samples.append(sample)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, item):
        sample = self.get_sample(item)

        image = torch.from_numpy(sample['image']).unsqueeze(0)
        label = torch.from_numpy(sample['label'])

        if self.do_augment:
            image = self.augment(image)

        if self.pseudo_rgb:
            image = image.repeat(3, 1, 1)

        if self.subgrp == 'black':
            if sample['race_label'] == 2:
                image = self.perturb(image.type(torch.ByteTensor)).type(torch.FloatTensor)
        else:
            image = self.perturb(image.type(torch.ByteTensor)).type(torch.FloatTensor)

        return {'image': image, 'label': label}

    def get_sample(self, item):
        sample = self.samples[item]
        image = imread(sample['image_path']).astype(np.float32)

        return {'image': image, 'label': sample['label'], 'race_label':sample['race_label']}


class CheXpertDataModule(pl.LightningDataModule):
    def __init__(self, csv_train_img, csv_val_img, csv_test_img, image_size, pseudo_rgb, batch_size, 
            num_workers, img_data_dir=None, pfactor=None, ptech=None, subgrp=None):
        super().__init__()
        self.csv_train_img = csv_train_img
        self.csv_val_img = csv_val_img
        self.csv_test_img = csv_test_img
        self.image_size = image_size
        self.batch_size = batch_size
        self.num_workers = num_workers

        self.train_set = CheXpertDataset(self.csv_train_img, self.image_size, augmentation=True, pseudo_rgb=pseudo_rgb, 
                img_data_dir=img_data_dir, pfactor=pfactor, ptech=ptech, subgrp=subgrp)
        self.val_set = CheXpertDataset(self.csv_val_img, self.image_size, augmentation=False, pseudo_rgb=pseudo_rgb, 
                img_data_dir=img_data_dir, pfactor=pfactor, ptech=ptech, subgrp=subgrp)
        self.test_set = CheXpertDataset(self.csv_test_img, self.image_size, augmentation=False, pseudo_rgb=pseudo_rgb, 
                img_data_dir=img_data_dir, pfactor=pfactor, ptech=ptech, subgrp=subgrp)

        print('#train: ', len(self.train_set))
        print('#val:   ', len(self.val_set))
        print('#test:  ', len(self.test_set))

    def train_dataloader(self):
        return DataLoader(self.train_set, self.batch_size, shuffle=True, num_workers=self.num_workers)

    def val_dataloader(self):
        return DataLoader(self.val_set, self.batch_size, shuffle=False, num_workers=self.num_workers)

    def test_dataloader(self):
        return DataLoader(self.test_set, self.batch_size, shuffle=False, num_workers=self.num_workers)


class ResNet(pl.LightningModule):
    def __init__(self, num_classes):
        super().__init__()
        self.num_classes = num_classes
        self.model = models.resnet34(pretrained=True)
        # freeze_model(self.model)
        num_features = self.model.fc.in_features
        self.model.fc = nn.Linear(num_features, self.num_classes)

    def remove_head(self):
        num_features = self.model.fc.in_features
        id_layer = nn.Identity(num_features)
        self.model.fc = id_layer

    def forward(self, x):
        return self.model.forward(x)

    def configure_optimizers(self):
        params_to_update = []
        for param in self.parameters():
            if param.requires_grad == True:
                params_to_update.append(param)
        optimizer = torch.optim.Adam(params_to_update, lr=0.001)
        return optimizer

    def unpack_batch(self, batch):
        return batch['image'], batch['label']

    def process_batch(self, batch):
        img, lab = self.unpack_batch(batch)
        out = self.forward(img)
        prob = torch.sigmoid(out)
        loss = F.binary_cross_entropy(prob, lab)
        return loss

    def training_step(self, batch, batch_idx):
        loss = self.process_batch(batch)
        self.log('train_loss', loss)
        grid = torchvision.utils.make_grid(batch['image'][0:4, ...], nrow=2, normalize=True)
        self.logger.experiment.add_image('images', grid, self.global_step)
        return loss

    def validation_step(self, batch, batch_idx):
        loss = self.process_batch(batch)
        self.log('val_loss', loss)

    def test_step(self, batch, batch_idx):
        loss = self.process_batch(batch)
        self.log('test_loss', loss)


class DenseNet(pl.LightningModule):
    def __init__(self, num_classes):
        super().__init__()
        self.num_classes = num_classes
        self.model = models.densenet121(pretrained=True)
        # freeze_model(self.model)
        num_features = self.model.classifier.in_features
        self.model.classifier = nn.Linear(num_features, self.num_classes)

    def remove_head(self):
        num_features = self.model.classifier.in_features
        id_layer = nn.Identity(num_features)
        self.model.classifier = id_layer

    def forward(self, x):
        return self.model.forward(x)

    def configure_optimizers(self):
        params_to_update = []
        for param in self.parameters():
            if param.requires_grad == True:
                params_to_update.append(param)
        optimizer = torch.optim.Adam(params_to_update, lr=0.001)
        return optimizer

    def unpack_batch(self, batch):
        return batch['image'], batch['label']

    def process_batch(self, batch):
        img, lab = self.unpack_batch(batch)
        out = self.forward(img)
        prob = torch.sigmoid(out)
        loss = F.binary_cross_entropy(prob, lab)
        return loss

    def training_step(self, batch, batch_idx):
        loss = self.process_batch(batch)
        self.log('train_loss', loss)
        grid = torchvision.utils.make_grid(batch['image'][0:4, ...], nrow=2, normalize=True)
        self.logger.experiment.add_image('images', grid, self.global_step)
        return loss

    def validation_step(self, batch, batch_idx):
        loss = self.process_batch(batch)
        self.log('val_loss', loss)

    def test_step(self, batch, batch_idx):
        loss = self.process_batch(batch)
        self.log('test_loss', loss)


def freeze_model(model):
    for param in model.parameters():
        param.requires_grad = False

class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count

def test(model, data_loader, device):
    model.eval()
    logits = []
    preds = []
    targets = []
    roc_auc_0 = AverageMeter()
    roc_auc_10 = AverageMeter()
    with torch.no_grad():
        for index, batch in enumerate(tqdm(data_loader, desc='Test-loop')):
            img, lab = batch['image'].to(device), batch['label'].to(device)
            out = model(img)
            pred = torch.sigmoid(out)
            logits.append(out)
            preds.append(pred)
            targets.append(lab)

            fpr, tpr, _ = roc_curve(lab[:,0].cpu(), pred[:,0].cpu())
            roc_auc_0.update(auc(fpr, tpr).item())
            fpr, tpr, _ = roc_curve(lab[:,10].cpu(), pred[:,10].cpu())
            roc_auc_10.update(auc(fpr, tpr).item())

        logits = torch.cat(logits, dim=0)
        preds = torch.cat(preds, dim=0)
        targets = torch.cat(targets, dim=0)
        print("AUC(no finding): %2.5f, AUC(Pleural Effu):%2.5f" % (roc_auc_0.avg, roc_auc_10.avg))

        counts = []
        for i in range(0,num_classes):
            t = targets[:, i] == 1
            c = torch.sum(t)
            counts.append(c)
        print(counts)

    return preds.cpu().numpy(), targets.cpu().numpy(), logits.cpu().numpy()


def embeddings(model, data_loader, device):
    model.eval()

    embeds = []
    targets = []

    with torch.no_grad():
        for index, batch in enumerate(tqdm(data_loader, desc='Test-loop')):
            img, lab = batch['image'].to(device), batch['label'].to(device)
            emb = model(img)
            embeds.append(emb)
            targets.append(lab)

        embeds = torch.cat(embeds, dim=0)
        targets = torch.cat(targets, dim=0)

    return embeds.cpu().numpy(), targets.cpu().numpy()


def main(hparams, pfactor, ptech, img_data_dir=None, ckpt_dir=None, out_dir=None):

    # sets seeds for numpy, torch, python.random and PYTHONHASHSEED.
    pl.seed_everything(42, workers=True)

    # data
    data = CheXpertDataModule(csv_train_img='datafiles/full_sample_train.csv',
                              csv_val_img='datafiles/full_sample_val.csv',
                              csv_test_img='datafiles/full_sample_test.csv',
                              image_size=image_size,
                              pseudo_rgb=True,
                              batch_size=batch_size,
                              num_workers=num_workers,
                              img_data_dir=img_data_dir,
                              pfactor=pfactor,
                              ptech=ptech,
                              subgrp=hparams.subgrp)

    # model
    model_type = DenseNet
    model = model_type(num_classes=num_classes)

    # Create output directory
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    temp_dir = os.path.join(out_dir, 'temp')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    for idx in range(0,5):
        sample = data.train_set.get_sample(idx)
        imsave(os.path.join(temp_dir, 'sample_' + str(idx) + '.jpg'), sample['image'].astype(np.uint8))


    print('Checkpoints found:', ckpt_dir)
    model = model_type.load_from_checkpoint(ckpt_dir, num_classes=num_classes) #'disease/densenet-all/epoch=9-step=5089.ckpt'

    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda:" + str(hparams.dev) if use_cuda else "cpu")

    model.to(device)

    cols_names_classes = ['class_' + str(i) for i in range(0,num_classes)]
    cols_names_logits = ['logit_' + str(i) for i in range(0, num_classes)]
    cols_names_targets = ['target_' + str(i) for i in range(0, num_classes)]


    print('TESTING-','Filter:', ptech, 'perturbation factor:', pfactor)
    preds_test, targets_test, logits_test = test(model, data.test_dataloader(), device)
    df = pd.DataFrame(data=preds_test, columns=cols_names_classes)
    df_logits = pd.DataFrame(data=logits_test, columns=cols_names_logits)
    df_targets = pd.DataFrame(data=targets_test, columns=cols_names_targets)
    df = pd.concat([df, df_logits, df_targets], axis=1)
    df.to_csv(os.path.join(out_dir, 'predictions_test.csv'), index=False)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--gpus', default=1)
    parser.add_argument('--dev', default=0)
    parser.add_argument('--img_data_dir', type=str, default=None)
    parser.add_argument('--subgrp', type=str, default=None, choices=['all', 'pblack'])
    args = parser.parse_args()
    #args.subgrp = 'all'
    out_dir_base = 'output/disease/'
    model_name = 'densenet-pall/'

    ckpt_dir = 'output/epoch=9-step=5089.ckpt'
    pfactor_list = [0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6]
    ptech_list = ['gamma_correction', 'contrast', 'brightness', 'sharpness', 'gaussian_blur']
    img_data_dir = '<path_to_data>/CheXpert-v1.0/'
    for idx_f, ptech in enumerate(ptech_list):
        if ptech == 'sharpness':
            pfactor_list = [ -6, -4, -2, 1, 2, 4, 6]
        elif ptech == 'gaussian_blur':
            pfactor_list = [1, 3, 5, 7, 9, 11, 13]
        else:
            pfactor_list = [0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6]
            
        for idx, pfactor in enumerate(pfactor_list):
            out_dir = os.path.join(out_dir_base, model_name, ptech,  str(pfactor))
            main(args, pfactor, ptech, img_data_dir, ckpt_dir, out_dir)
