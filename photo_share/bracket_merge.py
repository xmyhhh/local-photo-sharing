from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .constants import BRACKET_OUTPUT_DIR
from .paths import resolve_photo

ProgressCallback = Callable[[str, int, int], None]


def merge_bracket_groups(
    root: Path,
    groups: list[dict[str, Any]],
    group_ids: list[int],
    params: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    selected_ids = set(group_ids)
    selected = [group for group in groups if int(group.get("id", -1)) in selected_ids]
    if not selected:
        raise ValueError("No selected bracket groups were found.")

    output_dir = create_output_dir()
    files = []
    total = len(selected)
    for index, group in enumerate(selected, start=1):
        report(progress_callback, f"正在对齐并合成第 {int(group['id'])} 组", index - 1, total)
        output_path = output_dir / f"bracket_group_{int(group['id']):03d}.jpg"
        source_paths = [resolve_photo(root, photo["path"]) for photo in group.get("photos", [])]
        align_method = merge_one_group(source_paths, output_path, params)
        algorithm = get_algorithm(params)
        files.append({
            "groupId": int(group["id"]),
            "name": output_path.name,
            "path": str(output_path),
            "alignMethod": align_method,
            "algorithm": algorithm,
            "downloadUrl": f"/api/bracket-merge/download/{output_dir.name}/{output_path.name}",
        })
        report(progress_callback, f"已完成第 {int(group['id'])} 组", index, total)

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


def merge_one_group(source_paths: list[Path], output_path: Path, params: dict[str, Any]) -> str:
    if not source_paths:
        raise ValueError("Bracket group has no photos.")
    arrays = load_rgb_arrays(source_paths)
    if len(arrays) == 1:
        result_array = arrays[0]
        align_method = "single"
    else:
        aligned, align_method = align_images_feature_homography(arrays)
        result_array = merge_aligned_arrays(aligned, source_paths, params)
    result = Image.fromarray(np.clip(result_array, 0, 255).astype(np.uint8), "RGB")
    result = apply_adjustments(result, params)
    result.save(
        output_path,
        format="JPEG",
        quality=parse_int(params.get("quality"), 70, 98, 92),
        optimize=True,
        progressive=True,
    )
    return align_method


def get_algorithm(params: dict[str, Any]) -> str:
    value = str(params.get("algorithm") or "fusion").lower()
    if value in {"fusion", "debevec", "robertson"}:
        return value
    return "fusion"


def merge_aligned_arrays(images: list[np.ndarray], source_paths: list[Path], params: dict[str, Any]) -> np.ndarray:
    algorithm = get_algorithm(params)
    if algorithm == "debevec":
        return merge_hdr_debevec(images, source_paths)
    if algorithm == "robertson":
        return merge_hdr_robertson(images, source_paths)
    return merge_mertens_fusion(images)


def load_rgb_arrays(source_paths: list[Path]) -> list[np.ndarray]:
    arrays = []
    base_size: tuple[int, int] | None = None
    for source_path in source_paths:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            if base_size is None:
                base_size = image.size
            elif image.size != base_size:
                image = ImageOps.fit(image, base_size, method=Image.Resampling.LANCZOS)
            arrays.append(np.array(image))
    return arrays


def align_images_feature_homography(images: list[np.ndarray]) -> tuple[list[np.ndarray], str]:
    reference_index = len(images) // 2
    reference = images[reference_index]
    aligned = []
    methods = []
    for index, image in enumerate(images):
        if index == reference_index:
            aligned.append(reference)
            methods.append("reference")
            continue
        warped, method = warp_to_reference(image, reference)
        aligned.append(warped)
        methods.append(method)
    if any(method == "homography" for method in methods):
        return aligned, "feature-homography"
    if any(method == "affine" for method in methods):
        return aligned, "feature-affine"
    return aligned, "translation-fallback"


def warp_to_reference(image: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, str]:
    gray_image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gray_reference = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY)
    detector = cv2.ORB_create(nfeatures=5000, scaleFactor=1.2, nlevels=8, fastThreshold=8)
    keypoints_image, descriptors_image = detector.detectAndCompute(gray_image, None)
    keypoints_reference, descriptors_reference = detector.detectAndCompute(gray_reference, None)
    if descriptors_image is None or descriptors_reference is None or len(keypoints_image) < 12 or len(keypoints_reference) < 12:
        return warp_translation(image, gray_image, gray_reference), "translation"

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(descriptors_image, descriptors_reference, k=2)
    good = []
    for pair in matches:
        if len(pair) != 2:
            continue
        first, second = pair
        if first.distance < 0.75 * second.distance:
            good.append(first)
    if len(good) < 10:
        return warp_translation(image, gray_image, gray_reference), "translation"

    src = np.float32([keypoints_image[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
    dst = np.float32([keypoints_reference[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if homography is not None and mask is not None and int(mask.sum()) >= 10:
        height, width = reference.shape[:2]
        return cv2.warpPerspective(image, homography, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT), "homography"

    affine, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if affine is not None and mask is not None and int(mask.sum()) >= 8:
        height, width = reference.shape[:2]
        return cv2.warpAffine(image, affine, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT), "affine"
    return warp_translation(image, gray_image, gray_reference), "translation"


def warp_translation(image: np.ndarray, gray_image: np.ndarray, gray_reference: np.ndarray) -> np.ndarray:
    try:
        shift, _response = cv2.phaseCorrelate(np.float32(gray_image), np.float32(gray_reference))
        matrix = np.float32([[1, 0, shift[0]], [0, 1, shift[1]]])
        height, width = image.shape[:2]
        return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    except Exception:
        return image


def exposure_fusion_average(images: list[np.ndarray]) -> np.ndarray:
    stack = np.stack([image.astype(np.float32) for image in images], axis=0)
    gray = np.mean(stack, axis=3)
    contrast = np.abs(gray - np.mean(gray, axis=(1, 2), keepdims=True))
    weights = contrast + 0.08
    weights = weights / np.sum(weights, axis=0, keepdims=True)
    return np.sum(stack * weights[..., None], axis=0)


def merge_mertens_fusion(images: list[np.ndarray]) -> np.ndarray:
    merge = cv2.createMergeMertens()
    bgr_images = [cv2.cvtColor(image, cv2.COLOR_RGB2BGR).astype(np.float32) / 255.0 for image in images]
    fused = merge.process(bgr_images)
    rgb = cv2.cvtColor(np.clip(fused * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
    return rgb.astype(np.float32)


def merge_hdr_debevec(images: list[np.ndarray], source_paths: list[Path]) -> np.ndarray:
    times = exposure_times(source_paths, len(images))
    bgr_images = [cv2.cvtColor(image, cv2.COLOR_RGB2BGR).astype(np.uint8) for image in images]
    calibrate = cv2.createCalibrateDebevec()
    response = calibrate.process(bgr_images, times)
    merge = cv2.createMergeDebevec()
    hdr = merge.process(bgr_images, times, response)
    return tonemap_hdr_to_rgb(hdr)


def merge_hdr_robertson(images: list[np.ndarray], source_paths: list[Path]) -> np.ndarray:
    times = exposure_times(source_paths, len(images))
    bgr_images = [cv2.cvtColor(image, cv2.COLOR_RGB2BGR).astype(np.uint8) for image in images]
    calibrate = cv2.createCalibrateRobertson()
    response = calibrate.process(bgr_images, times)
    merge = cv2.createMergeRobertson()
    hdr = merge.process(bgr_images, times, response)
    return tonemap_hdr_to_rgb(hdr)


def tonemap_hdr_to_rgb(hdr: np.ndarray) -> np.ndarray:
    hdr = np.nan_to_num(hdr, nan=0.0, posinf=1.0, neginf=0.0)
    tonemap = cv2.createTonemapReinhard(gamma=1.0, intensity=0.0, light_adapt=0.8, color_adapt=0.0)
    ldr = tonemap.process(hdr)
    rgb = cv2.cvtColor(np.clip(ldr * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
    return rgb.astype(np.float32)


def exposure_times(source_paths: list[Path], count: int) -> np.ndarray:
    values: list[float] = []
    for source_path in source_paths:
        values.append(read_exposure_time(source_path))
    if len(values) != count or len({round(value, 8) for value in values if value > 0}) < 2:
        middle = count // 2
        values = [float(2 ** (index - middle)) for index in range(count)]
    return np.array(values, dtype=np.float32)


def read_exposure_time(source_path: Path) -> float:
    try:
        with Image.open(source_path) as image:
            exif = image.getexif()
            value = exif.get(33434)
    except Exception:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            numerator, denominator = value
            return float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0


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


def report(callback: ProgressCallback | None, stage: str, processed: int, total: int) -> None:
    if callback:
        callback(stage, processed, total)


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
