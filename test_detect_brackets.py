from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from photo_share.brackets import detect_exposure_brackets


DEFAULT_SOURCE = Path(r"D:\新疆照片\卡1\DCIM\101_PANA")
DEFAULT_OUTPUT = Path(r"D:\codex_prj\photo\test_out")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a folder for exposure bracket groups and copy matches.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Source photo folder to scan.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory for copied groups.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()

    if not source.exists() or not source.is_dir():
        raise SystemExit(f"Source folder not found: {source}")

    output.mkdir(parents=True, exist_ok=True)
    def progress_callback(processed: int, total: int) -> None:
        if total <= 0:
            print("\rprogress: 100.00% (0/0)", end="", flush=True)
            return
        percent = processed * 100 / total
        print(f"\rprogress: {percent:6.2f}% ({processed}/{total})", end="", flush=True)

    result = detect_exposure_brackets(source, source, scan_limit=None, progress_callback=progress_callback)
    print()

    summary_lines = [
        f"source: {source}",
        f"groups: {result['count']}",
        f"scanned: {result['scanned']}",
        f"analyzed: {result['analyzed']}",
        f"truncated: {result['truncated']}",
        "",
    ]

    for group in result["groups"]:
        biases = [photo["exposureBias"] for photo in group["photos"]]
        group_dir = output / f"group_{group['id']:02d}"
        group_dir.mkdir(parents=True, exist_ok=True)
        summary_lines.append(
            f"group {group['id']:02d}: size={group['size']} time_span={group['timeSpanSeconds']} "
            f"similarity={group['averageSimilarity']} exposure_range_ev={group['exposureRangeEv']} biases={biases}"
        )
        for photo in group["photos"]:
            source_path = source / photo["path"]
            target_name = rename_by_exposure_bias(photo["name"], photo["exposureBias"])
            target_path = group_dir / target_name
            shutil.copy2(source_path, target_path)
            summary_lines.append(
                f"  {photo['name']} | capture={photo['captureTime']} | aperture={photo['aperture']} "
                f"| focal={photo['focalLength']} | exposure={photo['exposureTime']} | bias={photo['exposureBias']}"
            )
        summary_lines.append("")

    (output / "summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Detected {result['count']} groups. Output: {output}")
    return 0


def rename_by_exposure_bias(filename: str, exposure_bias: float | None) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    if exposure_bias is None:
        return filename
    rounded = int(round(exposure_bias))
    if abs(exposure_bias - rounded) > 0.15:
        label = format_decimal(exposure_bias).replace("-", "m").replace("+", "p").replace(".", "_")
    elif rounded < 0:
        label = f"m{abs(rounded)}"
    elif rounded > 0:
        label = f"p{rounded}"
    else:
        label = "0"
    stem = re.sub(r"(_[mp]?\d+|_0)$", "", stem)
    return f"{stem}_{label}{suffix}"


def format_decimal(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


if __name__ == "__main__":
    raise SystemExit(main())
