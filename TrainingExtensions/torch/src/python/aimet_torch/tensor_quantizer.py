# /usr/bin/env python3.5
# -*- mode: python -*-
# =============================================================================
#  @@-COPYRIGHT-START-@@
#
#  Copyright (c) 2020, Qualcomm Innovation Center, Inc. All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#
#  1. Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#
#  2. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
#  3. Neither the name of the copyright holder nor the names of its contributors
#     may be used to endorse or promote products derived from this software
#     without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
#  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
#  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.
#
#  SPDX-License-Identifier: BSD-3-Clause
#
#  @@-COPYRIGHT-END-@@
# =============================================================================
""" Custom Tensor Quantizers for PyTorch Op for quantizing weights and activations """

import io
from typing import Union

from aimet_common.defs import QuantScheme
import libpymo
import AimetTensorQuantizer


class TensorQuantizer:
    """
    Base class for Simulation of quantization for a given tensor. This tensor can be a parameter in the model or an
    input to a layer or an output from a layer.
    """

    def __init__(self, bitwidth: int, round_mode: str, quant_scheme: Union[QuantScheme, str],
                 use_symmetric_encodings: bool, enabled_by_default: bool):
        """
        Constructor
        :param bitwidth: Quantization bitwidth
        :param round_mode: Rounding mode (e.g. Nearest)
        :param quant_scheme: Quantization scheme (e.g. Range Learning)
        :param use_symmetric_encodings: True if symmetric encoding is used.  False otherwise.
        :param enabled_by_default: True if quantization of tensor is enabled.  False otherwise.
        """
        super(TensorQuantizer, self).__init__()
        self.round_mode = round_mode
        self.quant_scheme = quant_scheme
        self.use_symmetric_encodings = use_symmetric_encodings
        self.bitwidth = bitwidth
        self.enabled = enabled_by_default


class PickableState:
    """
    State variables in QcQuantizeBase that need to be saved separately when pickling
    """
    def __init__(self, builtin_dict, encoding):
        self.dict = builtin_dict

        if encoding:
            self.min = encoding.min
            self.max = encoding.max
            self.delta = encoding.delta
            self.offset = encoding.offset
            self.bw = encoding.bw


class PostTrainingTensorQuantizer(TensorQuantizer):
    """
    Simulates quantization for the given tensor post training.
    """

    def __init__(self, bitwidth: int, round_mode: str, quant_scheme: str, use_symmetric_encodings: bool,
                 enabled_by_default: bool):
        """
        Constructor
        :param bitwidth: Quantization bitwidth
        :param round_mode: Rounding mode (e.g. Nearest)
        :param quant_scheme: Quantization scheme (e.g. tf, tf_enhanced)
        :param use_symmetric_encodings: True if symmetric encoding is used.  False otherwise.
        :param enabled_by_default: True if quantization of tensor is enabled.  False otherwise.
        """
        super(PostTrainingTensorQuantizer, self).__init__(bitwidth, round_mode, quant_scheme, use_symmetric_encodings,
                                                          enabled_by_default)
        self._cppOp = AimetTensorQuantizer.AimetTensorQuantizer(quant_scheme)
        self.encoding = None

    def __str__(self):
        stream = io.StringIO(newline='\n')
        stream.write('Post Training TensorQuantizer:\n')
        stream.write('  quant-scheme:{}, round_mode={}, bitwidth={}, enabled={}\n'.format(self.quant_scheme,
                                                                                          self.round_mode,
                                                                                          self.bitwidth,
                                                                                          self.enabled))
        if self.encoding:
            stream.write('  min:{}, max={}, delta={}, offset={}\n'.format(self.encoding.min, self.encoding.max,
                                                                          self.encoding.delta, self.encoding.offset))
        else:
            stream.write('  no encoding\n')

        return stream.getvalue()


    def __getstate__(self):
        # Copy the object's state from self.__dict__ which contains
        # all our instance attributes. Always use the dict.copy()
        # method to avoid modifying the original state.
        state = PickableState(self.__dict__.copy(), self.encoding)

        # Remove the unpicklable entries.
        del state.dict['_cppOp']
        del state.dict['encoding']

        return state

    def __setstate__(self, state):
        # Restore instance attributes
        self.__dict__.update(state.dict)

        # Create the c++ op
        self._cppOp = AimetTensorQuantizer.AimetTensorQuantizer(self.quant_scheme)

        # Create the encoding object
        if hasattr(state, 'min'):
            self.encoding = libpymo.TfEncoding()
            self.encoding.bw = state.bw
            self.encoding.max = state.max
            self.encoding.min = state.min
            self.encoding.delta = state.delta
            self.encoding.offset = state.offset
        else:
            self.encoding = None

    def update_encoding_stats(self, tensor):
        """
        Update the stats for computing encoding
        :param tensor: Tensor to use for updating the encodings stats
        :return: None
        """
        if self.enabled:
            self._cppOp.updateStats(tensor, tensor.is_cuda)

    def compute_encoding(self):
        """
        Compute the quantization encoding for this tensor
        :return:
        """
        if self.enabled:
            encoding, is_encoding_valid = self._cppOp.getEncoding(self.bitwidth, self.use_symmetric_encodings)

            if is_encoding_valid:
                self.encoding = encoding

    def quantize_dequantize(self, tensor, round_mode):
        """
        Quantize-dequantize the tensor, using the saved encoding for this tensor
        :param tensor: Tensor to quantize-dequantize
        :param round_mode: Rounding mode
        :return: Resulting tensor
        """
        if self.enabled:
            quantized_tensor = self._cppOp.quantizeDequantize(tensor, self.encoding, round_mode, tensor.is_cuda)
        else:
            quantized_tensor = tensor

        return quantized_tensor

    def reset_encoding_stats(self):
        """
        Resets the encodings stats
        :return: None
        """
        self._cppOp.resetEncodingStats()
