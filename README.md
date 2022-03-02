# Progressive_Stress_Testing
Instruction to run the code and reproduce the results of our paper "Progressive Stress Testing for Analysing Model Robustness and Subgroup Disparities".

## Dataset

The CheXpert imaging dataset can be downloaded from https://stanfordmlgroup.github.io/competitions/chexpert/.


Training command:
```
python train.py --img_data_dir '<path_to_data>/CheXpert-v1.0/'
```
To run our progressive stress testing
```
python perturbation.py --img_data_dir '<path_to_data>/CheXpert-v1.0/' --subgrp all
```
