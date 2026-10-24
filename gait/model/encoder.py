"""L1: tiny contrastive keystroke encoder (~55k params).

Input: last <=32 keystrokes, each row from schema.seq_item_to_row:
[hold, dd, ud, uu, cls, bigram, shift_side, cmd_side, autorepeat].
Output: L2-normalized 32-d embedding. Scored by cosine to the user prototype.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from gait.features.schema import N_CLASSES, N_BIGRAMS

MAX_LEN = 32
EMB_DIM = 32


def device() -> torch.device:
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


class KeystrokeEncoder(nn.Module):
    def __init__(self, ch: int = 64):
        super().__init__()
        self.cls_emb = nn.Embedding(N_CLASSES, 8)
        self.bigram_emb = nn.Embedding(N_BIGRAMS, 8)
        in_dim = 4 + 8 + 8 + 3 + 3 + 1  # 27
        self.convs = nn.ModuleList([
            nn.Conv1d(in_dim if i == 0 else ch, ch, 5, padding=2)
            for i in range(3)
        ])
        self.norms = nn.ModuleList([nn.LayerNorm(ch) for _ in range(3)])
        self.head = nn.Linear(2 * ch, EMB_DIM)

    def forward(self, rows: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """rows: (B, L, 9) raw seq rows; mask: (B, L) 1 for valid."""
        timing = rows[..., :4]
        cls = self.cls_emb(rows[..., 4].long().clamp(0, N_CLASSES - 1))
        big = self.bigram_emb(rows[..., 5].long().clamp(0, N_BIGRAMS - 1))
        shift = F.one_hot(rows[..., 6].long().clamp(0, 2), 3).float()
        cmd = F.one_hot(rows[..., 7].long().clamp(0, 2), 3).float()
        rep = rows[..., 8:9]
        x = torch.cat([timing, cls, big, shift, cmd, rep], dim=-1)  # (B,L,27)
        x = x.transpose(1, 2)  # (B,C,L)
        for conv, norm in zip(self.convs, self.norms):
            x = conv(x)
            x = norm(x.transpose(1, 2)).transpose(1, 2)
            x = F.gelu(x)
        x = x.transpose(1, 2)  # (B,L,C)
        m = mask.unsqueeze(-1)
        mean = (x * m).sum(1) / m.sum(1).clamp(min=1)
        x_masked = x.masked_fill(m == 0, -1e9)
        mx = x_masked.max(1).values
        emb = self.head(torch.cat([mean, mx], dim=-1))
        return F.normalize(emb, dim=-1)


def pad_batch(seqs: list[np.ndarray]) -> tuple[torch.Tensor, torch.Tensor]:
    B = len(seqs)
    rows = torch.zeros(B, MAX_LEN, 9)
    mask = torch.zeros(B, MAX_LEN)
    for i, s in enumerate(seqs):
        L = min(len(s), MAX_LEN)
        rows[i, :L] = torch.tensor(np.asarray(s[-MAX_LEN:], dtype=np.float32))
        mask[i, :L] = 1
    return rows, mask


def supcon_loss(emb: torch.Tensor, labels: torch.Tensor, tau: float = 0.1) -> torch.Tensor:
    """Supervised contrastive loss over a batch of normalized embeddings."""
    sim = emb @ emb.T / tau
    n = emb.shape[0]
    eye = torch.eye(n, dtype=torch.bool, device=emb.device)
    sim = sim.masked_fill(eye, -1e9)
    pos = (labels.unsqueeze(0) == labels.unsqueeze(1)) & ~eye
    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    pos_count = pos.sum(1)
    valid = pos_count > 0
    if valid.sum() == 0:
        return torch.tensor(0.0, device=emb.device, requires_grad=True)
    loss = -(log_prob * pos).sum(1)[valid] / pos_count[valid]
    return loss.mean()


def augment(seq: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Time-scale, timing noise, random crop (timing dims are log1p seconds)."""
    s = seq.copy().astype(np.float32)
    # time-scale: operate in linear time then back to log1p
    scale = rng.uniform(0.9, 1.1)
    lin = np.expm1(s[:, :4])
    lin[:, [0, 1, 3]] *= scale
    lin[:, 2] = (lin[:, 2]) * scale  # ud is shifted by +0.5 pre-log; approx ok
    lin *= 1 + rng.normal(0, 0.05, size=lin.shape)
    s[:, :4] = np.log1p(np.maximum(lin, 0.0))
    if len(s) > 24:
        L = int(rng.integers(24, min(len(s), 32) + 1))
        start = int(rng.integers(0, len(s) - L + 1))
        s = s[start:start + L]
    return s


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
