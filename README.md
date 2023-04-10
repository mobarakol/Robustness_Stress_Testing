# Robustness_Stress_Testing
Instruction to run the code and reproduce the results of our paper "Robustness Stress Testing in Medical Image Classification]{Robustness Stress Testing in Medical Image Classification".

## Dataset

The CheXpert imaging dataset can be downloaded from https://stanfordmlgroup.github.io/competitions/chexpert/. <br>
ISIC skin lesion dataset can be downloaded from https://github.com/GalAvineri/ISIC-Archive-Downloader.


Training command:
```
python train.py --img_data_dir '<path_to_data>/CheXpert-v1.0/'
```
To run our robustness stress testing
```
python perturbation.py --img_data_dir '<path_to_data>/CheXpert-v1.0/' --subgrp all
```
