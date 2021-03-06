import numpy as np
import torch
import convsparsenet as csn
from convsparsenet import ConvSparseNet

dtype = csn.dtype


class CausalMP(ConvSparseNet):

    def __init__(self, normed_thresh=None,
                 mask_epsilon=None,
                 backprop_through_inference=True,
                 thresh=0.1,
                 **kwargs):
        ConvSparseNet.__init__(self, **kwargs)
        self.thresh = thresh
        if normed_thresh is None:
            self.normed_thresh = 2/np.sqrt(self.kernel_size)
        else:
            self.normed_thresh = normed_thresh
        self.mask_epsilon = mask_epsilon or 0.01*np.sqrt(1/self.kernel_size)
        self.masks = self.get_masks()
        self.backprop_through_inference = backprop_through_inference

    def infer(self, signal):
        if self.backprop_through_inference:
            everything = self._infer(signal)
        else:
            with torch.no_grad():
                everything = self._infer(signal)
        return everything

    def _infer(self, signal):
        n_signal = signal.shape[0] if len(signal.shape) > 1 else 1
        if not isinstance(signal, torch.Tensor):
            signal = torch.tensor(signal, device=self.device, dtype=dtype,
                                  requires_grad=False)
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
                                               device=self.device,
                                               dtype=dtype,
                                               requires_grad=False)],
                          dim=1)

        weights = self.weights.reshape(self.n_kernel, -1)
        for tt in range(l_signal):
            segment = resid[:, tt:tt+self.kernel_size].clone() # never backprop through residual
            dots = torch.mm(segment, torch.t(weights))
            candidates = torch.argmax(torch.abs(dots), dim=1)
            spikes = dots[torch.arange(batch_size), candidates]
            abspikes = torch.abs(spikes)

            indexer = torch.arange(batch_size)
            segnorms = torch.norm(segment*self.masks[candidates])
            norm_condition = (abspikes/segnorms > self.normed_thresh).float()
            raw_condition = (abspikes > self.thresh).float()

            spikes = raw_condition*norm_condition*spikes
            acts[indexer, candidates, tt] = spikes
            resid[:, tt:tt+self.kernel_size] -= \
                spikes[:, None]*weights[candidates, :]

        padded_signal = torch.cat([signal, torch.zeros([batch_size,
                                                       self.kernel_size-1],
                                                       device=self.device)],
                                  dim=1)
        return acts, {"residual": resid,
                      "reconstruction": padded_signal - resid}

    def loss(self, signal, recon, acts):
        if self.backprop_through_inference:
            return ConvSparseNet.loss(self, signal, recon, acts)
        else:
            return self.mse(signal, recon, acts)

    def extra_updates(self, acts, meta):
        self.masks = self.get_masks()

    def get_masks(self):
        """Returns an array where each row is a binary mask for a filter. The
        mask should be zero outside the region where the filter has significant
        support. Used for ignoring part of signal segments when assessing
        whether a candidate coefficient clears the normed_thresh.
        For now this method assumes that the correct mask has zeros to the left
        and ones to the right of some point. This is consistent with filters
        learned in early experiments."""
        masks = (torch.squeeze(self.weights) > self.mask_epsilon).float()
        starts = torch.argmax(masks, dim=1)  # returns *first* maximum
        for ind in range(self.n_kernel):
            masks[ind, int(starts[ind].item()):] = 1
        return masks

