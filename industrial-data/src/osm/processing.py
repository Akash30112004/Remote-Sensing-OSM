from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from rapidfuzz import fuzz
from shapely.geometry import MultiPoint

from src.osm.tags import normalize_free_text, normalize_industrial_type, normalize_raw_tags
from src.temporal import current_extraction_date

try:
    from shapely import make_valid
except ImportError:  # pragma: no cover
    make_valid = None


def repair_geometry(geometry):
    if geometry is None or geometry.is_empty:
        return None, False
    if geometry.is_valid:
        return geometry, False
    if make_valid is not None:
        repaired = make_valid(geometry)
        if repaired is not None and not repaired.is_empty and repaired.is_valid:
            return repaired, True
    repaired = geometry.buffer(0)
    if repaired is not None and not repaired.is_empty and repaired.is_valid:
        return repaired, True
    return None, False


def _geometry_key(geometry, precision: int) -> tuple:
    rounded = geometry.simplify(0).wkt
    return (geometry.geom_type, round(geometry.centroid.x, precision), round(geometry.centroid.y, precision), rounded)


def _distance_meters(left_geometry, right_geometry) -> float:
    left_frame = gpd.GeoSeries([left_geometry], crs="EPSG:4326")
    right_frame = gpd.GeoSeries([right_geometry], crs="EPSG:4326")
    metric_crs = left_frame.estimate_utm_crs() or CRS.from_epsg(3857)
    left_projected = left_frame.to_crs(metric_crs).iloc[0]
    right_projected = right_frame.to_crs(metric_crs).iloc[0]
    return float(left_projected.distance(right_projected))


def normalize_osm_gdf(
    gdf: gpd.GeoDataFrame,
    *,
    source_name: str,
    district_name: str | None,
    district_source_id: str | None,
    source_url: str,
    exact_duplicate_coordinate_precision: int,
    probable_duplicate_distance_meters: float,
    probable_duplicate_name_similarity: int,
    probable_duplicate_industry_similarity: int,
    storage_crs: str = "EPSG:4326",
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    if gdf.empty:
        return gdf.copy(), {
            "total_rows": 0,
            "valid_rows": 0,
            "repaired_rows": 0,
            "exact_duplicates_removed": 0,
            "probable_duplicate_rows": 0,
            "rejected_rows": 0,
        }

    working = gdf.copy()
    if working.crs is None:
        working = working.set_crs(storage_crs)
    working = working.to_crs(storage_crs)

    rows = []
    rejected_rows = 0
    repaired_rows = 0

    for _, row in working.iterrows():
        geometry, was_repaired = repair_geometry(row.geometry)
        if geometry is None:
            rejected_rows += 1
            continue

        if was_repaired:
            repaired_rows += 1

        raw_tags = row.get("raw_tags") or {}
        industrial_type = row.get("industrial_type") or normalize_industrial_type(raw_tags)
        normalized_name = normalize_free_text(row.get("name"))
        normalized_industrial_type = normalize_free_text(industrial_type)
        operational_status = row.get("operational_status") or raw_tags.get("operational_status") or raw_tags.get("status")
        extraction_date = current_extraction_date()

        rows.append(
            {
                "osm_id": int(row["osm_id"]),
                "osm_type": str(row["osm_type"]),
                "name": row.get("name"),
                "normalized_name": normalized_name,
                "industrial_type": industrial_type,
                "normalized_industrial_type": normalized_industrial_type,
                "geometry": geometry,
                "source": source_name,
                "source_timestamp": pd.to_datetime(row.get("source_timestamp"), utc=True, errors="coerce"),
                "raw_tags": raw_tags,
                "source_url": source_url,
                "district_name": district_name,
                "district_source_id": district_source_id,
                "extraction_date": extraction_date,
                "first_seen": extraction_date,
                "last_seen": extraction_date,
                "operational_status": operational_status,
                "probable_duplicate": False,
                "duplicate_group_id": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )

    normalized = gpd.GeoDataFrame(rows, geometry="geometry", crs=storage_crs)

    normalized["_exact_key"] = normalized.geometry.apply(lambda geom: _geometry_key(geom, exact_duplicate_coordinate_precision))
    exact_duplicate_mask = normalized.duplicated(subset=["osm_type", "osm_id", "_exact_key"], keep="first")
    exact_duplicates_removed = int(exact_duplicate_mask.sum())
    normalized = normalized.loc[~exact_duplicate_mask].copy()
    normalized.drop(columns=["_exact_key"], inplace=True)

    probable_duplicate_rows = _flag_probable_duplicates(
        normalized,
        probable_duplicate_distance_meters=probable_duplicate_distance_meters,
        probable_duplicate_name_similarity=probable_duplicate_name_similarity,
        probable_duplicate_industry_similarity=probable_duplicate_industry_similarity,
    )

    summary = {
        "total_rows": int(len(gdf)),
        "valid_rows": int(len(normalized)),
        "repaired_rows": int(repaired_rows),
        "exact_duplicates_removed": int(exact_duplicates_removed),
        "probable_duplicate_rows": int(probable_duplicate_rows),
        "rejected_rows": int(rejected_rows),
    }
    return normalized, summary


def _flag_probable_duplicates(
    gdf: gpd.GeoDataFrame,
    *,
    probable_duplicate_distance_meters: float,
    probable_duplicate_name_similarity: int,
    probable_duplicate_industry_similarity: int,
) -> int:
    if gdf.empty:
        return 0

    gdf.reset_index(drop=True, inplace=True)

    if len(gdf) == 1:
        gdf.loc[:, "duplicate_group_id"] = [str(uuid4())]
        return 0

    metric_crs = gdf.estimate_utm_crs() or CRS.from_epsg(3857)
    projected = gdf.to_crs(metric_crs)
    assigned_groups: dict[int, str] = {}
    probable_duplicate_count = 0

    for index, row in gdf.iterrows():
        if index in assigned_groups:
            continue

        group_id = str(uuid4())
        assigned_groups[index] = group_id
        cluster_indices = [index]

        for other_index, other_row in gdf.loc[index + 1 :].iterrows():
            if other_index in assigned_groups:
                continue

            if row["normalized_industrial_type"] != other_row["normalized_industrial_type"]:
                continue

            name_score = fuzz.ratio(row["normalized_name"] or "", other_row["normalized_name"] or "")
            industry_score = fuzz.ratio(row["normalized_industrial_type"] or "", other_row["normalized_industrial_type"] or "")
            distance_meters = float(projected.loc[index].geometry.distance(projected.loc[other_index].geometry))

            if (
                distance_meters <= probable_duplicate_distance_meters
                and name_score >= probable_duplicate_name_similarity
                and industry_score >= probable_duplicate_industry_similarity
            ):
                assigned_groups[other_index] = group_id
                cluster_indices.append(other_index)

        if len(cluster_indices) > 1:
            probable_duplicate_count += len(cluster_indices)
            gdf.loc[cluster_indices, "probable_duplicate"] = True
            gdf.loc[cluster_indices, "duplicate_group_id"] = group_id
        else:
            gdf.loc[index, "duplicate_group_id"] = group_id

    return probable_duplicate_count


def overpass_gdf_from_response(payload: dict[str, Any]) -> gpd.GeoDataFrame:
    from src.osm.overpass import overpass_elements_to_geodataframe

    return overpass_elements_to_geodataframe(payload)
