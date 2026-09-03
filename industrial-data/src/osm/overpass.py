from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from shapely.geometry import LineString, Point, Polygon
from urllib3.util.retry import Retry

from src.osm.tags import tag_filters_from_config


@dataclass(frozen=True)
class OverpassArea:
    mode: str
    value: str


def create_retry_session(total_retries: int, backoff_factor: float) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        read=total_retries,
        connect=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _largest_polygon(geometry) -> Polygon | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "Polygon":
        return geometry
    if geometry.geom_type == "MultiPolygon":
        return max(list(geometry.geoms), key=lambda item: item.area, default=None)
    if geometry.geom_type == "GeometryCollection":
        polygons = [part for part in geometry.geoms if part.geom_type == "Polygon"]
        if polygons:
            return max(polygons, key=lambda item: item.area)
    return None


def geometry_to_overpass_poly(geometry) -> str:
    polygon = _largest_polygon(geometry)
    if polygon is None:
        raise ValueError("A polygon geometry is required to build an Overpass poly query")
    coordinates = list(polygon.exterior.coords)
    return " ".join(f"{latitude} {longitude}" for longitude, latitude in coordinates)


def geometry_to_bbox(geometry) -> str:
    minx, miny, maxx, maxy = geometry.bounds
    return f"{miny},{minx},{maxy},{maxx}"


def build_overpass_query(config: dict[str, Any], geometry, *, use_bbox: bool = False, timeout_seconds: int | None = None) -> str:
    filters = tag_filters_from_config(config)
    selector = geometry_to_bbox(geometry) if use_bbox else f'poly:"{geometry_to_overpass_poly(geometry)}"'
    timeout = timeout_seconds or int(config["osm"]["source"].get("request_timeout_seconds", 180))

    clauses = []
    for key, value in filters:
        if value is None:
            clauses.append(f'nwr["{key}"]({selector});')
        elif key == "man_made":
            clauses.append(f'nwr["{key}"~"^({value})$"]({selector});')
        else:
            clauses.append(f'nwr["{key}"="{value}"]({selector});')

    return "\n".join([f"[out:json][timeout:{timeout}];", "(", *clauses, ");", "out tags geom center;"])


def execute_overpass_query(overpass_url: str, query: str, *, request_timeout_seconds: int, retry_attempts: int, retry_backoff_seconds: float) -> dict[str, Any]:
    session = create_retry_session(retry_attempts, retry_backoff_seconds)
    response = session.post(overpass_url, data={"data": query}, timeout=request_timeout_seconds)
    response.raise_for_status()
    return response.json()


def overpass_elements_to_geodataframe(payload: dict[str, Any], crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    rows = []
    geometries = []

    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        geometry = None

        if element["type"] == "node":
            geometry = Point(float(element.get("lon")), float(element.get("lat")))
        else:
            geometry_points = element.get("geometry") or []
            coordinates = [(point["lon"], point["lat"]) for point in geometry_points]
            if len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
                geometry = Polygon(coordinates)
            elif len(coordinates) >= 2:
                geometry = LineString(coordinates)

        if geometry is None:
            continue

        rows.append(
            {
                "osm_id": int(element["id"]),
                "osm_type": element["type"],
                "name": tags.get("name"),
                "industrial_type": None,
                "source_timestamp": element.get("timestamp"),
                "raw_tags": tags,
            }
        )
        geometries.append(geometry)

    return gpd.GeoDataFrame(rows, geometry=geometries, crs=crs)
