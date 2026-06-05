from __future__ import annotations


def image_tensors_from_input(images):
    refs = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
    if isinstance(images, dict):
        refs = [t for t in images.values() if t is not None]
    return refs
