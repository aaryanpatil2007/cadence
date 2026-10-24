"""L2: per-user GMM over pointer window-stat vectors, impostor GMM for LLR."""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler


class PointerModel:
    def __init__(self):
        self.scaler = StandardScaler()
        self.user_gmm: GaussianMixture | None = None
        self.imp_gmm: GaussianMixture | None = None

    def fit(self, user_X: np.ndarray, impostor_X: np.ndarray) -> "PointerModel":
        self.scaler.fit(np.vstack([user_X, impostor_X]))
        u = self.scaler.transform(user_X)
        i = self.scaler.transform(impostor_X)
        n_u = min(4, max(1, len(u) // 10))
        n_i = min(4, max(1, len(i) // 10))
        self.user_gmm = GaussianMixture(n_u, covariance_type="full",
                                        reg_covar=1e-3, random_state=0).fit(u)
        self.imp_gmm = GaussianMixture(n_i, covariance_type="full",
                                       reg_covar=1e-3, random_state=0).fit(i)
        return self

    def llr(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)
        Xs = self.scaler.transform(X)
        return self.user_gmm.score_samples(Xs) - self.imp_gmm.score_samples(Xs)

    def prob(self, X: np.ndarray) -> np.ndarray:
        """sigmoid(LLR / 10) -> (0,1); calibrated further downstream."""
        return 1.0 / (1.0 + np.exp(-self.llr(X) / 10.0))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "PointerModel":
        with open(path, "rb") as f:
            return pickle.load(f)
