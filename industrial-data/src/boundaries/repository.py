from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def load_district_geometry_from_postgis(
    engine: Engine,
    *,
    table_name: str = "districts",
    district_name: str | None = None,
    district_source_id: str | None = None,
) -> gpd.GeoDataFrame:
    if not district_name and not district_source_id:
        raise ValueError("district_name or district_source_id is required")

    clauses = []
    parameters: dict[str, str] = {}

    if district_name:
        clauses.append("name = :district_name")
        parameters["district_name"] = district_name
    if district_source_id:
        clauses.append("source_id = :district_source_id")
        parameters["district_source_id"] = district_source_id

    query = f"SELECT id, name, administrative_code, geometry, source, source_id, source_date FROM {table_name} WHERE {' AND '.join(clauses)} ORDER BY id LIMIT 1"
    return gpd.read_postgis(text(query), engine, params=parameters, geom_col="geometry")


def load_district_geometry_from_geojson(file_path: str | Path) -> gpd.GeoDataFrame:
    return gpd.read_file(file_path)
