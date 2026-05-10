from __future__ import annotations

import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import piexif
from PIL import Image, ImageOps

from .constants import BRACKET_FEATURE_WORKERS, BRACKET_SCAN_LIMIT, JPG_EXTENSIONS, THUMBNAIL_DIR
from .paths import thumb_url, to_relative

BRACKET_GROUP_SIZES = {3, 5, 7}
BRACKET_MAX_GROUP_SIZE = 7
BRACKET_MAX_TIME_DELTA_SECONDS = 1.0
BRACKET_APERTURE_TOLERANCE = 0.05
BRACKET_FOCAL_LENGTH_TOLERANCE = 0.6
BRACKET_SIMILARITY_MIN = 0.72
BRACKET_AVERAGE_SIMILARITY_MIN = 0.82
BRACKET_EXPOSURE_BIAS_STEP_TOLERANCE = 0.12


class BracketFeature:
    def __init__(
        self,
        path: Path,
        rel: str,
        mtime: int,
        width: int,
        height: int,
        capture_time: datetime | None,
        capture_timestamp: float | None,
        aperture: float | None,
        focal_length: float | None,
        exposure_time: float | None,
        exposure_bias: float | None,
        file_number: int | None,
        pixels: tuple[float, ...],
    ) -> None:
        self.path = path
        self.rel = rel
        self.mtime = mtime
        self.width = width
        self.height = height
        self.capture_time = capture_time
        self.capture_timestamp = capture_timestamp
        self.aperture = aperture
        self.focal_length = focal_length
        self.exposure_time = exposure_time
        self.exposure_bias = exposure_bias
        self.file_number = file_number
        self.pixels = pixels


def detect_exposure_brackets(
    root: Path,
    folder_path: Path,
    thumbnails: Any | None = None,
    scan_limit: int | None = BRACKET_SCAN_LIMIT,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    del thumbnails
    groups: list[list[BracketFeature]] = []
    scanned = 0
    analyzed = 0
    truncated = False
    total = count_photo_files(folder_path, scan_limit)
    processed = 0

    for photo_dir in iter_photo_dirs(folder_path):
        photos = [
            child
            for child in photo_dir.iterdir()
            if child.is_file() and child.suffix.lower() in JPG_EXTENSIONS
        ]
        photos.sort(key=photo_sort_key)
        if scan_limit is not None and scanned + len(photos) > scan_limit:
            photos = photos[: max(0, scan_limit - scanned)]
            truncated = True
        scanned += len(photos)
        features, processed_delta, analyzed_delta = read_bracket_features_parallel(
            root,
            photos,
            total,
            processed,
            len(groups),
            progress_callback,
        )
        processed += processed_delta
        analyzed += analyzed_delta
        matched_groups = find_bracket_groups_in_features(
            features,
            groups_count_base=len(groups),
            progress_callback=progress_callback,
        )
        groups.extend(matched_groups)
        report_progress(
            progress_callback,
            stage="stage2",
            processed=len(features),
            total=len(features),
            groups_count=len(groups),
        )
        if truncated:
            break

    serialized = [serialize_bracket_group(group, group_index + 1) for group_index, group in enumerate(groups)]
    return {
        "groups": serialized,
        "count": len(serialized),
        "scanned": scanned,
        "analyzed": analyzed,
        "queued": 0,
        "truncated": truncated,
        "processed": processed,
        "total": total,
        "progress": 1.0 if total <= 0 else round(processed / total, 6),
        "stage": "done",
        "stage1": {
            "processed": processed,
            "total": total,
            "progress": 1.0 if total <= 0 else round(processed / total, 6),
        },
        "stage2": {
            "processed": analyzed,
            "total": analyzed,
            "progress": 1.0 if analyzed <= 0 else 1.0,
        },
    }


def report_progress(
    progress_callback: Any | None,
    *,
    stage: str,
    processed: int,
    total: int,
    groups_count: int,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(stage, processed, total, groups_count)
    except Exception:
        return


def read_bracket_features_parallel(
    root: Path,
    photos: list[Path],
    total: int,
    processed_base: int,
    groups_count: int,
    progress_callback: Any | None,
) -> tuple[list[BracketFeature], int, int]:
    if not photos:
        return ([], 0, 0)
    indexed_features: list[tuple[int, BracketFeature]] = []
    processed = 0
    analyzed = 0
    worker_count = min(BRACKET_FEATURE_WORKERS, max(1, len(photos)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="bracket-feature") as executor:
        future_map = {
            executor.submit(read_bracket_feature, root, photo): index
            for index, photo in enumerate(photos)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            processed += 1
            feature = None
            try:
                feature = future.result()
            except Exception:
                feature = None
            if feature is not None:
                analyzed += 1
                indexed_features.append((index, feature))
            report_progress(
                progress_callback,
                stage="stage1",
                processed=processed_base + processed,
                total=total,
                groups_count=groups_count,
            )
    indexed_features.sort(key=lambda item: item[0])
    return ([feature for _, feature in indexed_features], processed, analyzed)


def count_photo_files(folder_path: Path, scan_limit: int | None) -> int:
    total = 0
    for photo_dir in iter_photo_dirs(folder_path):
        photos = [
            child
            for child in photo_dir.iterdir()
            if child.is_file() and child.suffix.lower() in JPG_EXTENSIONS
        ]
        if scan_limit is None:
            total += len(photos)
            continue
        remaining = max(0, scan_limit - total)
        total += min(len(photos), remaining)
        if total >= scan_limit:
            break
    return total


def iter_photo_dirs(folder_path: Path) -> list[Path]:
    photo_dirs: list[Path] = []
    for current, dirnames, filenames in os.walk(folder_path):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not dirname.startswith(".") and dirname != THUMBNAIL_DIR
        ]
        current_path = Path(current)
        if any(Path(filename).suffix.lower() in JPG_EXTENSIONS for filename in filenames):
            photo_dirs.append(current_path)
    return photo_dirs


def find_bracket_groups_in_features(
    features: list[BracketFeature],
    groups_count_base: int = 0,
    progress_callback: Any | None = None,
) -> list[list[BracketFeature]]:
    groups: list[list[BracketFeature]] = []
    index = 0
    while index < len(features):
        current = [features[index]]
        index += 1
        while index < len(features) and can_join_group(current, features[index]):
            current.append(features[index])
            index += 1
            if len(current) >= BRACKET_MAX_GROUP_SIZE:
                break
        if is_exposure_bracket_group(current):
            groups.append(current)
        report_progress(
            progress_callback,
            stage="stage2",
            processed=index,
            total=len(features),
            groups_count=groups_count_base + len(groups),
        )
    return groups


def can_join_group(group: list[BracketFeature], candidate: BracketFeature) -> bool:
    if not group:
        return True
    previous = group[-1]
    if not file_numbers_are_consecutive(previous, candidate):
        return False
    if not dimensions_are_close(previous, candidate):
        return False
    if not capture_times_are_close(group[0], candidate):
        return False
    if not same_aperture(group[0], candidate):
        return False
    if not same_focal_length(group[0], candidate):
        return False
    if image_similarity(previous.pixels, candidate.pixels) < BRACKET_SIMILARITY_MIN:
        return False
    return True


def read_bracket_feature(root: Path, photo_path: Path) -> BracketFeature | None:
    try:
        stat = photo_path.stat()
        exif_dict = piexif.load(str(photo_path))
        exif = exif_dict.get("Exif", {})
        zeroth = exif_dict.get("0th", {})
        capture_time = parse_exif_datetime(
            exif.get(piexif.ExifIFD.DateTimeOriginal)
            or exif.get(piexif.ExifIFD.DateTimeDigitized)
            or zeroth.get(piexif.ImageIFD.DateTime)
        )
        aperture = rational_to_float(exif.get(piexif.ExifIFD.FNumber))
        focal_length = rational_to_float(exif.get(piexif.ExifIFD.FocalLength))
        exposure_time = rational_to_float(exif.get(piexif.ExifIFD.ExposureTime))
        exposure_bias = rational_to_float(exif.get(piexif.ExifIFD.ExposureBiasValue))
        with Image.open(photo_path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            gray = image.convert("L")
            gray.thumbnail((48, 48))
            normalized = ImageOps.autocontrast(gray)
            pixels = tuple(value / 255.0 for value in normalized.resize((12, 12)).getdata())
    except Exception:
        return None

    capture_timestamp = capture_time.timestamp() if capture_time is not None else None
    return BracketFeature(
        path=photo_path,
        rel=to_relative(root, photo_path),
        mtime=int(stat.st_mtime),
        width=width,
        height=height,
        capture_time=capture_time,
        capture_timestamp=capture_timestamp,
        aperture=aperture,
        focal_length=focal_length,
        exposure_time=exposure_time,
        exposure_bias=exposure_bias,
        file_number=trailing_number(photo_path.stem),
        pixels=pixels,
    )


def parse_exif_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore").strip("\x00 ").strip()
    else:
        text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def photo_sort_key(path: Path) -> tuple[str, int, str]:
    prefix, number = split_trailing_number(path.stem)
    return (prefix.lower(), number if number is not None else -1, path.name.lower())


def split_trailing_number(value: str) -> tuple[str, int | None]:
    match = re.search(r"(\d+)$", value)
    if not match:
        return (value, None)
    return (value[: match.start()], int(match.group(1)))


def trailing_number(value: str) -> int | None:
    return split_trailing_number(value)[1]


def file_numbers_are_consecutive(left: BracketFeature, right: BracketFeature) -> bool:
    if left.file_number is None or right.file_number is None:
        return False
    return right.file_number - left.file_number == 1


def dimensions_are_close(left: BracketFeature, right: BracketFeature) -> bool:
    if left.width <= 0 or left.height <= 0 or right.width <= 0 or right.height <= 0:
        return False
    return left.width == right.width and left.height == right.height


def capture_times_are_close(first: BracketFeature, candidate: BracketFeature) -> bool:
    if first.capture_timestamp is None or candidate.capture_timestamp is None:
        return False
    return abs(candidate.capture_timestamp - first.capture_timestamp) <= BRACKET_MAX_TIME_DELTA_SECONDS


def same_aperture(first: BracketFeature, candidate: BracketFeature) -> bool:
    if first.aperture is None or candidate.aperture is None:
        return False
    return abs(first.aperture - candidate.aperture) <= BRACKET_APERTURE_TOLERANCE


def same_focal_length(first: BracketFeature, candidate: BracketFeature) -> bool:
    if first.focal_length is None or candidate.focal_length is None:
        return False
    return abs(first.focal_length - candidate.focal_length) <= BRACKET_FOCAL_LENGTH_TOLERANCE


def is_exposure_bracket_group(group: list[BracketFeature]) -> bool:
    if len(group) not in BRACKET_GROUP_SIZES:
        return False
    if not has_even_exposure_bias_steps(group):
        return False
    similarities = [
        image_similarity(group[index].pixels, group[index + 1].pixels)
        for index in range(len(group) - 1)
    ]
    if not similarities:
        return False
    if min(similarities) < BRACKET_SIMILARITY_MIN:
        return False
    if sum(similarities) / len(similarities) < BRACKET_AVERAGE_SIMILARITY_MIN:
        return False
    return has_exposure_variation(group)


def has_exposure_variation(group: list[BracketFeature]) -> bool:
    exposure_values = [feature.exposure_time for feature in group if feature.exposure_time and feature.exposure_time > 0]
    if len(exposure_values) >= 2 and exposure_range_ev(exposure_values) >= 0.5:
        return True
    exposure_biases = [feature.exposure_bias for feature in group if feature.exposure_bias is not None]
    if len(exposure_biases) >= 2 and (max(exposure_biases) - min(exposure_biases)) >= 1.0:
        return True
    return False


def has_even_exposure_bias_steps(group: list[BracketFeature]) -> bool:
    if len(group) < 3:
        return False
    biases = [feature.exposure_bias for feature in group]
    if any(bias is None for bias in biases):
        return False
    ordered = sorted(float(bias) for bias in biases if bias is not None)
    deltas = [ordered[index + 1] - ordered[index] for index in range(len(ordered) - 1)]
    if not deltas:
        return False
    first_delta = deltas[0]
    if first_delta <= 0:
        return False
    for delta in deltas[1:]:
        if abs(delta - first_delta) > BRACKET_EXPOSURE_BIAS_STEP_TOLERANCE:
            return False
    return True


def image_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = 0.0
    left_energy = 0.0
    right_energy = 0.0
    for left_value, right_value in zip(left, right):
        left_centered = left_value - left_mean
        right_centered = right_value - right_mean
        numerator += left_centered * right_centered
        left_energy += left_centered * left_centered
        right_energy += right_centered * right_centered
    denominator = math.sqrt(left_energy * right_energy)
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def serialize_bracket_group(group: list[BracketFeature], index: int) -> dict[str, Any]:
    ordered_group = sorted(group, key=exposure_bias_sort_key)
    similarities = [
        image_similarity(ordered_group[item_index].pixels, ordered_group[item_index + 1].pixels)
        for item_index in range(len(ordered_group) - 1)
    ]
    exposure_values = [feature.exposure_time for feature in ordered_group if feature.exposure_time and feature.exposure_time > 0]
    exposure_biases = [feature.exposure_bias for feature in ordered_group if feature.exposure_bias is not None]
    exposure_range = combined_exposure_range_ev(exposure_values, exposure_biases)
    return {
        "id": index,
        "size": len(ordered_group),
        "averageSimilarity": round(sum(similarities) / len(similarities), 3),
        "exposureRangeEv": round(exposure_range, 2) if exposure_range is not None else None,
        "timeSpanSeconds": round(ordered_group[-1].capture_timestamp - ordered_group[0].capture_timestamp, 3)
        if ordered_group[0].capture_timestamp is not None and ordered_group[-1].capture_timestamp is not None
        else None,
        "photos": [
            {
                "name": feature.path.name,
                "path": feature.rel,
                "mtime": feature.mtime,
                "captureTime": feature.capture_time.strftime("%Y-%m-%d %H:%M:%S") if feature.capture_time else None,
                "aperture": feature.aperture,
                "focalLength": feature.focal_length,
                "exposureTime": feature.exposure_time,
                "exposureBias": feature.exposure_bias,
                "thumbUrl": thumb_url(feature.rel),
            }
            for feature in ordered_group
        ],
    }


def exposure_bias_sort_key(feature: BracketFeature) -> tuple[float, int]:
    if feature.exposure_bias is None:
        return (float("inf"), feature.file_number or 0)
    return (feature.exposure_bias, feature.file_number or 0)


def exposure_range_ev(values: list[float]) -> float:
    minimum = min(value for value in values if value > 0)
    maximum = max(value for value in values if value > 0)
    return abs(math.log2(maximum / minimum))


def combined_exposure_range_ev(exposure_values: list[float], exposure_biases: list[float]) -> float | None:
    ranges: list[float] = []
    if len(exposure_values) >= 2:
        ranges.append(exposure_range_ev(exposure_values))
    if len(exposure_biases) >= 2:
        ranges.append(max(exposure_biases) - min(exposure_biases))
    if not ranges:
        return None
    return max(ranges)


def rational_to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    try:
        numerator, denominator = value
        denominator = float(denominator)
        if denominator == 0:
            return None
        return float(numerator) / denominator
    except (TypeError, ValueError, ZeroDivisionError):
        return None
