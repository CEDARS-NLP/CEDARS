"""Data-ingestion service.

Ports the framework-agnostic helpers from the original Flask ``ops`` blueprint
(``allowed_data_file``, ``load_pandas_dataframe``, ``prepare_note``,
``prepare_patients``, ``EMR_to_mongodb``) with the Flask bits removed (``flash``
-> exceptions/logging, ``g.bucket_name`` -> :func:`get_bucket_name`). Object keys
are prefixed per project for isolation.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pandas as pd
import pyarrow.parquet as pq
from loguru import logger
from werkzeug.utils import secure_filename

from ..database import (get_bucket_name, get_current_project_engine,
                        project_s3_prefix, s3)
from ..database.db_inserts import bulk_insert_notes, bulk_upsert_patients
from ..database.db_updates import update_notes_summary

ALLOWED_EXTENSIONS = {"csv", "xlsx", "json", "parquet", "pickle", "pkl", "xml", "csv.gz"}


def allowed_data_file(filename: str) -> bool:
    """True if ``filename`` has a supported tabular-data extension."""
    return any(filename.endswith("." + ext) for ext in ALLOWED_EXTENSIONS)


def _uploaded_prefix() -> str:
    return f"{project_s3_prefix()}/uploaded_files/"


def ingest_chunk_sizes() -> tuple[int, int]:
    """Return (insert_notes, upsert_patients) chunk sizes from env (with defaults)."""
    insert = int(os.getenv("CHUNK_SIZE_INSERT_NOTES") or 1000)
    upsert = int(os.getenv("CHUNK_SIZE_UPSERT_PATIENTS") or 2000)
    return insert, upsert


def list_uploaded_files() -> list[dict]:
    """List previously uploaded source files for the current project."""
    prefix = _uploaded_prefix()
    response = s3.list_objects_v2(Bucket=get_bucket_name(), Prefix=prefix)
    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.endswith("/"):
            continue
        files.append({
            "key": key,
            "name": key.rsplit("/", 1)[-1],
            "size": obj["Size"],
        })
    return files


def upload_source_file(fileobj, filename: str, content_type: str | None = None) -> str:
    """Upload a source file to the project's ``uploaded_files/`` prefix; return its key."""
    key = f"{_uploaded_prefix()}{secure_filename(filename)}"
    extra_args = {"ContentType": content_type} if content_type else {}
    s3.upload_fileobj(Fileobj=fileobj, Bucket=get_bucket_name(), Key=key,
                      ExtraArgs=extra_args)
    logger.info(f"File '{filename}' uploaded to '{key}'.")
    return key


def _read_gz_csv(filename, *args, **kwargs):
    return pd.read_csv(filename, compression="gzip", *args, **kwargs)


def load_pandas_dataframe(filepath, chunk_size=1000):
    """Yield chunks of a tabular file downloaded from S3 (ported verbatim)."""
    if not filepath:
        raise ValueError("Filepath must be provided.")

    extension = str(filepath).rsplit(".", maxsplit=1)[-1].lower()
    loaders = {
        "csv": pd.read_csv,
        "xlsx": pd.read_excel,
        "json": pd.read_json,
        "parquet": pd.read_parquet,
        "pickle": pd.read_pickle,
        "pkl": pd.read_pickle,
        "xml": pd.read_xml,
        "gz": _read_gz_csv,
    }
    if extension not in loaders:
        raise ValueError(
            f"Unsupported file extension '{extension}'. "
            f"Supported extensions are {', '.join(loaders.keys())}.")

    local_filename = None
    try:
        logger.info(filepath)
        local_directory = tempfile.gettempdir()
        os.makedirs(local_directory, exist_ok=True)
        local_filename = os.path.join(local_directory, os.path.basename(filepath))

        s3.download_file(get_bucket_name(), filepath, local_filename)
        logger.info(f"File downloaded successfully to {local_filename}")

        if extension == "parquet":
            parquet_file = pq.ParquetFile(local_filename)
            for batch in parquet_file.iter_batches(batch_size=chunk_size):
                yield batch.to_pandas()
        else:
            chunks = loaders[extension](local_filename, chunksize=chunk_size)
            for chunk in chunks:
                yield chunk
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File '{filepath}' not found.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to load the file '{filepath}' due to: {str(exc)}") from exc
    finally:
        if local_filename and os.path.exists(local_filename):
            os.remove(local_filename)
            logger.info(f"Removed temporary file: {local_filename}")


def prepare_note(note_info):
    """Normalize a note row for insertion (ported from ``ops.prepare_note``)."""
    logger.debug(f"Formatting note info for note {note_info['text_id']}.")
    date_format = "%Y-%m-%d"
    text_date = note_info["text_date"]
    if isinstance(text_date, str):
        note_info["text_date"] = datetime.strptime(text_date, date_format)
    else:
        # Source already carries a datetime-like value (parquet/pickle/etc.).
        note_info["text_date"] = pd.to_datetime(text_date).to_pydatetime()
    note_info["reviewed"] = False
    note_info["text_id"] = str(note_info["text_id"]).strip()
    note_info["patient_id"] = str(note_info["patient_id"]).strip()
    return note_info


def prepare_patients(patient_ids):
    """Normalize patient ids (ported verbatim)."""
    return [str(p_id).strip() for p_id in patient_ids]


def emr_to_sql(filepath, chunk_size_insert_notes=1000, chunk_size_upsert_patients=2000):
    """Load a tabular file into the project's SQL database in chunks (ported from
    ``ops.EMR_to_mongodb``).

    Respects foreign key constraints by inserting parent records (Patients) before
    child records (Notes, NotesSummary). This requires two passes over the input file:
    - Pass 1: Collect all patient IDs from the file
    - Pass 2: Insert notes once all patients exist

    Returns a summary dict instead of flashing messages.
    """
    logger.info("Starting document migration to the project's database.")

    # PHASE 1: Collect all unique patient IDs from the input file (first pass, minimal memory)
    logger.info("Collecting all patient IDs from input file...")
    all_patient_ids: list = []
    for chunk in load_pandas_dataframe(filepath, chunk_size_insert_notes):
        chunk_patient_ids = prepare_patients(list(chunk["patient_id"].unique()))
        all_patient_ids.extend(chunk_patient_ids)
    
    unique_patient_ids = list(dict.fromkeys(all_patient_ids))  # Preserve insertion order, remove duplicates
    logger.info(f"Collected {len(unique_patient_ids)} unique patient IDs")

    # PHASE 2: Create all Patients records (parent table, must happen BEFORE notes due to FK constraints)
    logger.info("Creating Patients records...")
    upserted_count_patients, _ = bulk_upsert_patients(
        get_current_project_engine(), unique_patient_ids, chunk_size_upsert_patients)
    logger.info(f"Upserted {upserted_count_patients} patients")

    # PHASE 3: Insert Notes in chunks (child table, now all parent FKs are satisfied)
    logger.info("Inserting Notes records...")
    total_rows = 0
    total_chunks = 0
    for chunk in load_pandas_dataframe(filepath, chunk_size_insert_notes):
        total_chunks += 1
        rows_in_chunk = len(chunk)
        total_rows += rows_in_chunk
        logger.info(f"Processing chunk {total_chunks} with {rows_in_chunk} rows")

        notes_to_insert = [prepare_note(row.to_dict()) for _, row in chunk.iterrows()]
        inserted_count = bulk_insert_notes(get_current_project_engine(), notes_to_insert)
        logger.info(f"Inserted {inserted_count} notes from chunk {total_chunks}")

    # PHASE 4: Update NotesSummary (child table, references Patients.patient_id)
    logger.info("Updating NotesSummary...")
    notes_summary_count = update_notes_summary(get_current_project_engine())
    logger.info(f"Updated {notes_summary_count} notes summary")

    logger.info(
        f"Completed document migration. Total rows: {total_rows}, "
        f"chunks: {total_chunks}, unique patients: {len(unique_patient_ids)}")

    return {
        "total_rows": total_rows,
        "total_chunks": total_chunks,
        "total_patients": len(unique_patient_ids),
        "notes_inserted": total_rows,
    }
