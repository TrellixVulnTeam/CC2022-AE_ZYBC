from typing import Dict
from .base_layer import BaseLayer
import torch.nn as nn
from torch import Tensor
from uu.utils import ftensor as ft
import numpy as np
import torch
from torch.nn.modules.utils import _pair
from torch.nn.common_types import _size_2_t
from  torch.nn.modules.conv import _ConvNd
from torch.nn import functional as F
from uu.utils import padding_calc
from torch.nn.parameter import Parameter

class TiledConv2dFunction(torch.autograd.Function):
    @staticmethod
    def forward(ctx, input, weight, bias, stride,
                        padding, dilation, groups, info, depth, num_conv):
        ctx.depth = depth
        ctx.info = info   
        ctx.num_conv = num_conv             
        if depth == 0:
            out = F.conv2d(input, weight, bias, stride,
                        padding, dilation, groups)
            ctx.save_for_backward(input, out, weight)
        else:
            out = F.conv2d(input, weight, bias, stride,
                        padding, dilation, groups)
            ctx.save_for_backward(input, out, weight)
            # how to save , stride, padding, dilation, groups ??
            #print("net_ out\n", out)
            input_tile_for_next = padding_calc.recreate_input_tile(info, out, depth-1)
            #print("shape input_tile_for_next\n", input_tile_for_next.size())
            #print("input_tile_for_next\n", input_tile_for_next)
            out = input_tile_for_next
         
        return out

    @staticmethod
    def backward(ctx, grad_output):
        print("\n\n** tiled conv2d backward")
        print("** grad_output", grad_output)
        print("** grad_output shape", grad_output.size())
        print("ctx.depth", ctx.depth)
        input, out, weight, = ctx.saved_tensors
        depth = ctx.num_conv-ctx.depth-1
        info = ctx.info
        print("info", info)
        # print("input shape", input.size())
        # print("out shape", out.size())
        # print("weight shape", weight.size())
        if ctx.needs_input_grad[0]:
            if depth == 0:
                # for user input
                weight = Parameter(torch.rot90(weight.data, 2, [2,3]))
                grad_input = F.conv2d(grad_output, weight)
                print(grad_input)
            elif depth == ctx.num_conv-1:
                # a whole grad_output as input of backward
                new_grad_out = padding_calc.get_input_tile(info, grad_output, depth)
                print(new_grad_out)
                weight = Parameter(torch.rot90(weight.data, 2, [2,3]))
                grad_input = F.conv2d(new_grad_out, weight)
                input_tile_for_next = padding_calc.recreate_input_tile(ctx.info, grad_input, depth-1)
                grad_input = input_tile_for_next
                print(grad_input)
            else:
                weight = Parameter(torch.rot90(weight.data, 2, [2,3]))
                grad_input = F.conv2d(grad_output, weight)
                input_tile_for_next = padding_calc.recreate_input_tile(ctx.info, grad_input, depth-1)
                grad_input = input_tile_for_next

        if ctx.needs_input_grad[1]:
            print("compute grad_weight\n")
            # grad_weight = torch.nn.grad.conv2d_weight(input, weight.shape, grad_output)  
                
        #grad_bias = torch.zeros([1, 1, 1, 1]).cuda() #TODO: bias shape??
        # print ("++++++++++++++++shape grad_input", grad_input.size())
        # print ("++++++++++++++++shape grad_weight", grad_weight.size())
        return grad_input, None, None, None, None, None, None, None, None, None

class TiledConv2d(_ConvNd):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: _size_2_t,
        stride: _size_2_t = 1,
        padding: _size_2_t = 0,
        dilation: _size_2_t = 1,
        groups: int = 1,
        bias: bool = True,
        padding_mode: str = 'zeros',  
        # additional info
        depth: int =  0,
        num_conv: int = 0  # num of conv in segment
    ):
        kernel_size_ = _pair(kernel_size)
        stride_ = _pair(stride)
        padding_ = _pair(padding)
        dilation_ = _pair(dilation)
        self.depth = depth
        self.num_conv = num_conv
        super(TiledConv2d, self).__init__(
            in_channels, out_channels, kernel_size_, stride_, padding_, dilation_,
            False, _pair(0), groups, bias, padding_mode)

    def forward(self, input: Tensor, info: Dict) -> Tensor:
        tconv2d = TiledConv2dFunction.apply
        return tconv2d(input, self.weight, self.bias, self.stride,
                        self.padding, self.dilation, self.groups, info, self.depth, self.num_conv)
 