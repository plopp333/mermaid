"""
Spatial transform functions in 1D, 2D, and 3D.

.. todo::
    Add CUDA implementation. Could be based of the existing 2D CUDA implementation.
"""
from __future__ import absolute_import

import sys

import torch
from torch.autograd import Function
from torch.nn import Module
from cffi import FFI
from pyreg.data_wrapper import USE_CUDA, STNTensor, STNVal

if sys.version_info >= (3, 0):
    if USE_CUDA:
        from pyreg.libraries._ext import my_lib_1D, my_lib_2D, my_lib_3D
    from pyreg.libraries._ext import my_lib_nd
else:
    if USE_CUDA:
        from pyreg.libraries._ext import my_lib_1D, my_lib_2D, my_lib_3D
    from pyreg.libraries._ext import my_lib_nd

from . import map_scale_utils

ffi = FFI()





#
# class STNFunction_ND_BCXYZ(Module):
#     """
#    Spatial transform function for 1D, 2D, and 3D. In BCXYZ format (this IS the format used in the current toolbox).
#    """
#
#     def __init__(self, spacing):
#         """
#         Constructor
#
#         :param ndim: (int) spatial transformation of the transform
#         """
#         super(STNFunction_ND_BCXYZ, self).__init__()
#         self.spacing = spacing
#         self.ndim = len(spacing)
#
#     def forward_stn(self, input1, input2, ndim):
#         if ndim==1:
#             raise ValueError("Not implemented")
#         if ndim==2:
#             output = torch.nn.functional.grid_sample(input1, input2.permute([0, 2, 3, 1]), mode='bilinear',
#                                           padding_mode='border')
#         if ndim==3:
#             output = torch.nn.functional.grid_sample(input1, input2.permute([0, 2, 3, 4, 1]), mode='trilinear', padding_mode='border')
#         return output
#
#     def forward(self, input1, input2):
#         """
#         Perform the actual spatial transform
#
#         :param input1: image in BCXYZ format
#         :param input2: spatial transform in BdimXYZ format
#         :return: spatially transformed image in BCXYZ format
#         """
#
#         assert(len(self.spacing)+2==len(input2.size()))
#
#         output = self.forward_stn(input1, map_scale_utils.scale_map(input2,self.spacing), self.ndim)
#         # print(STNVal(output, ini=-1).sum())
#         return output
#














class STNFunction_ND_BCXYZ(Function):
    """
   Spatial transform function for 1D, 2D, and 3D. In BCXYZ format (this IS the format used in the current toolbox).
   """

    def __init__(self, spacing,zero_boundary=False):
        """
        Constructor

        :param ndim: (int) spatial transformation of the transform
        """
        super(STNFunction_ND_BCXYZ, self).__init__()
        self.spacing = spacing
        self.ndim = len(spacing)
        self.zero_boundary = zero_boundary

    def forward_stn(self, input1, input2, output, ndim, device_c, use_cuda=USE_CUDA,zero_boundary=False):
        if use_cuda:
            if ndim == 1:
                my_lib_1D.BilinearSamplerBCW_updateOutput_cuda_1D(input1, input2, output, device_c, int(zero_boundary))
            elif ndim == 2:
                my_lib_2D.BilinearSamplerBCWH_updateOutput_cuda_2D(input1, input2, output, device_c, int(zero_boundary))
            elif ndim == 3:
                my_lib_3D.BilinearSamplerBCWHD_updateOutput_cuda_3D(input1, input2, output, device_c, int(zero_boundary))
        else:
            my_lib_nd.BilinearSamplerBCXYZ_updateOutput_ND(input1, input2, output, ndim, int(zero_boundary))

    def backward_stn(self, input1, input2, grad_input1, grad_input2, grad_output, ndim, device_c, use_cuda=USE_CUDA,zero_boundary=False):
        if use_cuda:
            if ndim == 1:
                my_lib_1D.BilinearSamplerBCW_updateGradInput_cuda_1D(input1, input2, grad_input1, grad_input2,
                                                                     grad_output, device_c, int(zero_boundary))
            elif ndim == 2:
                my_lib_2D.BilinearSamplerBCWH_updateGradInput_cuda_2D(input1, input2, grad_input1, grad_input2,
                                                                      grad_output, device_c, int(zero_boundary))
            elif ndim == 3:
                my_lib_3D.BilinearSamplerBCWHD_updateGradInput_cuda_3D(input1, input2, grad_input1, grad_input2,
                                                                       grad_output, device_c, int(zero_boundary))
        else:
            my_lib_nd.BilinearSamplerBCXYZ_updateGradInput_ND(input1, input2, grad_input1, grad_input2, grad_output,
                                                              ndim, int(zero_boundary))

    def forward(self, input1, input2):
        """
        Perform the actual spatial transform

        :param input1: image in BCXYZ format
        :param input2: spatial transform in BdimXYZ format
        :return: spatially transformed image in BCXYZ format
        """

        assert(len(self.spacing)+2==len(input2.size()))

        self.input1 = STNVal(input1, ini=1)
        self.input2 = STNVal(input2, ini=1)
        self.device_c = ffi.new("int *")
        if self.ndim == 1:
            output = STNTensor(input1.size()[0], input1.size()[1], input2.size()[2]).zero_()
        elif self.ndim == 2:
            output = STNTensor(input1.size()[0], input1.size()[1], input2.size()[2], input2.size()[3]).zero_()
        elif self.ndim == 3:
            output = STNTensor(input1.size()[0], input1.size()[1], input2.size()[2], input2.size()[3],
                               input2.size()[4]).zero_()
        else:
            raise ValueError('Can only process dimensions 1-3')
        # print('decice %d' % torch.cuda.current_device())
        if USE_CUDA:
            self.device = torch.cuda.current_device()
        else:
            self.device = -1
        self.device_c[0] = self.device

        # the spatial transformer code expects maps in the range of [-1,1]^d
        # So first rescale the map (i.e., input2) and then account for this rescaling in the gradient

        self.forward_stn(input1, map_scale_utils.scale_map(input2,self.spacing), output, self.ndim, self.device_c, zero_boundary= self.zero_boundary)
        # print(STNVal(output, ini=-1).sum())
        return STNVal(output, ini=-1)

    def backward(self, grad_output):
        """
        Computes the gradient

        :param grad_output: grad output from previous "layer"
        :return: gradient
        """
        grad_input1 = STNTensor(self.input1.size()).zero_()
        grad_input2 = STNTensor(self.input2.size()).zero_()
        grad_output = STNVal(grad_output, ini=1)
        # print grad_output.view(1, -1).sum()
        # print('backward decice %d' % self.device)

        # also needs to scale the input map first
        self.backward_stn(self.input1, map_scale_utils.scale_map(self.input2,self.spacing), grad_input1, grad_input2, grad_output, self.ndim, self.device_c, zero_boundary=  self.zero_boundary)
        # print( STNVal(grad_input1, ini=-1).sum(), STNVal(grad_input2, ini=-1).sum())

        map_scale_utils.scale_map_grad(grad_input2,self.spacing)

        return STNVal(grad_input1, ini=-1), STNVal(grad_input2, ini=-1)


###################################################################################################################

