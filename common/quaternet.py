# ---------------------------------------------- #
# Copyright (c) 2018-present, Facebook, Inc.
# https://github.com/facebookresearch/QuaterNet
# ---------------------------------------------- #

import torch
import torch.nn as nn
import torch.nn.functional as F
from common.quaternion import qmul

class QuaterNet(nn.Module):
    """
    QuaterNet general architecture.
    Attributes
    ----------
        * num_joints   : number of skeleton joints.
        * num_outputs  : extra inputs/outputs, in addition to joint rotations.
        * num_controls : extra input features.
        * model_velocities : flag to add a queternion multiplication block on the
                             RNN output to force the network to model velocities
                             instead of absolute rotations.
        * fc1, fc2 : ReLU fully conected layers (if extra input features)
        * rnn : Gated recurrent unit.
        * fc : output ReLU fully-connected layer.
    Methods
    -------
        * __init__() : initialization
        * forward()  : forward propagation 
    """


    def __init__( self, num_joints, num_outputs = 0,
                  num_controls = 0, model_velocities = False ):
        """
        QuaterNet Constructor.
        Input
        -----
            * num_joints   : number of skeleton joints.
            * num_outputs  : extra inputs/outputs, in addition to joint rotations.
            * num_controls : extra input features.
            * model_velocities : flag to add a queternion multiplication block on the
                                 RNN output to force the network to model velocities
                                 instead of absolute rotations.
                        
        Output
        ------
            * None
        """

        # ------------- QuaterNet attributes -------------
        super().__init__()
        self.num_joints   = num_joints
        self.num_outputs  = num_outputs
        self.num_controls = num_controls
        self.model_velocities = model_velocities
        # ------------------------------------------------

        # ----- ReLU Layers (if extra input features) ---- #
        if num_controls > 0:
            fc1_size = 30
            fc2_size = 30
            self.fc1 = nn.Linear(num_controls, fc1_size)
            self.fc2 = nn.Linear(fc1_size, fc2_size)
            self.relu = nn.LeakyReLU(0.05, inplace = True)
        else:
            fc2_size = 0
        # ------------------------------------------------ #

        # ------------ Gated Recurrent Units ------------- #
        h_size = 1000
        rnn_layers = 2
        self.rnn = nn.GRU( input_size = 4 * num_joints + num_outputs + fc2_size,
                           hidden_size = h_size    ,
                           num_layers = rnn_layers ,
                           batch_first = True      )
        # ------------------------------------------------ #

    
        
        # Initializing hidden state
        self.h0 = nn.Parameter( torch.zeros( rnn_layers, 1, h_size).normal_(std = 0.01),
                                requires_grad = True )
        
        # Output fully connected layer
        self.fc = nn.Linear(h_size, 4 * num_joints + num_outputs)
    


    def forward(self, x, h = None, return_prenorm = False, return_all = False):
        """
        Forward propagation.
        Input
        ------
            * x : input tensor
                  size = ( batch_size, sequence_length, 4 * num_joints + num_outputs + fc2_size)
            * h : hidden state; if None, it returns to the learned initial state
            * return_prenorm : flag -> if True, it returns the quaternions prior to normalization
            * return_all     : flag -> if True, it returns all sencuance_lenght frames,
                                       otherwise, it returns only the last frame.
        Output
        ------
            model evaluation
        """

        assert len(x.shape) == 3
        assert x.shape[-1] == 4 * self.num_joints + self.num_outputs + self.num_controls

        x_orig = x

        # ----- ReLU Layers (if extra input features) ---- #
        if self.num_controls > 0:
            controls = x[:, :, (4*self.num_joints + self.num_outputs):]
            controls = self.relu( self.fc1(controls) )
            controls = self.relu( self.fc2(controls) )
            x = torch.cat( ( x[:, :, :(4*self.num_joints + self.num_outputs)], controls), dim = 2 )
        # ------------------------------------------------ #
        
        # ------------ Gated Recurrent Units ------------- #
        if h is None:
            h = self.h0.expand(-1, x.shape[0], -1).contiguous()
        x, h = self.rnn(x, h)
        # ------------------------------------------------ #

        # output
        if return_all:
            x = self.fc(x)
        else:
            x = self.fc( x[:, -1:] )
            x_orig = x_orig[:, -1:]

        # normalize only quaternion rotations
        pre_normalized = x[:, :, :(4*self.num_joints)].contiguous()
        normalized = pre_normalized.view(-1, 4)
        
        # --- Residual arquitecture to model velocities -- #
        if self.model_velocities:
            normalized = qmul( normalized, x_orig[:, :, :(4*self.num_joints)].contiguous().view(-1, 4) )
        # ------------------------------------------------ #

        # Normalize quaternions
        normalized = F.normalize( normalized, dim = 1 ).view( pre_normalized.shape )

        # ---- Add extra features (if extra features) ---- #
        if self.num_outputs > 0:
            x = torch.cat( (normalized, x[:, :, (4*self.num_joints):]), dim = 2 )
        else:
            x = normalized
        # ------------------------------------------------ #
        
        # Output
        if return_prenorm:
            return x, h, pre_normalized
        else:
            return x, h