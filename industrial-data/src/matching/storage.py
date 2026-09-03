from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, Integer, MetaData, Table, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from src.temporal import merge_temporal_snapshots


def _table_name_is_safe(table_name: str) -> bool:
    return table_name.replace("_", "").isalnum()


def ensure_matching_tables(engine: Engine, master_table: str, match_table: str) -> None:
    if not _table_name_is_safe(master_table) or not _table_name_is_safe(match_table):
        raise ValueError("Unsafe matching table name")

    metadata = MetaData()
    master = Table(
        master_table,
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("site_id", Text, nullable=False),
        Column("name", Text),
        Column("normalized_name", Text),
        Column("industry_type", Text),
        Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=False),
        Column("state", Text),
        Column("district", Text),
        Column("address", Text),
        Column("establishment_status", Text),
        Column("establishment_date", Date),
        Column("osm_ids", JSONB, nullable=False),
        Column("government_ids", JSONB, nullable=False),
        Column("matched_source_ids", JSONB, nullable=False),
        Column("source_count", Integer, nullable=False),
        Column("source_confidence", Float, nullable=False),
        Column("match_score", Float, nullable=False),
        Column("match_method", Text, nullable=False),
        Column("match_confidence", Text, nullable=False),
        Column("review_required", Boolean, nullable=False, server_default=text("FALSE")),
        Column("last_verified", Date),
        Column("extraction_date", Date),
        Column("first_seen", Date),
        Column("last_seen", Date),
        Column("operational_status", Text),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )

    matches = Table(
        match_table,
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("candidate_id", Text, nullable=False),
        Column("site_id", Text),
        Column("osm_source_key", Text, nullable=False),
        Column("government_source_key", Text, nullable=False),
        Column("osm_id", BigInteger, nullable=False),
        Column("government_source_id", Text),
        Column("government_table", Text, nullable=False),
        Column("match_score", Float, nullable=False),
        Column("match_confidence", Text, nullable=False),
        Column("match_method", Text, nullable=False),
        Column("review_required", Boolean, nullable=False, server_default=text("FALSE")),
        Column("matched_source_ids", JSONB, nullable=False),
        Column("spatial_distance_meters", Float),
        Column("name_score", Float),
        Column("industry_score", Float),
        Column("address_score", Float),
        Column("state_consistent", Boolean, nullable=False, server_default=text("FALSE")),
        Column("district_consistent", Boolean, nullable=False, server_default=text("FALSE")),
        Column("extraction_date", Date),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )

    metadata.create_all(engine, tables=[master, matches])


def bootstrap_database(engine: Engine, sql_dir: str | Path) -> None:
    sql_path = Path(sql_dir)
    for filename in ("schema.sql", "functions.sql", "indexes.sql"):
        script_path = sql_path / filename
        script_text = script_path.read_text(encoding="utf-8")
        with engine.begin() as connection:
            connection.exec_driver_sql(script_text)


def write_match_results(engine: Engine, match_table: str, matches_gdf: gpd.GeoDataFrame) -> None:
    if matches_gdf.empty:
        return
    ensure_matching_tables(engine, master_table="industrial_sites", match_table=match_table)
    with engine.begin() as connection:
        try:
            existing = pd.read_sql(f'SELECT * FROM "{match_table}"', connection)
        except Exception:
            existing = None

    merged = merge_temporal_snapshots(existing, matches_gdf, key_columns=["osm_source_key", "government_source_key"])

    with engine.begin() as connection:
        connection.execute(text(f'DELETE FROM "{match_table}"'))
    merged.to_sql(match_table, engine, if_exists="append", index=False)


def write_master_sites(engine: Engine, master_table: str, master_gdf: gpd.GeoDataFrame) -> None:
    if master_gdf.empty:
        return
    ensure_matching_tables(engine, master_table=master_table, match_table="industrial_entity_matches")
    with engine.begin() as connection:
        try:
            existing = gpd.read_postgis(f'SELECT * FROM "{master_table}"', connection, geom_col="geometry")
        except Exception:
            existing = None

    merged = merge_temporal_snapshots(existing, master_gdf, key_columns=["site_id"])

    with engine.begin() as connection:
        connection.execute(text(f'DELETE FROM "{master_table}"'))
    merged.to_postgis(master_table, engine, if_exists="append", index=False)
