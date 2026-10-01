"""Stable identity of the actual local tensors used for training and inference."""
from __future__ import annotations

import hashlib


def model_weights_fingerprint(model: object) -> str:
    import torch

    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):  # type: ignore[attr-defined]
        if not isinstance(tensor, torch.Tensor):
            raise ValueError("model state contains a non-tensor value")
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(value.shape)).encode("ascii"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(memoryview(value.view(torch.uint8).numpy()))
    return digest.hexdigest()
