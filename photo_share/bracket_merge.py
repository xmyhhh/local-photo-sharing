from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageEnhance, ImageOps

from .constants import BRACKET_OUTPUT_DIR
from .paths import resolve_photo


def merge_bracket_groups(
    root: Path,
    groups: list[dict[str, Any]],
    group_ids: list[int],
    params: dict[str, Any],
) -> dict[str, Any]:
    selected = [group for group in groups if int(group.get("id", -1)) in set(group_ids)]
    if not selected:
        raise ValueError("No selected bracket groups were found.")

    output_dir = create_output_dir()
    files = []
    for group in selected:
        output_path = output_dir / f"bracket_group_{int(group['id']):03d}.jpg"
        source_paths = [resolve_photo(root, photo["path"]) for photo in group.get("photos", [])]
        merge_one_group(source_paths, output_path, params)
        files.append({
            "groupId": int(group["id"]),
            "name": output_path.name,
            "path": str(output_path),
            "downloadUrl": f"/api/bracket-merge/download/{output_dir.name}/{output_path.name}",
        })

    return {
        "outputDir": str(output_dir),
        "outputId": output_dir.name,
        "files": files,
    }


def create_output_dir() -> Path:
    BRACKET_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BRACKET_OUTPUT_DIR / f"{timestamp}_{uuid4().hex[:8]}"
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def merge_one_group(source_paths: list[Path], output_path: Path, params: dict[str, Any]) -> None:
    if not source_paths:
        raise ValueError("Bracket group has no photos.")
    images = load_aligned_images(source_paths)
    if len(images) == 1:
        result = images[0]
    else:
        result = average_images(images)
    result = apply_adjustments(result, params)
    result.save(
        output_path,
        format="JPEG",
        quality=parse_int(params.get("quality"), 70, 98, 92),
        optimize=True,
        progressive=True,
    )


def load_aligned_images(source_paths: list[Path]) -> list[Image.Image]:
    opened: list[Image.Image] = []
    try:
        for source_path in source_paths:
            with Image.open(source_path) as image:
                opened.append(ImageOps.exif_transpose(image).convert("RGB"))
        base_size = opened[0].size
        aligned = []
        for image in opened:
            if image.size != base_size:
                image = ImageOps.contain(image, base_size)
                canvas = Image.new("RGB", base_size, (0, 0, 0))
                canvas.paste(image, ((base_size[0] - image.width) // 2, (base_size[1] - image.height) // 2))
                image = canvas
            aligned.append(image)
        return aligned
    except Exception:
        for image in opened:
            image.close()
        raise


def average_images(images: list[Image.Image]) -> Image.Image:
    result = images[0].copy()
    for index, image in enumerate(images[1:], start=2):
        result = Image.blend(result, image, 1 / index)
    for image in images:
        image.close()
    return result


def apply_adjustments(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    exposure = parse_float(params.get("exposure"), -2.0, 2.0, 0.0)
    contrast = parse_float(params.get("contrast"), 0.5, 2.0, 1.0)
    saturation = parse_float(params.get("saturation"), 0.0, 2.0, 1.0)
    sharpen = parse_float(params.get("sharpen"), 0.0, 2.0, 0.2)

    result = image
    if exposure:
        result = ImageEnhance.Brightness(result).enhance(2 ** exposure)
    if contrast != 1.0:
        result = ImageEnhance.Contrast(result).enhance(contrast)
    if saturation != 1.0:
        result = ImageEnhance.Color(result).enhance(saturation)
    if sharpen:
        result = ImageEnhance.Sharpness(result).enhance(1 + sharpen)
    return result


def parse_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def parse_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def resolve_merge_output(output_id: str, filename: str) -> Path:
    output_dir = (BRACKET_OUTPUT_DIR / output_id).resolve()
    output_path = (output_dir / filename).resolve()
    try:
        output_path.relative_to(BRACKET_OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise FileNotFoundError(filename) from exc
    if not output_path.is_file() or output_path.suffix.lower() != ".jpg":
        raise FileNotFoundError(filename)
    return output_path


def clear_all_outputs() -> None:
    if BRACKET_OUTPUT_DIR.exists():
        shutil.rmtree(BRACKET_OUTPUT_DIR)
