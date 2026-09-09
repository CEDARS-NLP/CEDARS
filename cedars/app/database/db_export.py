'''
db_export.py

Exports a project's RESULTS table as a CSV, streamed in chunks to S3.
'''

from io import BytesIO, StringIO
from math import ceil

import pandas as pd
import polars as pl
from loguru import logger
from sqlalchemy import select

from ..cedars_enums import log_function_call
from .db_session import session_scope
from .project_table_creation import Results

logger.enable(__name__)

# Note: mongo's RESULTS also carried free-text `sentences`/`predicted_notes`
# cache fields; the SQL Results table has no equivalent columns, so this
# export omits them (see db_updates.upsert_patient_records).
_SCHEMA = {
    "patient_id": pl.Utf8,
    "total_notes": pl.Int64,
    "reviewed_notes": pl.Int64,
    "total_sentences": pl.Int64,
    "reviewed_sentences": pl.Int64,
    "event_date": pl.Datetime,
    "event_information": pl.Utf8,
    "first_note_date": pl.Datetime,
    "last_note_date": pl.Datetime,
    "comments": pl.Utf8,
    "reviewer": pl.Utf8,
    "max_score_note_id": pl.Utf8,
    "max_score_note_date": pl.Datetime,
    "max_score": pl.Float64,
    "last_updated_at": pl.Datetime,
}


@log_function_call
def download_annotations(project_engine, s3_client, bucket_name: str, s3_prefix: str,
                         filename: str = "annotations.csv") -> bool:
    '''
    Streams every Results row (in upload order, via index_no) to a CSV file in
    S3, in chunks to bound memory usage on very large projects.

    Args:
        s3_client: a boto3 S3 client.
        bucket_name (str): destination S3 bucket.
        s3_prefix (str): key prefix for the uploaded object.
        filename (str): the CSV file name within `{s3_prefix}/annotated_files/`.

    Returns:
        bool: True on success, False on failure.
    '''
    try:
        logger.info("Starting download task")
        csv_buffer = StringIO()
        pd.DataFrame(columns=list(_SCHEMA.keys())).to_csv(csv_buffer, index=False, header=True)

        logger.info("Retrieving Results from db")
        with session_scope(project_engine) as session:
            rows = session.execute(
                select(*(getattr(Results, col) for col in _SCHEMA)).order_by(Results.index_no)
            ).all()

        logger.info("Creating dataframe for Results")
        df = pl.DataFrame(rows, orient="row", schema=_SCHEMA, infer_schema_length=None)

        for col in ("first_note_date", "last_note_date", "event_date"):
            df = df.with_columns(pl.col(col).dt.date().alias(col))

        logger.info("Uploading results to csv buffer")
        chunk_size = 1000
        for chunk_index in range(0, df.shape[0], chunk_size):
            chunk = df.slice(chunk_index, chunk_size)
            logger.info(
                f"Sending chunk {ceil(chunk_index / chunk_size) + 1}/"
                f"{ceil(df.shape[0] / chunk_size)} to csv buffer"
            )
            csv_buffer.write(chunk.to_pandas().to_csv(header=False, index=False))

        csv_buffer.seek(0)
        data_stream = BytesIO(csv_buffer.getvalue().encode("utf-8"))

        s3_client.upload_fileobj(
            Fileobj=data_stream,
            Bucket=bucket_name,
            Key=f"{s3_prefix}/annotated_files/{filename}",
            ExtraArgs={"ContentType": "text/csv"},
        )
        logger.info(f"File '{filename}' successfully uploaded to bucket '{bucket_name}'")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"Failed to upload annotations to s3: {filename}, error: {exc}")
        return False
