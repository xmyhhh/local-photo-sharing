from __future__ import annotations

from typing import Any

from flask import abort
class PhotoFilters:
    def __init__(self, ratings: set[int] | None, date_from: int | None, date_to: int | None) -> None:
        self.ratings = ratings
        self.needs_rating = ratings is not None
        self.date_from = date_from
        self.date_to = date_to

    @classmethod
    def from_request(cls, args: Any) -> "PhotoFilters":
        ratings = parse_rating_filter(args)
        date_from = parse_date_start(args.get("date_from"))
        date_to = parse_date_end(args.get("date_to"))
        return cls(ratings, date_from, date_to)

    def matches_photo(self, photo_rating: int, mtime: int) -> bool:
        if self.ratings is not None and photo_rating not in self.ratings:
            return False
        return self.matches_date(mtime)

    def matches_date(self, mtime: int) -> bool:
        if self.date_from is not None and mtime < self.date_from:
            return False
        if self.date_to is not None and mtime > self.date_to:
            return False
        return True





def parse_optional_int(value: str | None, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        abort(400, f"Expected integer from {minimum} to {maximum}.")
    if parsed < minimum or parsed > maximum:
        abort(400, f"Expected integer from {minimum} to {maximum}.")
    return parsed


def parse_rating_filter(args: Any) -> set[int] | None:
    raw_values = args.getlist("rating") if hasattr(args, "getlist") else [args.get("rating")]
    ratings: set[int] = set()
    for raw in raw_values:
        if raw is None or raw == "":
            continue
        for item in str(raw).split(","):
            if item == "":
                continue
            rating = parse_optional_int(item, 0, 5)
            if rating is not None:
                ratings.add(rating)
    if not ratings or ratings == set(range(0, 6)):
        return None
    return ratings


def parse_date_start(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(value).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    except ValueError:
        abort(400, "date_from must use YYYY-MM-DD format.")


def parse_date_end(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(value).replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
    except ValueError:
        abort(400, "date_to must use YYYY-MM-DD format.")
