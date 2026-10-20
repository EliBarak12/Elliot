"""Lazily loaded vision models (CPU). One instance per process, shared by all searches."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
import structlog
import torch
from PIL import Image

log = structlog.get_logger(__name__)

CLIP_NAME = os.environ.get("DSM_CLIP_MODEL", "openai/clip-vit-base-patch32")
OWL_NAME = os.environ.get("DSM_OWL_MODEL", "google/owlvit-base-patch32")
DINO_NAME = os.environ.get("DSM_DINO_MODEL", "facebook/dinov2-small")

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _threads() -> None:
    torch.set_num_threads(int(os.environ.get("DSM_TORCH_THREADS", "2")))


def _load(key: str, loader: Any) -> Any:
    with _lock:
        if key not in _cache:
            _threads()
            t0 = time.time()
            _cache[key] = loader()
            log.info("vision.model.loaded", model=key, seconds=round(time.time() - t0, 1))
        return _cache[key]


class Clip:
    def __init__(self) -> None:
        from transformers import CLIPModel, CLIPProcessor

        self.model = CLIPModel.from_pretrained(CLIP_NAME).eval()
        self.proc = CLIPProcessor.from_pretrained(CLIP_NAME)

    @torch.inference_mode()
    def images(self, imgs: Sequence[np.ndarray | Image.Image]) -> np.ndarray:
        if not imgs:
            return np.zeros((0, self.model.config.projection_dim), np.float32)
        pil = [i if isinstance(i, Image.Image) else Image.fromarray(i) for i in imgs]
        x = self.proc(images=pil, return_tensors="pt")
        f = self.model.get_image_features(**x)
        if not isinstance(f, torch.Tensor):  # newer transformers return a model output
            f = f.pooler_output
        f = f / f.norm(dim=-1, keepdim=True)
        return f.numpy()

    @torch.inference_mode()
    def texts(self, texts: list[str]) -> np.ndarray:
        x = self.proc(text=texts, return_tensors="pt", padding=True)
        f = self.model.get_text_features(**x)
        if not isinstance(f, torch.Tensor):
            f = f.pooler_output
        f = f / f.norm(dim=-1, keepdim=True)
        return f.numpy()

    @property
    def logit_scale(self) -> float:
        return float(self.model.logit_scale.exp())


class Dino:
    def __init__(self) -> None:
        from transformers import AutoImageProcessor, AutoModel

        self.model = AutoModel.from_pretrained(DINO_NAME).eval()
        self.proc = AutoImageProcessor.from_pretrained(DINO_NAME)

    @torch.inference_mode()
    def images(self, imgs: Sequence[np.ndarray | Image.Image]) -> np.ndarray:
        if not imgs:
            return np.zeros((0, self.model.config.hidden_size), np.float32)
        pil = [i if isinstance(i, Image.Image) else Image.fromarray(i) for i in imgs]
        x = self.proc(images=pil, return_tensors="pt")
        out = self.model(**x)
        f = out.pooler_output
        f = f / f.norm(dim=-1, keepdim=True)
        return f.numpy()


class Owl:
    """OWL-ViT open-vocabulary detector; used on close-up inspection images."""

    def __init__(self) -> None:
        from transformers import OwlViTForObjectDetection, OwlViTProcessor

        self.model = OwlViTForObjectDetection.from_pretrained(OWL_NAME).eval()
        self.proc = OwlViTProcessor.from_pretrained(OWL_NAME)

    @torch.inference_mode()
    def detect(self, image: np.ndarray, queries: list[str], threshold: float = 0.05) -> list[dict[str, Any]]:
        pil = Image.fromarray(image)
        x = self.proc(text=[queries], images=pil, return_tensors="pt")
        out = self.model(**x)
        res = self.proc.post_process_grounded_object_detection(
            out, threshold=threshold, target_sizes=[(pil.height, pil.width)]
        )[0]
        dets: list[dict[str, Any]] = []
        for box, score, label in zip(res["boxes"], res["scores"], res["labels"], strict=False):
            dets.append({"box": [float(v) for v in box], "score": float(score), "query": queries[int(label)]})
        dets.sort(key=lambda d: float(d["score"]), reverse=True)
        return dets


def clip() -> Clip:
    return _load("clip", Clip)


def dino() -> Dino:
    return _load("dino", Dino)


def owl() -> Owl:
    return _load("owl", Owl)
