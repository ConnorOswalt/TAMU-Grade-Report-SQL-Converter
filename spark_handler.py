"""
spark_handler.py
PySpark + Delta Lake / Parquet handler for the TAMU Grade Consolidator project.

Compatible with:
- config.py (PROJECT_ROOT, PARQUET_DIR, USE_DELTA_LAKE, SPARK_PARTITION_COLS, etc.)
- converter.py (grd_to_df returns pandas DataFrame)
- sql_handler.py (SQLite layer)
- main.py (the converter-style main loop)

Features:
- Local SparkSession with sensible defaults
- Partitioned Parquet + optional Delta Lake writes
- Easy pandas → Spark conversion
- Logging that matches your existing style
"""

import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import lit

from config import (
    PROJECT_ROOT,
    PARQUET_DIR,
    SPARK_PARTITION_COLS,
    PARQUET_COMPRESSION,
    USE_DELTA_LAKE,
    PARQUET_ROW_GROUP_SIZE,
)


def get_spark_session(
    app_name: str = "TAMU Grade Consolidator",
    memory: str = "4g"
) -> SparkSession:
    """
    Returns a local-mode SparkSession.
    Delta Lake support is enabled if USE_DELTA_LAKE = True in config.py.
    """
    builder = (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", memory)
        .config("spark.executor.memory", memory)
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.parquet.compression.codec", PARQUET_COMPRESSION)
        .config("spark.sql.parquet.enableVectorizedReader", "true")
        .config("spark.ui.enabled", "false")
    )

    if USE_DELTA_LAKE:
        builder = builder \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    logging.info(f"SparkSession started → {app_name} | "
                 f"Delta Lake: {USE_DELTA_LAKE} | "
                 f"Compression: {PARQUET_COMPRESSION}")
    return spark


def pandas_to_spark(df: pd.DataFrame, spark: SparkSession) -> DataFrame:
    """Convert pandas DataFrame to Spark DataFrame (efficient)."""
    if df.empty:
        logging.warning("pandas_to_spark received empty DataFrame")
        return spark.createDataFrame([], schema="struct<>")
    return spark.createDataFrame(df)


def write_partitioned(
    df: pd.DataFrame | DataFrame,
    table_name: str = "grade_distribution",
    mode: str = "append",
    spark: Optional[SparkSession] = None
) -> None:
    """
    Main write function.
    Accepts either pandas or Spark DataFrame.
    Writes to both Parquet and Delta Lake (if enabled).
    """
    if spark is None:
        spark = get_spark_session()

    # Convert pandas → Spark if needed
    if isinstance(df, pd.DataFrame):
        spark_df = pandas_to_spark(df, spark)
    else:
        spark_df = df

    if spark_df.rdd.isEmpty():
        logging.info(f"Empty DataFrame for {table_name} — skipping write")
        return

    target_path = PARQUET_DIR / table_name
    partition_cols = SPARK_PARTITION_COLS

    logging.info(f"Writing {table_name} → {target_path} | mode={mode} | partitions={partition_cols}")

    # Standard Parquet write (always happens)
    spark_df.write \
        .mode(mode) \
        .partitionBy(*partition_cols) \
        .option("compression", PARQUET_COMPRESSION) \
        .option("parquet.block.size", PARQUET_ROW_GROUP_SIZE) \
        .parquet(str(target_path), mode=mode)

    # Delta Lake write (if enabled in config)
    if USE_DELTA_LAKE:
        delta_path = PARQUET_DIR / f"{table_name}_delta"
        spark_df.write \
            .format("delta") \
            .mode(mode) \
            .partitionBy(*partition_cols) \
            .save(str(delta_path))
        logging.info(f"✓ Delta Lake table written → {delta_path}")

    logging.info(f"✅ Successfully wrote {spark_df.count():,} rows to {table_name}")


def stop_spark(spark: SparkSession) -> None:
    """Gracefully stop SparkSession."""
    if spark:
        spark.stop()
        logging.info("SparkSession stopped")


# ────────────────────────────────────────────────────────────────
#  Quick test when running the file directly
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    spark = get_spark_session()

    # Small test DataFrame
    test_pdf = pd.DataFrame({
        "year": [2023, 2023],
        "semester": [3, 3],
        "college": ["EN", "SC"],
        "report_type": ["grd", "grd"],
        "A": [25, 30],
        "B": [15, 10],
        "gpa": [3.45, 3.2]
    })

    write_partitioned(test_pdf, table_name="test_grade_distribution", mode="overwrite", spark=spark)

    stop_spark(spark)
    print("spark_handler.py test completed successfully.")