from typing import Dict
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
                        padding, dilation, groups, info, uniq_id, is_ccheckpoint):
        print("== tiled conv2d forward")
        #print("input shape", input.size())
        c_info = info[0][uniq_id]   
        #print("current fwd info", c_info)
        s_depth = c_info.local_idex  # depth in current segment
        
        if c_info.local_first: # if it is the first conv in a segment then padding
            padding_info = c_info.padding_info
            pd = torch.nn.ConstantPad2d(padding_info, 0)
            input = pd(input)

        #print("af input shape", input.size())
        ctx.info = info           
        if s_depth == 0: 
            # depth is 0 if it is the last conv or the last one in segment
            if not is_ccheckpoint:    
                ctx.input = input
                ctx.weight = weight
                ctx.padding = padding
                ctx.stride = stride
                ctx.groups = groups
                ctx.uniq_id = uniq_id
                #force no auto padding in our customized functions.
                padding = (0,0)
                out = F.conv2d(input, weight, bias, stride,
                        padding, dilation, groups)
            else:
                #force no auto padding in our customized functions.
                padding = (0,0)
                out = F.conv2d(input, weight, bias, stride,
                        padding, dilation, groups)
            print("shape input_tile_for_next\n", out.size())
        else:
            if not is_ccheckpoint:            
                ctx.input = input
                ctx.weight = weight
                ctx.padding = padding
                ctx.stride = stride
                ctx.groups = groups
                ctx.uniq_id=uniq_id
                #force no auto padding in our customized functions.
                padding = (0,0)
                out = F.conv2d(input, weight, bias, stride,
                        padding, dilation, groups)
            else:
                #force no auto padding in our customized functions.
                padding = (0,0)
                out = F.conv2d(input, weight, bias, stride,
                        padding, dilation, groups)
         
            #print("net_ out\n", out)
            # TODO : how to get the direct children after this??
            next_id = c_info.next_id
            input_tile_for_next = padding_calc.recreate_input_tile_f(info, out, next_id)
            #print("input_tile_for_next\n", input_tile_for_next)
            out = input_tile_for_next
            print("shape input_tile_for_next\n", input_tile_for_next.size())
        return out

    @staticmethod
    def backward(ctx, grad_output):
        f_info = ctx.info[0][ctx.uniq_id]
        b_info = ctx.info[1][ctx.uniq_id]
        print("I am", f_info.coord)
        if ctx.input.is_cuda:
            if torch.backends.cudnn.enabled:
                print("@@@ using cudnn bkw")
                weight_tensor = ctx.weight
                weight_size = weight_tensor.size()
                padding = ctx.padding   #original padding
                stride = ctx.stride
                group = ctx.groups 
                input_tensor = ctx.input 
                input_size = input_tensor.size()
                dilation = (1,1)
                our_padding = (0,0)

                g_depth = b_info.op_idex    # global depth
                rev_g_depth = f_info.op_idex
                l_depth = f_info.local_idex
                local_first = f_info.local_first
                # Handle Grad_in
                # TODO: maybe need clean up branch logic
                if ctx.needs_input_grad[0]:
                    if rev_g_depth == 0:
                        # the last stage in regular order
                        # a whole grad_output as input of backward
                        print("ouput grad ++ input shape", input_size)
                        #print("ouput grad ++ input", input_tensor)
                        print("weight shape", weight_size)
                        print("grad_output shape", grad_output.size())
                        first_op_in_seg = ctx.uniq_id
                        new_grad_out = padding_calc.get_input_tile(ctx.info[1], grad_output, first_op_in_seg)
                        # since I remove padding from get_input_tile, so manually do it here.
                        grad_input = torch.cudnn_convolution_backward_input(input_size, new_grad_out, weight_tensor, our_padding, stride, dilation, group, False, False, False)
                        grad_input = padding_calc.resize_grad_in(f_info, grad_input)
                        print("grad_input", grad_input.size())
                    elif g_depth == 0: 
                        # for user input
                        print("input grad ++ input shape", input_size)
                        #print("input grad ++ input", input_tensor)
                        print("weight shape", weight_size)
                        print("grad_output shape", grad_output.size())
                        grad_input = torch.cudnn_convolution_backward_input(input_size, grad_output, weight_tensor, our_padding, stride, dilation, group, False, False, False)
                        print("final", grad_input.size())
                        # reshape to tile size before end of the segment
                        grad_input = padding_calc.reshape_for_final(ctx.info[1][-11], f_info, grad_input)
                    elif l_depth == 0 and not local_first:  
                        # the last conv in local continous conv segment
                        print("local last ++ input shape", input_size)
                        #print("local last ++ input", input_tensor)
                        print("weight shape", weight_size)
                        print("grad_output shape", grad_output.size())
                        grad_input = torch.cudnn_convolution_backward_input(input_size, grad_output, weight_tensor, our_padding, stride, dilation, group, False, False, False)
                        #shrink if original input is padded.
                        print("grad_input", grad_input.size())
                        grad_input = padding_calc.resize_grad_in(f_info, grad_input)
                        print("new grad_input", grad_input.size())
                    elif local_first:   # we nned to remove padding part only
                        print("in the local first ++ input shape", input_size)
                        #print("in the local first  ++ input", input_tensor)
                        print("weight shape", weight_size)
                        print("grad_output shape", grad_output.size())
                        grad_input = torch.cudnn_convolution_backward_input(input_size, grad_output, weight_tensor, our_padding, stride, dilation, group, False, False, False)
                        #shrink if original input is padded.
                        grad_input = padding_calc.resize_grad_in_1(f_info, grad_input)
                        print("grad_input", grad_input.size())
                    else:
                        #TODO:logic something wrong!!!! if the local first do something
                        print("in the middle ++ input shape", input_size)
                        #print("in the middle ++ input", input_tensor)
                        print("weight shape", weight_size)
                        print("grad_output shape", grad_output.size())
                        grad_input = torch.cudnn_convolution_backward_input(input_size, grad_output, weight_tensor, our_padding, stride, dilation, group, False, False, False)
                        #shrink if original input is padded.
                        grad_input = padding_calc.resize_grad_in(f_info, grad_input)
                        print("grad_input", grad_input.size())
                else:
                    grad_input = None

                if ctx.needs_input_grad[1]:
                    # need to reshape both grad_out and input_tensor
                    #debug 
                    nontiled_grad_out = ctx.info[0][-1*ctx.uniq_id][1]
                    nontiled_activation = ctx.info[0][-1*ctx.uniq_id][0]

                    if f_info.next_id == -99:
                        # TODO, looks some issue here.
                        next_f_info = ctx.info[0][-11]
                    else:
                        next_f_info = ctx.info[0][f_info.next_id] # TODO how to get next info....
 
                    new_grad_output, new_input_tensor = padding_calc.reshape_grad_out_input_tensor_for_weight_update(grad_output, input_tensor, \
                                                        f_info, next_f_info, weight_size,\
                                                        padding, stride, nontiled_grad_out, nontiled_activation) # 
                    grad_weight = torch.cudnn_convolution_backward_weight(weight_size , new_grad_output, new_input_tensor, our_padding, stride, dilation, group, False, False, False)
                
                        
                    grad_bias = None
                else:
                    grad_weight = None
                    grad_bias = None
            else:
                print("using naive cuda bkw")
        else:
            print("using cpu bkw")

        print("##############return grad_in in conv2d", grad_input[0,0,0,0:10]) 
        return grad_input, grad_weight, grad_bias, None, None, None, None, None, None, None, None

    

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
        # depth: int =  0,
        # num_conv: int = 0,  # num of conv in segment
        is_ccheckpoint = False
    ):
        kernel_size_ = _pair(kernel_size)
        stride_ = _pair(stride)
        padding_ = _pair(padding)
        dilation_ = _pair(dilation)
        # self.depth = depth
        # self.num_conv = num_conv
        self.is_ccheckpoint = is_ccheckpoint
        super(TiledConv2d, self).__init__(
            in_channels, out_channels, kernel_size_, stride_, padding_, dilation_,
            False, _pair(0), groups, bias, padding_mode)

    def forward(self, *inputs) -> Tensor:
        print("id", id(self))
        first_op = False
        if type (inputs[0]) == tuple:
            # to remove additional packing in tuple
            inputs = list(inputs[0])
        if len(inputs) == 2:
            input, info = inputs
            self.is_ccheckpoint = False
        elif len(inputs) == 3:
            input, info, is_ccheckpoint = inputs
            self.is_ccheckpoint = is_ccheckpoint
        else:
            print("missing info in cConv2d")
            assert False
        
        
        tconv2d = TiledConv2dFunction.apply
        uniq_id = id(self)
        pi = info[0][uniq_id]
        
        if pi.op_idex == 0: # last stage in the segment or in the global network
           return tconv2d(input, self.weight, self.bias, self.stride,
                       self.padding, self.dilation, self.groups, info, uniq_id, self.is_ccheckpoint)
        else:
           return tconv2d(input, self.weight, self.bias, self.stride,
                       self.padding, self.dilation, self.groups, info, uniq_id, self.is_ccheckpoint), info, self.is_ccheckpoint


                
 