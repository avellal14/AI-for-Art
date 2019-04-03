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
from models import XNetEncoder2d, XNetDecoder2d, XNetTranslator2d, PatchGANDiscriminator2d
from torchvision import transforms

SEED = 14

# Set the random seed manually for reproducibility.
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed(SEED)


"""Builds the generators and discriminators using the CycleGenerator."""
def create_model(opts):
    E_XtoY = XNetEncoder2d(init_zero_weights=opts.init_zero_weights)
    E_YtoX = XNetEncoder2d(init_zero_weights=opts.init_zero_weights)
    
    D_X = XNetDecoder2d(init_zero_weights=opts.init_zero_weights)
    D_Y = XNetDecoder2d(init_zero_weights=opts.init_zero_weights)
    
    T_XtoY = XNetTranslator2d(init_zero_weights=opts.init_zero_weights)
    T_YtoX = XNetTranslator2d(init_zero_weights=opts.init_zero_weights)
    
    Q_X = PatchGANDiscriminator2d()
    Q_Y = PatchGANDiscriminator2d()

    if torch.cuda.is_available():
        E_XtoY.cuda()
        E_YtoX.cuda()
        
        D_X.cuda()
        D_Y.cuda()        
        
        T_XtoY.cuda()
        T_YtoX.cuda()
        
        Q_X.cuda()
        Q_Y.cuda()
        
        print('Models moved to GPU.')
    return E_XtoY, E_YtoX, D_X, D_Y, T_XtoY, T_YtoX, Q_X, Q_Y


"""Saves the parameters of both generators G_YtoX, G_XtoY and discriminators D_X, D_Y."""
def checkpoint(iteration, E_XtoY, E_YtoX, D_X, D_Y, T_XtoY, T_YtoX, Q_X, Q_Y, opts):
    E_XtoY_path = os.path.join(opts.checkpoint_dir, 'E_XtoY_' +  str(iteration) + '_.pkl')
    E_YtoX_path = os.path.join(opts.checkpoint_dir, 'E_YtoX_' + str(iteration) + '_.pkl')
    D_X_path = os.path.join(opts.checkpoint_dir, 'D_X_' + str(iteration) + '_.pkl')
    D_Y_path = os.path.join(opts.checkpoint_dir, 'D_Y_' + str(iteration) + '_.pkl')
    T_XtoY_path = os.path.join(opts.checkpoint_dir, 'T_XtoY_' +  str(iteration) + '_.pkl')
    T_YtoX_path = os.path.join(opts.checkpoint_dir, 'T_YtoX_' + str(iteration) + '_.pkl')
    Q_X_path = os.path.join(opts.checkpoint_dir, 'Q_X_' + str(iteration) + '_.pkl')
    Q_Y_path = os.path.join(opts.checkpoint_dir, 'Q_Y_' + str(iteration) + '_.pkl')
       
    torch.save(E_XtoY.state_dict(), E_XtoY_path)
    torch.save(E_YtoX.state_dict(), E_YtoX_path)
    torch.save(D_X.state_dict(), D_X_path)
    torch.save(D_Y.state_dict(), D_Y_path)
    torch.save(T_XtoY.state_dict(), T_XtoY_path)
    torch.save(T_YtoX.state_dict(), T_YtoX_path)
    torch.save(Q_X.state_dict(), Q_X_path)
    torch.save(Q_Y.state_dict(), Q_Y_path)
    
    
"""Creates a grid for sampling GAN results. Consist of pairs of columns,
   where the first column in each pair contains images source images and
   the second column in each pair contains images generated by the CycleGAN
   from the corresponding images in the first column.
"""
def merge_images(sources, targets, opts, k=10):
    _, _, h, w = sources.shape
    row = int(np.sqrt(opts.batch_size))
    merged = np.zeros([3, row*h, row*w*2])
    for idx, (s, t) in enumerate(zip(sources, targets)):
        i = idx // row
        j = idx % row

        print("I: ", i, "H: ", h, "J: ", j)
        merged[:, i*h:(i+1)*h, (j*2)*h:(j*2+1)*h] = s
        merged[:, i*h:(i+1)*h, (j*2+1)*h:(j*2+2)*h] = t
    return merged.transpose(1, 2, 0)


"""Saves samples from both generators X->Y and Y->X."""
def save_samples(iteration, fixed_Y, fixed_X, E_XtoY, E_YtoX, D_X, D_Y, T_XtoY, T_YtoX, opts):
    fake_X = D_X(E_YtoX(fixed_Y))
    fake_Y = D_Y(E_XtoY(fixed_X))
    
    cycle_X = D_X(T_YtoX(E_XtoY(fixed_X)))
    cycle_Y = D_Y(T_XtoY(E_YtoX(fixed_Y)))
    
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
    # Create generators and discriminators
    E_XtoY, E_YtoX, D_X, D_Y, T_XtoY, T_YtoX, Q_X, Q_Y = create_model(opts)

    #Create optimizers for all 4 pairs of networks
    e_params = itertools.chain(E_XtoY.parameters(), E_YtoX.parameters())
    d_params = itertools.chain(D_X.parameters(), D_Y.parameters())
    t_params = itertools.chain(T_XtoY.parameters(), T_YtoX.parameters())
    q_params = itertools.chain(Q_X.parameters(), Q_Y.parameters())
   
    e_optimizer = optim.Adam(e_params, opts.lr, [opts.beta1, opts.beta2])
    d_optimizer = optim.Adam(d_params, opts.lr, [opts.beta1, opts.beta2])
    t_optimizer = optim.Adam(t_params, opts.lr, [opts.beta1, opts.beta2])
    q_optimizer = optim.Adam(q_params, opts.lr, [opts.beta1, opts.beta2])
 

    #Get iterators for training and testing data
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

        # 1. Compute the discriminator x loss
        dx_optimizer.zero_grad()
                
        #Real loss
        D_X_real_loss = torch.mean((D_X(images_X))**2) #D_X_real_loss = torch.mean((D_X(images_X)-1)**2)
        fake_X = G_YtoX(images_Y)
        
        #Fake loss
        D_X_fake_loss = torch.mean((D_X(fake_X) - 1)**2) #D_X_fake_loss = torch.mean((D_X(fake_X))**2)
        D_X_loss = (D_X_real_loss + D_X_fake_loss) * .5

        D_X_loss.backward()
        dx_optimizer.step()

        #2. Compute the discriminator y loss
        dy_optimizer.zero_grad()
        
        #Real loss
        D_Y_real_loss = torch.mean((D_Y(images_Y))**2) #D_Y_real_loss = torch.mean((D_Y(images_Y)-1)**2) 
        fake_Y = G_XtoY(images_X)
        
        #Fake loss
        D_Y_fake_loss = torch.mean((D_Y(fake_Y) - 1)**2) #D_Y_fake_loss = torch.mean((D_Y(fake_Y))**2)
        D_Y_loss = (D_Y_real_loss + D_Y_fake_loss) * .5

        D_Y_loss.backward()
        dy_optimizer.step()

        #### GENERATOR TRAINING #### 
        g_optimizer.zero_grad()
        
        # 1. Generate fake images that look like domain X based on real images in domain Y
        fake_X = G_YtoX(images_Y)
        # 2. Compute the generator loss based on domain X
        g_loss = torch.mean((D_X(fake_X)**2)) #g_loss = torch.mean((D_X(fake_X)-1)**2)

        #cycle consistency loss for G_XtoY (add lambda?)
        reconstructed_Y = G_XtoY(fake_X)
        cycle_consistency_loss = torch.mean(torch.abs(images_Y-reconstructed_Y)) #replaced L2 with L1
        g_loss += opts.cycle_consistency_lambda * cycle_consistency_loss

        # 1. Generate fake images that look like domain Y based on real images in domain X
        fake_Y = G_XtoY(images_X)
        # 2. Compute the generator loss based on domain Y
        g_loss += torch.mean((D_Y(fake_Y)**2)) #g_loss += torch.mean((D_Y(fake_Y)-1)**2)

        #cycle consistency loss for G_YtoX (add lambda?)
        reconstructed_X = G_YtoX(fake_Y)
        cycle_consistency_loss = torch.mean(torch.abs(images_X-reconstructed_X)) #replaced L2 with L1
        g_loss += opts.cycle_consistency_lambda * cycle_consistency_loss

        g_loss.backward()
        g_optimizer.step()

        # Print the log info
        if iteration % opts.log_step == 0:
            print('Iteration [{:5d}/{:5d}] | d_Y_loss: {:6.4f} | d_X_loss: {:6.4f} | g_loss: {:6.4f}'
		   .format(iteration, opts.train_iters, D_Y_loss.item(), D_X_loss.item(),  g_loss.item()))

        # Save the generated samples
        if iteration % opts.sample_every == 0:
            save_samples(iteration, fixed_Y, fixed_X, G_YtoX, G_XtoY, opts)

        # Save the model parameters
        if iteration % opts.checkpoint_every == 0:
            checkpoint(iteration, G_XtoY, G_YtoX, D_X, D_Y, opts)


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

    parser.add_argument('--image_size', type=int, default=256, help='The side length N to convert images to NxN.')
    parser.add_argument('--g_conv_dim', type=int, default=256)
    parser.add_argument('--d_conv_dim', type=int, default=256)
    parser.add_argument('--use_cycle_consistency_loss', action='store_true', default=True, help='Choose whether to include the cycle consistency term in the loss.')
    parser.add_argument('--init_zero_weights', action='store_true', default=False, help='Choose whether to initialize the generator conv weights to 0 (implements the identity function).')

    # Training hyper-parameters
    parser.add_argument('--train_iters', type=int, default=200000, help='The number of training iterations to run (you can Ctrl-C out earlier if you want).')
    parser.add_argument('--batch_size', type=int, default=4, help='The number of images in a batch.')
    parser.add_argument('--num_workers', type=int, default=0, help='The number of threads to use for the DataLoader.')
    parser.add_argument('--lr', type=float, default=0.0003, help='The learning rate (default 0.0003)')
    parser.add_argument('--beta1', type=float, default=0.5)
    parser.add_argument('--beta2', type=float, default=0.999)
    parser.add_argument('--cycle_consistency_lambda', type=float, default=10.0)

    # Data sources
    parser.add_argument('--X', type=str, default='1.1', choices=['1.1', '1.0'], help='Choose the type of images for domain X.')
    parser.add_argument('--Y', type=str, default='1.0', choices=['1.1', '1.0'], help='Choose the type of images for domain Y.')

    # Saving directories and checkpoint/sample iterations
    parser.add_argument('--checkpoint_dir', type=str, default='checkpoints_cyclegan')
    parser.add_argument('--sample_dir', type=str, default='samples_cyclegan')
    parser.add_argument('--load', type=str, default=None)
    parser.add_argument('--log_step', type=int , default=10)
    parser.add_argument('--sample_every', type=int , default=500)
    parser.add_argument('--checkpoint_every', type=int , default=1000)

    return parser


if __name__ == '__main__':
    parser = create_parser()
    opts = parser.parse_args()

    if opts.use_cycle_consistency_loss:
        opts.sample_dir = 'cyclegan_samples'


    print_opts(opts)
    main(opts)

