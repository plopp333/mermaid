"""
This implements registration as a command line tool.
Contributors:
  Marc Niethammer: mn@cs.unc.edu
"""

# Note: all images have to be in the format BxCxXxYxZ (BxCxX in 1D and BxCxXxY in 2D)
# I.e., in 1D, 2D, 3D we are dealing with 3D, 4D, 5D tensors. B is the batchsize, and C are the channels
# (for example to support color-images or general multi-modal registration scenarios)

from __future__ import print_function
import set_pyreg_paths

# first do the torch imports
import torch
from torch.autograd import Variable
from time import time
import os
import numpy as np

import pyreg.module_parameters as pars
import pyreg.utils as utils
import pyreg.fileio as fileio
from pyreg import data_utils

prepare_data= True
batch_size =100
def read_images(source_image_name,target_image_name, normalize_spacing=True, normalize_intensities=True, squeeze_image=True):

    I0,hdr0,spacing0,normalized_spacing0 = fileio.ImageIO().read_to_nc_format(source_image_name, intensity_normalize=normalize_intensities, squeeze_image=squeeze_image)
    I1,hdr1,spacing1,normalized_spacing1 = fileio.ImageIO().read_to_nc_format(target_image_name, intensity_normalize=normalize_intensities, squeeze_image=squeeze_image)

    assert (np.all( spacing0 == spacing1) )
    # TODO: do a better test for equality for the images here

    if normalize_spacing:
        spacing = normalized_spacing0
    else:
        spacing = spacing0

    print('Spacing = ' + str(spacing))

    return I0, I1, spacing, hdr0, hdr1


def do_registration(gen_conf, par_algconf ):

    from pyreg.data_wrapper import AdaptVal
    import pyreg.smoother_factory as SF
    import pyreg.multiscale_optimizer as MO
    from pyreg.config_parser import nr_of_threads

    params = pars.ParameterDict()

    par_image_smoothing = par_algconf['algconf']['image_smoothing']
    par_model = par_algconf['algconf']['model']
    par_optimizer = par_algconf['algconf']['optimizer']

    use_map = par_model['deformation']['use_map']
    map_low_res_factor = par_model['deformation']['map_low_res_factor']
    model_name = par_model['deformation']['name']

    if use_map:
        model_name = model_name + '_map'
    else:
        model_name = model_name + '_image'

    # general parameters
    params['model']['registration_model'] = par_algconf['algconf']['model']['registration_model']

    torch.set_num_threads( nr_of_threads )
    print('Number of pytorch threads set to: ' + str(torch.get_num_threads()))
    I0, I1, spacing, md_I0, md_I1 = read_images(gen_conf['moving_image'], gen_conf['target_image'],  gen_conf['normalize_spacing'],  gen_conf['normalize_intensities'],
                                                gen_conf['squeeze_image'])
    from pyreg.prepare_data import prepare_data
    path = '/playpen/zyshen/data/mermaid/data/train'
    img_type = ['*a.mhd']
    skip = False
    sched = 'inter'
    save_path = '../data/data_' + sched + '.h5py'

    #prepare_data(save_path, img_type, path, skip, sched)
    dic = data_utils.read_file(save_path)
    # print(dic['info'])
    print(dic['data'].shape)
    print('finished')
    I0 = dic['data'][2:batch_size,0:1, :,:]
    I1 = dic['data'][2:batch_size,1:2, :,:]
    pair_path = dic['info']['pair_path'][2:batch_size]

    sz = I0.shape

    # create the source and target image as pyTorch variables
    ISource = AdaptVal(Variable(torch.from_numpy(I0.copy()), requires_grad=False))
    ITarget = AdaptVal(Variable(torch.from_numpy(I1), requires_grad=False))

    smooth_images = par_image_smoothing['smooth_images']
    visualize = gen_conf['visualize']
    visualize_step = gen_conf['visualize_step']
    save_fig = gen_conf['save_fig']
    save_fig_path = gen_conf['save_fig_path']
    expr_name = gen_conf['expr_name']
    use_multi_scale = gen_conf['use_multi_scale']

    if smooth_images:
        # smooth both a little bit
        params['image_smoothing'] = par_algconf['algconf']['image_smoothing']
        cparams = params['image_smoothing']
        s = SF.SmootherFactory(sz[2::], spacing).create_smoother(cparams)
        ISource = s.smooth_scalar_field(ISource)
        ITarget = s.smooth_scalar_field(ITarget)

    if not use_multi_scale:
        # create multi-scale settings for single-scale solution
        multi_scale_scale_factors = [1.0]
        multi_scale_iterations_per_scale = [par_optimizer['single_scale']['nr_of_iterations']]
    else:
        multi_scale_scale_factors = par_optimizer['multi_scale']['scale_factors']
        multi_scale_iterations_per_scale = par_optimizer['multi_scale']['scale_iterations']

    if params['model']['registration_model']['forward_model']['smoother']['type'] == 'adaptiveNet':
        params['model']['registration_model']['forward_model']['smoother']['input'] = [ISource, ITarget]
        params['model']['registration_model']['forward_model']['smoother']['use_adp'] = True
    else:
        params['model']['registration_model']['forward_model']['smoother']['use_adp'] = False

    mo = MO.MultiScaleRegistrationOptimizer(sz, spacing, use_map, map_low_res_factor, params)

    optimizer_name = par_optimizer['name']

    mo.set_optimizer_by_name(optimizer_name)
    mo.set_visualization(visualize)
    mo.set_visualize_step(visualize_step)
    mo.set_expr_name(expr_name)
    mo.set_save_fig(save_fig)
    mo.set_save_fig_path(save_fig_path)
    mo.set_save_fig_num(10)
    mo.set_pair_path(pair_path)



    mo.set_model(model_name)

    mo.set_source_image(ISource)
    mo.set_target_image(ITarget)

    mo.set_scale_factors(multi_scale_scale_factors)
    mo.set_number_of_iterations_per_scale(multi_scale_iterations_per_scale)
    mo.set_saving_env()


    # and now do the optimization
    mo.optimize()

    optimized_energy = mo.get_energy()
    warped_image = mo.get_warped_image()
    optimized_map = mo.get_map()
    optimized_reg_parameters = mo.get_model_parameters()

    return warped_image, optimized_map, optimized_reg_parameters, optimized_energy, params, md_I0


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Registers two images')

    required = parser.add_argument_group('required arguments')
    required.add_argument('--moving_image', required=False, default='../test_data/brain_slices/ws_slice.nrrd', help='Moving image')
    required.add_argument('--target_image', required=False, default='../test_data/brain_slices/wt_slice.nrrd', help='Target image')
    parser.add_argument('--expr_name', required=False, default='guassian_0.1_adam', dest='expr_name', help='name of experiment')
    parser.add_argument('--warped_image', required=False, help='Warped image after registration')
    parser.add_argument('--map', required=False, help='Computed map')
    parser.add_argument('--alg_conf', required=False, default='../settings/algconf_settings.json')
    parser.add_argument('--visualize', action='store_false', default=True, help='visualizes the output')
    parser.add_argument('--visualize_step', required=False, default=5, help='Number of iterations between visualization output')
    parser.add_argument('--save_fig', required=False,  default=True, help='save visualized results')
    parser.add_argument('--save_fig_path', required=False, default='../data/saved_results', dest='save_fig_path', help='path to save figures')
    parser.add_argument('--used_config', default=None, help='Name to write out the used configuration')
    parser.add_argument('--use_multiscale', required=False,default=False, help='Uses multi-scale optimization')
    parser.add_argument('--normalize_spacing', required=False,default=True, help='Normalizes the spacing to [0,1]^d')
    parser.add_argument('--normalize_intensities', required=False, default=True, help='Normalizes the intensities so that the 95th percentile is 0.95')
    parser.add_argument('--squeeze_image', required=False, default=True, help='Squeezes out singular dimension from image before processing (e.g., 1x256x256 -> 256x256)')
    parser.add_argument('--write_map', required=False, default=None, help='File to write the resulting map to (if map-based algorithm)')
    parser.add_argument('--write_warped_image', required=False, default=None, help='File to write the warped source image to (if image-based algorithm)')
    parser.add_argument('--write_reg_params', required=False, default=None, help='File to write the optimized registration parameters to')
    args = parser.parse_args()

    # load the specified configuration files
    par_algconf = pars.ParameterDict()
    par_algconf.load_JSON( args.alg_conf )


    gen_conf = {}
    gen_conf['moving_image'] = args.moving_image
    gen_conf['target_image'] = args.target_image
    gen_conf['visualize'] = args.visualize
    gen_conf['visualize_step'] = args.visualize_step
    gen_conf['use_multi_scale'] = args.use_multiscale
    gen_conf['normalize_spacing'] = args.normalize_spacing
    gen_conf['save_fig'] = args.save_fig
    gen_conf['save_fig_path'] = args.save_fig_path
    gen_conf['expr_name'] = args.expr_name
    gen_conf['normalize_intensities'] = args.normalize_intensities
    gen_conf['squeeze_image'] = args.squeeze_image
    used_config = args.used_config
    write_map= args.write_map
    write_warped_image = args.write_warped_image
    write_reg_params = args.write_reg_params

else:
    # load the specified configuration files
    par_algconf = pars.ParameterDict()
    par_algconf.load_JSON('../settings/algconf_settings.json')

    moving_image = '../test_data/brain_slices/ws_slice.nrrd'
    target_image = '../test_data/brain_slices/wt_slice.nrrd'
    visualize = True
    visualize_step = 5
    use_multiscale = False
    normalize_spacing = True
    normalize_intensities = True
    squeeze_image = True
    used_config = 'used_config'

    #TODO: Check what happens here when using .nhdr file; there seems to be some confusion in the library
    # where the datafile is not changed
    write_map = 'map_out.nrrd'
    write_warped_image = 'warped_image_out.nrrd'
    write_reg_params = 'reg_params_out.nrrd'

# now do the actual registration
since = time()

warped_image, optimized_map, optimized_reg_parameters, optimized_energy, params, md_I = \
    do_registration(gen_conf, par_algconf )

print('The final energy was: E={energy}, similarityE={similarityE}, regE={regE}'
                  .format(energy=optimized_energy[0],
                          similarityE=optimized_energy[1],
                          regE=optimized_energy[2]))

if write_map is not None:
    if optimized_map is not None:
        #om_data = optimized_map.data.numpy()
        #nrrd.write( write_map, om_data, md_I )
        fileio.MapIO().write(write_map,optimized_map,md_I)
    else:
        print('Warning: Map cannot be written as it was not computed -- maybe you are using an image-based algorithm?')

if write_warped_image is not None:
    if warped_image is not None:
        #wi_data = warped_image.data.numpy()
        #nrrd.write(write_warped_image, wi_data, md_I)
        fileio.ImageIO().write(write_warped_image,warped_image,md_I)
    else:
        print('Warning: Warped image cannot be written as it was not computed -- maybe you are using a map-based algorithm?')

if write_reg_params is not None:
    if optimized_reg_parameters is not None:
        #rp_data = optimized_reg_parameters.data.numpy()
        #nrrd.write(write_reg_params, rp_data, md_I)
        fileio.GenericIO().write(write_reg_params,optimized_reg_parameters,md_I)
    else:
        print('Warning: optimized parameters were not computed and hence cannot be saved.')

if used_config is not None:
    print('Writing the used configuration to file.')
    params.write_JSON( used_config + '_settings_clean.json')
    params.write_JSON_comments( used_config + '_settings_comments.json')

print("time {}".format(time()-since))



