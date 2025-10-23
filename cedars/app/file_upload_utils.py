"""
This page contatins utility functions to handle file uploads for CEDARS.
"""
import os
from datetime import datetime
import tempfile
import pickle
import pandas as pd
from flask import (
    flash, g
)
import pyarrow.parquet as pq
from loguru import logger
from .database import minio
from .cedars_enums import log_function_call
from . import db

@log_function_call
def read_gz_csv(filename, *args, **kwargs):
    '''
    Function to read a GZIP compressed csv to a pandas DataFrame.
    '''
    return pd.read_csv(filename, compression='gzip', *args, **kwargs)

def simplify_col_dtypes(col_schema):
    '''
    Convert complex data-types that pandas uses into a simplified format.
    Ex. : int32, int64 -> int

    Args :
        - col_schema (dict) : Dict mapping col_name : data-type

    Returns :
        - col_schema (dict) : Updated dictionary
    '''

    for column in col_schema:
        if col_schema[column][:3] == 'int':
            col_schema[column] = 'int'
        elif col_schema[column][:5] == 'float':
            col_schema[column] = 'float'
        elif col_schema[column] == 'object':
            col_schema[column] = 'text'
        elif col_schema[column][:8] == 'datetime':
            col_schema[column] = 'datetime'

    return col_schema

def inspect_csv(filepath, **kwargs):
    """
    Inspect CSV & GZ files to ensure correct column types and formats.
    """
    try:
        # use chunksize to avoid full load
        iterator = pd.read_csv(filepath, chunksize=5, **kwargs)
        df = next(iterator)
        dtypes = df.dtypes.astype(str).to_dict()
        return simplify_col_dtypes(dtypes)
    except Exception as e:
        return {"error": str(e)}

def inspect_gz(filepath, **kwargs):
    # gzip is handled transparently by pandas, but we can also open explicitly
    return inspect_csv(filepath, compression='gzip', **kwargs)

# ------------------------------
# Excel (inspect only headers from the first sheet)
# ------------------------------
def inspect_excel(filepath, **kwargs):
    try:
        excel_file = pd.ExcelFile(filepath)
        info = {}
        for sheet in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet, nrows=5, **kwargs)
            dtypes = df.dtypes.astype(str).to_dict()
            info[sheet] = simplify_col_dtypes(dtypes)

            # CEDARS only looks for data in the first sheet of the file
            return simplify_col_dtypes(dtypes)
    except Exception as e:
        return {"error": str(e)}

# ------------------------------
# Parquet (fast metadata only)
# ------------------------------
def inspect_parquet(filepath):
    try:
        parquet_file = pq.ParquetFile(filepath)
        schema = parquet_file.schema
        dtypes = {name: str(schema.field(i).type) for i, name in enumerate(schema.names)}
        row_count = parquet_file.metadata.num_rows
        return simplify_col_dtypes(dtypes)
    except Exception as e:
        return {"error": str(e)}

# ------------------------------
# Dispatcher
# ------------------------------
inspectors = {
    'csv': inspect_csv,
    'gz': inspect_gz,
    'xlsx': inspect_excel,
    'parquet': inspect_parquet
}


def check_schema_validity(schema):
    '''
    Raises an error if an invalid schema is passed.

    Args:
        - schema (dict) : Mapping column_name : column_data_type
    Returns:
        - None
    '''

    mandatory_schema_requirements = {'patient_id' : ['int', 'text', 'float'],
                           'text_id' : ['int', 'text', 'float'],
                           'text' : ['text'],
                           'text_date' : ['text']} # TODO : support native datetime

    optional_schema_requirements = {'text_tag_1' : ['int', 'text'],
                                    'text_tag_2' : ['int', 'text'],
                                    'text_tag_3' : ['int', 'text'],
                                    'text_tag_4' : ['int', 'text']}
    
    # Make sure that all mandatory columns are pressent
    for column in mandatory_schema_requirements:
        if column not in schema:
            raise ValueError(f"Column {column} is not present in the uploaded file")
        # Ensure that the column that is present has the appropriate datatype
        elif schema[column] not in mandatory_schema_requirements[column]:
            error_msg = f"Column {column} must have one of the following datatypes: "
            error_msg += mandatory_schema_requirements[column]
            error_msg += f". {column} in uploaded file is of type {schema[column]}."
            raise TypeError(error_msg)

    # Make sure that all mandatory columns are pressent
    for column in optional_schema_requirements:
        if column in schema:
            # Ensure that if an optional column is present,
            # it must has the appropriate datatype
            if schema[column] not in optional_schema_requirements[column]:
                error_msg = f"Column {column} must have one of the following datatypes: "
                error_msg += optional_schema_requirements[column]
                error_msg += f". {column} in uploaded file is of type {schema[column]}."
                raise TypeError(error_msg)


    # Make sure that the data can only have columns from our pre-set schema
    for column in schema:
        if column not in mandatory_schema_requirements and column not in optional_schema_requirements:
            all_allowed_cols = list(mandatory_schema_requirements.keys())
            all_allowed_cols.extend(list(optional_schema_requirements.keys()))
            error_msg = f"Unknown column {column} is present in the uploaded file."
            error_msg += f" Allowed columns in upload file are: {all_allowed_cols}."
            raise ValueError(error_msg)

@log_function_call
def load_pandas_dataframe(filepath, chunk_size=1000):
    """
    Load tabular data from a file into a pandas DataFrame.

    Args:
        filepath (str): The path to the file to load data from.
            Supported file extensions: csv, xlsx, json, parquet, pickle, pkl, xml.

    Returns:
        pd.DataFrame: DataFrame with the data from the file.

    Raises:
        ValueError: If the file extension is not supported.
        FileNotFoundError: If the file does not exist.
    """
    if not filepath:
        raise ValueError("Filepath must be provided.")

    extension = str(filepath).rsplit('.', maxsplit=1)[-1].lower()
    # If the extension is gz, we can assume it is a csv.gz file as this
    # is the only filecheck supported in the allowed_data_file check
    loaders = {
        'csv': pd.read_csv,
        'xlsx': pd.read_excel,
        'parquet': pd.read_parquet,
        'gz' : read_gz_csv,
    }

    if extension not in loaders:
        raise ValueError(f"""
                         Unsupported file extension '{extension}'.
                         Supported extensions are
                         {', '.join(loaders.keys())}.""")

    try:
        logger.info(filepath)
        obj = minio.get_object(g.bucket_name, filepath)
        local_directory = tempfile.gettempdir()
        os.makedirs(local_directory, exist_ok=True)
        local_filename = os.path.join(local_directory, os.path.basename(filepath))
        minio.fget_object(g.bucket_name, filepath, local_filename)
        logger.info(f"File downloaded successfully to {local_filename}")

        # Re-initialise object from minio to load it again
        if extension == 'parquet':
            parquet_file = pq.ParquetFile(local_filename)
            for batch in parquet_file.iter_batches(batch_size=chunk_size):
                yield batch.to_pandas()
        else:
            file_schema = inspectors[extension](local_filename)
            print(f"\n\n\n file_schema : {file_schema} \n\n\n", flush=True)
            check_schema_validity(file_schema)
            chunks = loaders[extension](local_filename, chunksize=chunk_size)
            for chunk in chunks:
                yield chunk

    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File '{filepath}' not found.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to load the file '{filepath}' due to: {str(exc)}") from exc
    except ValueError as exc:
        raise ValueError(f"Failed to upload the file due to schema issues: {exc}")
    except TypeError as exc:
        raise TypeError(f"Failed to upload the file due to datatype mismatch: {exc}")
    finally:
        obj.close()
        obj.release_conn()
        if 'local_filepath' in locals() and os.path.exists(local_filename):
            os.remove(local_filename)
            logger.info(f"Removed temporary file: {local_filename}")

@log_function_call
def prepare_note(note_info):
    logger.debug(f"Formatting note info for note {note_info['text_id']}.")
    date_format = '%Y-%m-%d'
    note_info["text_date"] = datetime.strptime(note_info["text_date"], date_format)
    note_info["reviewed"] = False
    note_info["text_id"] = str(note_info["text_id"]).strip()
    note_info["patient_id"] = str(note_info["patient_id"]).strip()

    tag_cols = [f"text_tag_{i}" for i in range(1, 5)]
    for col in tag_cols:
        if col in note_info:
            note_info[col] = str(note_info[col]).strip()
    return note_info

@log_function_call
def prepare_patients(patient_ids):
    return [str(p_id).strip() for p_id in patient_ids]

@log_function_call
def EMR_to_mongodb(filepath, chunk_size=1000):
    """
    This function is used to open a file and load its contents into the MongoDB database in chunks.

    Args:
        filepath (str): The path to the file to load data from.
        chunk_size (int): Number of rows to process per chunk.

    Returns:
        None
    """
    logger.info("Starting document migration to MongoDB database.")

    total_rows = 0
    total_chunks = 0
    all_patient_ids = []

    try:
        for chunk in load_pandas_dataframe(filepath, chunk_size):
            total_chunks += 1
            rows_in_chunk = len(chunk)
            total_rows += rows_in_chunk

            logger.info(f"Processing chunk {total_chunks} with {rows_in_chunk} rows")

            # Prepare notes
            notes_to_insert = [prepare_note(row.to_dict()) for _, row in chunk.iterrows()]

            # Collect patient IDs
            chunk_patient_ids = list(chunk['patient_id'].unique())
            chunk_patient_ids = prepare_patients(chunk_patient_ids)
            all_patient_ids.extend(chunk_patient_ids)

            # Bulk insert notes
            inserted_count = db.bulk_insert_notes(notes_to_insert)
            logger.info(f"Inserted {inserted_count} notes from chunk {total_chunks}")

        # store NOTES_SUMMARY such as first_note_date, last_note_date, total_notes etc.
        # to use a cache
        notes_summary_count = db.update_notes_summary()
        logger.info(f"Updated {notes_summary_count} notes summary")
        # Bulk upsert patients
        upserted_count_patients, _ = db.bulk_upsert_patients(all_patient_ids)
        logger.info(f"Upserted {upserted_count_patients} patients")
        logger.info(f"Completed document migration to MongoDB database. "
                    f"Total rows processed: {total_rows}, "
                    f"Total chunks processed: {total_chunks}, "
                    f"Total unique patients: {len(all_patient_ids)}")

    except Exception as e:
        logger.error(f"An error occurred during document migration: {str(e)}")
        flash(f"Failed to upload data: {str(e)}")
        raise
