# AI-for-Art 
This repository contains code for my submission to Duke's 2019 Spring AI for Art competition.

## Overview
The code in this repository is a modified PyTorch implementation of the CycleGAN architecture detailed by Zhu et al. (https://arxiv.org/pdf/1703.10593.pdf). 

A picture of the architecture is provided below (https://camo.githubusercontent.com/c653ddc55471557b851a7059540e80799fad7e29/687474703a2f2f6572696b6c696e6465726e6f72656e2e73652f696d616765732f6379636c6567616e2e706e67):
![alt text](https://github.com/avellal14/AI-for-Art/blob/master/cyclegan.png)

Files in this repository contain implementations of various 2d and 3d discriminator and generator architectures. There are also scripts to train the CycleGAN network and subsequently use it to perform style transfer between the provided input photograph and painting.

## Examples of Generated Paintings
A few images of Duke campus landmarks painted in the style of various Renaissance painters.

Some example images are below: 
![alt text](https://github.com/avellal14/AI-for-Art/blob/master/AI_for_Art_1.png)
