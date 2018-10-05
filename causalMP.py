import numpy as np
import torch
import torch.nn as nn
import convsparsenet

dtype = convsparsenet.dtype


class CausalMP(convsparsenet.ConvSparseNet):

    def __init__(self,
                 thresh=0.1,
                 **kwargs):
        """
        Args:
        thresh          : (float) threshold for activations

        see ConvSparseNet for other parameters
        """
        self.thresh = thresh
        convsparsenet.ConvSparseNet.__init__(self, **kwargs)

    def infer(self, signal):
        n_signal = signal.shape[0]
        if not isinstance(signal, torch.Tensor):
            signal = torch.tensor(signal, device=self.device, dtype=dtype)
        signal = signal.reshape([n_signal, -1])
        l_signal = signal.shape[-1]
        batch_size = signal.shape[0]
        acts = torch.zeros(batch_size,
                           self.n_kernel,
                           l_signal,
                           device=self.device,
                           requires_grad=False)
        resid = torch.cat([signal, torch.zeros([batch_size,
                                               self.kernel_size-1],
                                               device=self.device)],
                          dim=1)

        weights = self.weights.detach().reshape(self.n_kernel, -1)
        for tt in range(l_signal):
            segment = resid[:, tt:tt+self.kernel_size]
            dots = torch.mm(segment, torch.t(weights))
            candidates = torch.argmax(torch.abs(dots), dim=1)
            spikes = dots[torch.arange(batch_size), candidates]
            # segnorm = torch.norm(segment[self.masks[candidates]])
            spikes = (torch.abs(spikes) > self.thresh).float()*spikes
            acts[:, candidates, tt] += spikes
            resid[:, tt:tt+self.kernel_size] -= \
                spikes[:, None]*weights[candidates, :]

        padded_signal = torch.cat([signal, torch.zeros([batch_size,
                                                       self.kernel_size-1],
                                                       device=self.device)],
                                  dim=1)
        return acts, {"residual": resid,
                      "reconstruction": padded_signal - resid}
