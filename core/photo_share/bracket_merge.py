from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .constants import BRACKET_MERGE_WORKERS, BRACKET_OUTPUT_DIR
from .paths import resolve_photo

ProgressCallback = Callable[[str, int, int], None]


def merge_bracket_groups(
    root: Path,
    groups: list[dict[str, Any]],
    group_ids: list[int],
    params: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    _require_cv2()
    selected_ids = set(group_ids)
    selected = [group for group in groups if int(group.get("id", -1)) in selected_ids]
    if not selected:
        raise ValueError("No selected bracket groups were found.")

    output_dir = create_output_dir()
    files: list[dict[str, Any]] = []
    total = len(selected)
    completed = 0
    report(progress_callback, f"正在并行合成 {total} 组", 0, total)
    worker_count = min(BRACKET_MERGE_WORKERS, max(1, total))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="bracket-merge-group") as executor:
        future_map = {
            executor.submit(merge_group_to_file, root, group, output_dir, params): int(group["id"])
            for group in selected
        }
        for future in as_completed(future_map):
            files.append(future.result())
            completed += 1
            report(progress_callback, f"已完成 {completed}/{total} 组合成", completed, total)
    files.sort(key=lambda item: item["groupId"])

    return {
        "outputDir": str(output_dir),
        "outputId": output_dir.name,
        "files": files,
    }


def merge_group_to_file(root: Path, group: dict[str, Any], output_dir: Path, params: dict[str, Any]) -> dict[str, Any]:
    group_id = int(group["id"])
    output_path = output_dir / f"bracket_group_{group_id:03d}.jpg"
    source_paths = [resolve_photo(root, photo["path"]) for photo in group.get("photos", [])]
    align_method = merge_one_group(source_paths, output_path, params)
    return {
        "groupId": group_id,
        "name": output_path.name,
        "path": str(output_path),
        "alignMethod": align_method,
        "algorithm": get_algorithm(params),
        "imageUrl": f"/api/bracket-merge/image/{output_dir.name}/{output_path.name}",
        "downloadUrl": f"/api/bracket-merge/download/{output_dir.name}/{output_path.name}",
    }


def create_output_dir() -> Path:
    BRACKET_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BRACKET_OUTPUT_DIR / f"{timestamp}_{uuid4().hex[:8]}"
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def merge_one_group(source_paths: list[Path], output_path: Path, params: dict[str, Any]) -> str:
    _require_cv2()
    if not source_paths:
        raise ValueError("Bracket group has no photos.")
    arrays = load_rgb_arrays(source_paths)
    if len(arrays) == 1:
        result_array = arrays[0]
        align_method = "single"
    else:
        aligned, align_method = align_images(arrays, get_alignment(params))
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


def _require_cv2():
    try:
        import cv2 as module
    except ImportError as exc:
        raise RuntimeError("OpenCV is not available in this build, so bracket merging cannot run.") from exc
    globals()["cv2"] = module
    return module


def get_alignment(params: dict[str, Any]) -> str:
    value = str(params.get("alignment") or "simple").lower()
    if value in {"off", "simple", "people", "advanced"}:
        return value
    return "simple"


def merge_aligned_arrays(images: list[np.ndarray], source_paths: list[Path], params: dict[str, Any]) -> np.ndarray:
    algorithm = get_algorithm(params)
    if get_alignment(params) == "people" and algorithm == "fusion":
        return merge_deghosted_fusion(images)
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


def align_images(images: list[np.ndarray], alignment: str) -> tuple[list[np.ndarray], str]:
    if alignment == "off":
        return images, "none"
    if alignment == "people":
        aligned, method = align_images_simple(images)
        return aligned, f"people-{method}"
    if alignment == "advanced":
        return align_images_advanced(images)
    return align_images_simple(images)


def align_images_simple(images: list[np.ndarray]) -> tuple[list[np.ndarray], str]:
    reference_index = len(images) // 2
    reference = images[reference_index]
    aligned = []
    methods = []
    for index, image in enumerate(images):
        if index == reference_index:
            aligned.append(reference)
            methods.append("reference")
            continue
        warped, method = warp_to_reference_simple(image, reference)
        aligned.append(warped)
        methods.append(method)
    if any("homography" in method for method in methods):
        return aligned, "simple-homography"
    if any("affine" in method for method in methods):
        return aligned, "simple-affine"
    return aligned, "simple-translation"


def warp_to_reference_simple(image: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, str]:
    gray_image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gray_reference = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY)
    transform, method = estimate_simple_transform(gray_image, gray_reference)
    if transform is None:
        return warp_translation(image, gray_image, gray_reference), "translation"

    height, width = reference.shape[:2]
    warped = cv2.warpPerspective(
        image,
        transform,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    return warped, method


def estimate_simple_transform(gray_image: np.ndarray, gray_reference: np.ndarray) -> tuple[np.ndarray | None, str]:
    detector = cv2.ORB_create(nfeatures=5000, scaleFactor=1.2, nlevels=8, fastThreshold=8)
    keypoints_image, descriptors_image = detector.detectAndCompute(gray_image, None)
    keypoints_reference, descriptors_reference = detector.detectAndCompute(gray_reference, None)
    if descriptors_image is None or descriptors_reference is None:
        return None, "none"
    if len(keypoints_image) < 12 or len(keypoints_reference) < 12:
        return None, "none"

    good = match_descriptors(descriptors_image, descriptors_reference, cv2.NORM_HAMMING, 0.75)[:500]
    if len(good) < 10:
        return None, "none"

    src = np.float32([keypoints_image[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
    dst = np.float32([keypoints_reference[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if homography is not None and mask is not None and int(mask.sum()) >= 10 and is_reasonable_homography(homography):
        return homography.astype(np.float32), "orb-homography"

    affine, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if affine is not None and mask is not None and int(mask.sum()) >= 8:
        homography = np.eye(3, dtype=np.float32)
        homography[:2, :] = affine
        return homography, "orb-affine"
    return None, "none"


def align_images_advanced(images: list[np.ndarray]) -> tuple[list[np.ndarray], str]:
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
        warped, flow_used = refine_with_dense_flow(warped, reference)
        if flow_used:
            method = f"{method}+flow"
        aligned.append(warped)
        methods.append(method)
    if any("homography" in method for method in methods):
        return aligned, "advanced-homography"
    if any("affine" in method for method in methods):
        return aligned, "advanced-affine"
    if any("flow" in method for method in methods):
        return aligned, "advanced-flow"
    return aligned, "advanced-translation"


def warp_to_reference(image: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, str]:
    gray_image = enhance_gray(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY))
    gray_reference = enhance_gray(cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY))
    transform, method = estimate_feature_transform(gray_image, gray_reference)
    if transform is None:
        return warp_translation(image, gray_image, gray_reference), "translation"

    refined, refined_method = refine_transform_ecc(gray_image, gray_reference, transform)
    if refined is not None:
        transform = refined
        method = f"{method}+ecc-{refined_method}"

    height, width = reference.shape[:2]
    warped = cv2.warpPerspective(
        image,
        transform,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    return warped, method


def refine_with_dense_flow(image: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, bool]:
    try:
        gray_image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        gray_reference = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY)
        moving, fixed, scale = resize_for_flow(gray_image, gray_reference)
        flow = cv2.calcOpticalFlowFarneback(
            moving,
            fixed,
            None,
            pyr_scale=0.5,
            levels=4,
            winsize=31,
            iterations=4,
            poly_n=7,
            poly_sigma=1.5,
            flags=cv2.OPTFLOW_FARNEBACK_GAUSSIAN,
        )
        if scale != 1.0:
            flow = cv2.resize(flow, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_LINEAR)
            flow /= scale
        flow = cv2.GaussianBlur(flow, (0, 0), 3)
        magnitude = np.linalg.norm(flow, axis=2)
        if not np.isfinite(magnitude).all() or float(np.percentile(magnitude, 95)) > 80:
            return image, False
        height, width = reference.shape[:2]
        grid_x, grid_y = np.meshgrid(np.arange(width), np.arange(height))
        map_x = (grid_x - flow[..., 0]).astype(np.float32)
        map_y = (grid_y - flow[..., 1]).astype(np.float32)
        warped = cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return warped, True
    except Exception:
        return image, False


def resize_for_flow(gray_image: np.ndarray, gray_reference: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    height, width = gray_reference.shape[:2]
    longest = max(height, width)
    if longest <= 1400:
        return gray_image, gray_reference, 1.0
    scale = 1400 / longest
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return (
        cv2.resize(gray_image, size, interpolation=cv2.INTER_AREA),
        cv2.resize(gray_reference, size, interpolation=cv2.INTER_AREA),
        scale,
    )


def enhance_gray(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def estimate_feature_transform(gray_image: np.ndarray, gray_reference: np.ndarray) -> tuple[np.ndarray | None, str]:
    for name, detector, norm, ratio in feature_detectors():
        keypoints_image, descriptors_image = detector.detectAndCompute(gray_image, None)
        keypoints_reference, descriptors_reference = detector.detectAndCompute(gray_reference, None)
        if descriptors_image is None or descriptors_reference is None:
            continue
        if len(keypoints_image) < 16 or len(keypoints_reference) < 16:
            continue
        good = match_descriptors(descriptors_image, descriptors_reference, norm, ratio)
        if len(good) < 12:
            continue
        src = np.float32([keypoints_image[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
        dst = np.float32([keypoints_reference[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 3.0, maxIters=8000, confidence=0.999)
        if homography is not None and mask is not None and int(mask.sum()) >= 12 and is_reasonable_homography(homography):
            return homography.astype(np.float32), f"{name}-homography"
        affine, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=5000, confidence=0.999)
        if affine is not None and mask is not None and int(mask.sum()) >= 10:
            homography = np.eye(3, dtype=np.float32)
            homography[:2, :] = affine
            return homography, f"{name}-affine"
    return None, "none"


def feature_detectors():
    detectors = []
    if hasattr(cv2, "SIFT_create"):
        detectors.append(("sift", cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.015, edgeThreshold=12), cv2.NORM_L2, 0.72))
    detectors.append(("akaze", cv2.AKAZE_create(threshold=0.0008), cv2.NORM_HAMMING, 0.78))
    detectors.append(("orb", cv2.ORB_create(nfeatures=7000, scaleFactor=1.2, nlevels=10, fastThreshold=6), cv2.NORM_HAMMING, 0.75))
    return detectors


def match_descriptors(descriptors_image: np.ndarray, descriptors_reference: np.ndarray, norm: int, ratio: float):
    matcher = cv2.BFMatcher(norm)
    matches = matcher.knnMatch(descriptors_image, descriptors_reference, k=2)
    good = []
    for pair in matches:
        if len(pair) != 2:
            continue
        first, second = pair
        if first.distance < ratio * second.distance:
            good.append(first)
    good.sort(key=lambda match: match.distance)
    return good[:700]


def refine_transform_ecc(gray_image: np.ndarray, gray_reference: np.ndarray, transform: np.ndarray) -> tuple[np.ndarray | None, str]:
    try:
        moving, fixed, scale = resize_for_ecc(gray_image, gray_reference)
        scaled_transform = scale_homography(transform, 1 / scale)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5)
        _cc, refined = cv2.findTransformECC(
            fixed,
            moving,
            scaled_transform.astype(np.float32),
            cv2.MOTION_HOMOGRAPHY,
            criteria,
            None,
            5,
        )
        return scale_homography(refined, scale), "homography"
    except Exception:
        return None, "none"


def resize_for_ecc(gray_image: np.ndarray, gray_reference: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    height, width = gray_reference.shape[:2]
    longest = max(height, width)
    if longest <= 1200:
        return normalize_ecc(gray_image), normalize_ecc(gray_reference), 1.0
    scale = 1200 / longest
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return (
        normalize_ecc(cv2.resize(gray_image, size, interpolation=cv2.INTER_AREA)),
        normalize_ecc(cv2.resize(gray_reference, size, interpolation=cv2.INTER_AREA)),
        scale,
    )


def normalize_ecc(gray: np.ndarray) -> np.ndarray:
    return gray.astype(np.float32) / 255.0


def scale_homography(homography: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return homography.astype(np.float32)
    down = np.diag([scale, scale, 1.0]).astype(np.float32)
    up = np.diag([1 / scale, 1 / scale, 1.0]).astype(np.float32)
    return (down @ homography @ up).astype(np.float32)


def is_reasonable_homography(homography: np.ndarray) -> bool:
    if not np.isfinite(homography).all() or abs(float(homography[2, 2])) < 1e-8:
        return False
    normalized = homography / homography[2, 2]
    det = np.linalg.det(normalized[:2, :2])
    if det < 0.25 or det > 4.0:
        return False
    perspective = abs(float(normalized[2, 0])) + abs(float(normalized[2, 1]))
    return perspective < 0.01


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


def merge_deghosted_fusion(images: list[np.ndarray]) -> np.ndarray:
    reference_index = len(images) // 2
    stack = np.stack([image.astype(np.float32) for image in images], axis=0)
    gray = np.mean(stack, axis=3)
    reference_gray = gray[reference_index]

    blurred = np.array([cv2.GaussianBlur(item, (0, 0), 2.0) for item in gray])
    contrast = np.abs(gray - blurred)
    exposure = np.exp(-((gray - 128.0) ** 2) / (2 * 72.0 * 72.0))
    weights = contrast * 0.7 + exposure * 0.3 + 0.04

    diff = np.abs(gray - reference_gray[None, :, :])
    local_diff = np.array([cv2.GaussianBlur(item, (0, 0), 3.0) for item in diff])
    moving = local_diff > 20.0
    penalty = np.where(moving, np.exp(-((local_diff / 28.0) ** 2)), 1.0)
    penalty[reference_index] = 1.0
    weights *= penalty

    motion_area = np.any(moving, axis=0)
    if np.any(motion_area):
        motion_area = cv2.dilate(motion_area.astype(np.uint8), np.ones((7, 7), dtype=np.uint8), iterations=1).astype(bool)
        flat_weights = weights.reshape(weights.shape[0], -1)
        flat_motion = motion_area.reshape(-1)
        flat_weights[:, flat_motion] *= 0.25
        flat_weights[reference_index, flat_motion] = np.maximum(flat_weights[reference_index, flat_motion], 1.0)
        weights = flat_weights.reshape(weights.shape)

    weight_sum = np.sum(weights, axis=0, keepdims=True)
    weights = weights / np.maximum(weight_sum, 1e-6)
    return np.sum(stack * weights[..., None], axis=0)


def merge_mertens_fusion(images: list[np.ndarray]) -> np.ndarray:
    try:
        merge = cv2.createMergeMertens(contrast_weight=1.0, saturation_weight=0.15, exposure_weight=1.2)
        bgr_images = [cv2.cvtColor(image, cv2.COLOR_RGB2BGR).astype(np.uint8) for image in images]
        fused = merge.process(bgr_images)
        fused = np.nan_to_num(fused, nan=0.0, posinf=1.0, neginf=0.0)
        if float(np.max(fused)) <= 1.5:
            fused = fused * 255.0
        rgb = cv2.cvtColor(np.clip(fused, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB).astype(np.float32)
        if float(np.mean(rgb)) >= 3.0:
            return rgb
    except Exception:
        pass
    return exposure_fusion_average(images)


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
    shadows = parse_float(params.get("shadows"), 0.0, 1.0, 0.25)
    highlights = parse_float(params.get("highlights"), 0.0, 1.0, 0.15)
    contrast = parse_float(params.get("contrast"), 0.5, 2.0, 1.0)
    saturation = parse_float(params.get("saturation"), 0.0, 2.0, 1.0)
    sharpen = parse_float(params.get("sharpen"), 0.0, 2.0, 0.2)

    result = image
    if exposure:
        result = ImageEnhance.Brightness(result).enhance(2 ** exposure)
    if shadows or highlights:
        result = adjust_local_tones(result, shadows, highlights)
    if contrast != 1.0:
        result = ImageEnhance.Contrast(result).enhance(contrast)
    if saturation != 1.0:
        result = ImageEnhance.Color(result).enhance(saturation)
    if sharpen:
        result = ImageEnhance.Sharpness(result).enhance(1 + sharpen)
    return result


def adjust_local_tones(image: Image.Image, shadows: float, highlights: float) -> Image.Image:
    array = np.array(image).astype(np.float32)
    luminance = 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]
    normalized = luminance / 255.0

    if shadows:
        shadow_mask = np.clip((0.62 - normalized) / 0.62, 0.0, 1.0) ** 1.6
        lift = 1.0 + shadows * 1.15 * shadow_mask
        array *= lift[:, :, None]

    if highlights:
        highlight_mask = np.clip((normalized - 0.58) / 0.42, 0.0, 1.0) ** 1.4
        compression = 1.0 - highlights * 0.55 * highlight_mask
        array *= compression[:, :, None]
        array += 255.0 * highlights * 0.06 * highlight_mask[:, :, None]

    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), "RGB")


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
