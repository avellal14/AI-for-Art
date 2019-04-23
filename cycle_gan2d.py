import os
import pdb
import pickle
import argparse
import itertools

import warnings
warnings.filterwarnings("ignore")

# Torch imports
import torch
import torch.nn as nn
import torch.optim as optim

# Numpy & Scipy imports
import numpy as np
import scipy
import scipy.misc

# Local imports
import utils
from data_loader import get_data_loader2d
from models import CycleGenerator2d, PatchGANDiscriminator2d
from torchvision import transforms

SEED = 14

# Set the random seed manually for reproducibility.
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed(SEED)


"""Builds the generators and discriminators using the CycleGenerator."""
def create_model(opts):
    G_XtoY = CycleGenerator2d(init_zero_weights=opts.init_zero_weights)
    G_YtoX = CycleGenerator2d(init_zero_weights=opts.init_zero_weights)
    D_X = PatchGANDiscriminator2d()
    D_Y = PatchGANDiscriminator2d()

    if torch.cuda.is_available():
        G_XtoY.cuda()
        G_YtoX.cuda()
        D_X.cuda()
        D_Y.cuda()
        print('Models moved to GPU.')

    return G_XtoY, G_YtoX, D_X, D_Y


"""Saves the parameters of both generators G_YtoX, G_XtoY and discriminators D_X, D_Y as well as the optimizers"""
def checkpoint(iteration, G_XtoY, G_YtoX, D_X, D_Y, g_optimizer, dx_optimizer, dy_optimizer, opts):
    G_XtoY_path = os.path.join(opts.checkpoint_dir, 'G_XtoY_' +  str(iteration) + '_.pkl')
    G_YtoX_path = os.path.join(opts.checkpoint_dir, 'G_YtoX_' + str(iteration) + '_.pkl')
    D_X_path = os.path.join(opts.checkpoint_dir, 'D_X_' + str(iteration) + '_.pkl')
    D_Y_path = os.path.join(opts.checkpoint_dir, 'D_Y_' + str(iteration) + '_.pkl')

    g_optimizer_path = os.path.join(opts.checkpoint_dir, 'g_optimizer_' + str(iteration) + '_.pkl')
    dx_optimizer_path = os.path.join(opts.checkpoint_dir, 'dx_optimizer_' + str(iteration) + '_.pkl')
    dy_optimizer_path = os.path.join(opts.checkpoint_dir, 'dy_optimizer_' + str(iteration) + '_.pkl')

    torch.save(G_XtoY.state_dict(), G_XtoY_path)
    torch.save(G_YtoX.state_dict(), G_YtoX_path)
    torch.save(D_X.state_dict(), D_X_path)
    torch.save(D_Y.state_dict(), D_Y_path)

    torch.save(g_optimizer.state_dict(), g_optimizer_path)
    torch.save(dx_optimizer.state_dict(), dx_optimizer_path)
    torch.save(dy_optimizer.state_dict(), dy_optimizer_path)

"Loads generators, discriminators, and optimizers using provided iteration number (initializes them from scratch if provided iteration is 0)"
def load_checkpoint(opts):
    #prep all checkpoint directories
    G_XtoY_path = os.path.join(opts.checkpoint_dir, 'G_XtoY_' +  str(opts.start_iter) + '_.pkl')
    G_YtoX_path = os.path.join(opts.checkpoint_dir, 'G_YtoX_' + str(opts.start_iter) + '_.pkl')
    D_X_path = os.path.join(opts.checkpoint_dir, 'D_X_' + str(opts.start_iter) + '_.pkl')
    D_Y_path = os.path.join(opts.checkpoint_dir, 'D_Y_' + str(opts.start_iter) + '_.pkl')

    g_optimizer_path = os.path.join(opts.checkpoint_dir, 'g_optimizer_' + str(opts.start_iter) + '_.pkl')
    dx_optimizer_path = os.path.join(opts.checkpoint_dir, 'dx_optimizer_' + str(opts.start_iter) + '_.pkl')
    dy_optimizer_path = os.path.join(opts.checkpoint_dir, 'dy_optimizer_' + str(opts.start_iter) + '_.pkl')

    #initialize models either from scratch or using checkpoints from specified iteration
    G_XtoY, G_YtoX, D_X, D_Y = create_model(opts)

    g_params = itertools.chain(G_XtoY.parameters(), G_YtoX.parameters()) # Get generator parameters
    dx_params = D_X.parameters()   #Get discriminator parameters
    dy_params = D_Y.parameters()   #Get discriminator parameters

    g_optimizer = optim.Adam(g_params, opts.lr, [opts.beta1, opts.beta2])
    dx_optimizer = optim.Adam(dx_params, opts.lr, [opts.beta1, opts.beta2])
    dy_optimizer = optim.Adam(dy_params, opts.lr, [opts.beta1, opts.beta2])

    if(opts.start_iter > 0):
        G_XtoY.load_state_dict(torch.load(G_XtoY_path, map_location=lambda storage, loc: storage))
        G_YtoX.load_state_dict(torch.load(G_YtoX_path, map_location=lambda storage, loc: storage))
        D_X.load_state_dict(torch.load(D_X_path, map_location=lambda storage, loc: storage))
        D_Y.load_state_dict(torch.load(D_Y_path, map_location=lambda storage, loc: storage))

        g_optimizer.load_state_dict(torch.load(g_optimizer_path, map_location=lambda storage, loc: storage))
        dx_optimizer.load_state_dict(torch.load(dx_optimizer_path, map_location=lambda storage, loc: storage))
        dy_optimizer.load_state_dict(torch.load(dy_optimizer_path, map_location=lambda storage, loc: storage))

    return G_XtoY, G_YtoX, D_X, D_Y, g_optimizer, dx_optimizer, dy_optimizer

"""Creates a grid for sampling GAN results. Consist of pairs of columns,
   where the first column in each pair contains images source images and
   the second column in each pair contains images generated by the CycleGAN
   from the corresponding images in the first column.
"""
def merge_images(sources, targets, opts, k=10):
    _, _, h, w = sources.shape
    row = 2#int(np.sqrt(opts.batch_size))
    merged = np.zeros([3, row*h, row*w*2])
    for idx, (s, t) in enumerate(zip(sources, targets)):
        i = idx // row
        j = idx % row

        print("I: ", i, "H: ", h, "J: ", j)
        if(i * h >= merged.shape[1] or j * 2 * h >= merged.shape[2]):
            break
        merged[:, i*h:(i+1)*h, (j*2)*h:(j*2+1)*h] = s
        merged[:, i*h:(i+1)*h, (j*2+1)*h:(j*2+2)*h] = t
    return merged.transpose(1, 2, 0)


"""Saves samples from both generators X->Y and Y->X."""
def save_samples(iteration, fixed_Y, fixed_X, G_YtoX, G_XtoY, opts):
    fake_X = G_YtoX(fixed_Y)
    fake_Y = G_XtoY(fixed_X)

    cycle_X = G_YtoX(fake_Y)
    cycle_Y = G_XtoY(fake_X)

    X, fake_X, cycle_X = utils.to_data(fixed_X), utils.to_data(fake_X), utils.to_data(cycle_X)
    Y, fake_Y, cycle_Y = utils.to_data(fixed_Y), utils.to_data(fake_Y), utils.to_data(cycle_Y)

    merged = merge_images(X, fake_Y, opts)
    path = os.path.join(opts.sample_dir, 'sample-{:06d}-X-Y.png'.format(iteration))
    scipy.misc.imsave(path, merged)
    print('Saved {}'.format(path))

    merged = merge_images(Y, fake_X, opts)
    path = os.path.join(opts.sample_dir, 'sample-{:06d}-Y-X.png'.format(iteration))
    scipy.misc.imsave(path, merged)
    print('Saved {}'.format(path))

    merged = merge_images(X, cycle_X, opts)
    path = os.path.join(opts.sample_dir, 'sample-{:06d}-X-cycle_X.png'.format(iteration))
    scipy.misc.imsave(path, merged)
    print('Saved {}'.format(path))

    merged = merge_images(Y, cycle_Y, opts)
    path = os.path.join(opts.sample_dir, 'sample-{:06d}-Y-cycle_Y.png'.format(iteration))
    scipy.misc.imsave(path, merged)
    print('Saved {}'.format(path))


"""Runs the training loop.
        1. Saves checkpoint every opts.checkpoint_every iterations
        2. Saves generated samples every opts.sample_every iterations
"""
def training_loop(dataloader_X, dataloader_Y, test_dataloader_X, test_dataloader_Y, opts):
    #Initialize generators, discriminators, and optimizers
    G_XtoY, G_YtoX, D_X, D_Y, g_optimizer, dx_optimizer, dy_optimizer = load_checkpoint(opts)

    iter_X = iter(dataloader_X)
    iter_Y = iter(dataloader_Y)

    test_iter_X = iter(test_dataloader_X)
    test_iter_Y = iter(test_dataloader_Y)

    # Set fixed data from domains X and Y for sampling. These are images that are held
    # constant throughout training, that allow us to inspect the model's performance.
    fixed_X = utils.to_var(test_iter_X.next()[0])
    fixed_Y = utils.to_var(test_iter_Y.next()[0])

    iter_per_epoch = min(len(iter_X), len(iter_Y))

    for iteration in range(1, opts.train_iters+1):
        # Reset data_iter for each epoch
        if iteration % iter_per_epoch == 0:
            iter_X = iter(dataloader_X)
            iter_Y = iter(dataloader_Y)

        images_X, labels_X = iter_X.next()
        images_X, labels_X = utils.to_var(images_X), utils.to_var(labels_X).long().squeeze()

        images_Y, labels_Y = iter_Y.next()
        images_Y, labels_Y = utils.to_var(images_Y), utils.to_var(labels_Y).long().squeeze()

        
        #### GENERATOR TRAINING #### (changed so real = 0, generated = 1)
        g_optimizer.zero_grad()

        # 1. GAN loss term
        fake_X = G_YtoX(images_Y)
        fake_Y = G_XtoY(images_X)
        
        gan_loss = torch.mean((D_X(fake_X)**2)) + torch.mean((D_Y(fake_Y)**2)) 

        #2. Identity loss term
        identity_X = G_YtoX(images_X)
        identity_Y = G_XtoY(images_Y)
        
        identity_loss = torch.mean(torch.abs(images_X - identity_X)) + torch.mean(torch.abs(images_Y-identity_Y))
    
        #3. Cycle consistency loss term
        reconstructed_Y = G_XtoY(fake_X)
        reconstructed_X = G_YtoX(fake_Y)
        
        cycle_consistency_loss = torch.mean(torch.abs(images_Y-reconstructed_Y)) + torch.mean(torch.abs(images_X-reconstructed_X))

        
        #Final GAN Loss Term
        g_loss = gan_loss + opts.identity_lambda * identity_loss + opts.cycle_consistency_lambda * cycle_consistency_loss
       
        g_loss.backward()
        g_optimizer.step()

        
        #### DISCRIMINATOR TRAINING #### (changed so real = 0, generated = 1)

        # 1. Compute the discriminator x loss
        dx_optimizer.zero_grad()

        D_X_real_loss = torch.mean((D_X(images_X))**2) #Real loss
        fake_X = G_YtoX(images_Y)
        D_X_fake_loss = torch.mean((D_X(fake_X) - 1)**2) #Fake loss
        D_X_loss = (D_X_real_loss + D_X_fake_loss) * .5

        D_X_loss.backward()
        dx_optimizer.step()

        #2. Compute the discriminator y loss
        dy_optimizer.zero_grad()

        D_Y_real_loss = torch.mean((D_Y(images_Y))**2) #Real loss
        fake_Y = G_XtoY(images_X)
        D_Y_fake_loss = torch.mean((D_Y(fake_Y) - 1)**2) #Fake loss
        D_Y_loss = (D_Y_real_loss + D_Y_fake_loss) * .5

        D_Y_loss.backward()
        dy_optimizer.step()

     
        # Print the log info
        if iteration % opts.log_step == 0:
            print('Iteration [{:5d}/{:5d}] | d_Y_loss: {:6.4f} | d_X_loss: {:6.4f} | g_loss: {:6.4f}'
		   .format(iteration, opts.train_iters, D_Y_loss.item(), D_X_loss.item(),  g_loss.item()))

        # Save the generated samples 
        if iteration % opts.sample_every == 0:
            save_samples(iteration, fixed_Y, fixed_X, G_YtoX, G_XtoY, opts)

        # Save the model parameters
        if iteration % opts.checkpoint_every == 0:
            checkpoint(iteration, G_XtoY, G_YtoX, D_X, D_Y, g_optimizer, dx_optimizer, dy_optimizer, opts)

"""Loads the data, creates checkpoint and sample directories, and starts the training loop."""
def main(opts):
    # Create train and test dataloaders for images from the two domains X and Y
    dataloader_X, test_dataloader_X = get_data_loader2d(img_type=opts.X, opts=opts)
    dataloader_Y, test_dataloader_Y = get_data_loader2d(img_type=opts.Y, opts=opts)

    # Create checkpoint and sample directories
    utils.create_dir(opts.checkpoint_dir)
    utils.create_dir(opts.sample_dir)

    # Start training
    training_loop(dataloader_X, dataloader_Y, test_dataloader_X, test_dataloader_Y, opts)


"""Prints the values of all command-line arguments."""
def print_opts(opts):
    print('=' * 80)
    print('Opts'.center(80))
    print('-' * 80)
    for key in opts.__dict__:
        if opts.__dict__[key]:
            print('{:>30}: {:<30}'.format(key, opts.__dict__[key]).center(80))
    print('=' * 80)


"""Prints the values of all command-line arguments."""
def create_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument('--image_size', type=int, default=128, help='The side length N to convert images to NxN.')
    parser.add_argument('--g_conv_dim', type=int, default=256)
    parser.add_argument('--d_conv_dim', type=int, default=256)
    parser.add_argument('--use_cycle_consistency_loss', action='store_true', default=True, help='Choose whether to include the cycle consistency term in the loss.')
    parser.add_argument('--init_zero_weights', action='store_true', default=False, help='Choose whether to initialize the generator conv weights to 0 (implements the identity function).')

    # Training hyper-parameters
    parser.add_argument('--train_iters', type=int, default=200000, help='The number of training iterations to run (you can Ctrl-C out earlier if you want).')
    parser.add_argument('--batch_size', type=int, default=8, help='The number of images in a batch.')
    parser.add_argument('--num_workers', type=int, default=0, help='The number of threads to use for the DataLoader.')
    parser.add_argument('--lr', type=float, default=0.0003, help='The learning rate (default 0.0003)')
    parser.add_argument('--beta1', type=float, default=0.5)
    parser.add_argument('--beta2', type=float, default=0.999)
    parser.add_argument('--cycle_consistency_lambda', type=float, default=10.0)
    parser.add_argument('--identity_lambda', type=float, default=5.0)
    
    # Data sources
    parser.add_argument('--X', type=str, default='A', choices=['A', 'B'], help='Choose the type of images for domain X.')
    parser.add_argument('--Y', type=str, default='B', choices=['A', 'B'], help='Choose the type of images for domain Y.')


    # Saving directories and checkpoint/sample iterations
    parser.add_argument('--checkpoint_dir', type=str, default='checkpoints_cyclegan')
    parser.add_argument('--sample_dir', type=str, default='samples_cyclegan')
    parser.add_argument('--load', type=str, default=None)
    parser.add_argument('--log_step', type=int , default=10)
    parser.add_argument('--sample_every', type=int , default=500)
    parser.add_argument('--checkpoint_every', type=int , default=500)
    parser.add_argument('--start_iter', type=int, default=0)

    return parser


if __name__ == '__main__':
    parser = create_parser()
    opts = parser.parse_args()

    if opts.use_cycle_consistency_loss:
        opts.sample_dir = 'cyclegan_samples'


    print_opts(opts)
    main(opts)
