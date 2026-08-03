"""Download service (ported from the Flask ``ops`` download routes).

Lists/creates/downloads/deletes the annotation CSV exports stored in S3 under
the project's ``annotated_files/`` prefix. Generation runs on the ops queue via
:func:`app.ops_tasks.download_annotations` (which calls ``db.download_annotations``).
"""
from datetime import datetime

from .. import db, ops_tasks, queues
from ..database import get_bucket_name, project_s3_prefix, s3, s3_resource


def _annotated_prefix() -> str:
    return f"{project_s3_prefix()}/annotated_files/"


def list_files() -> list[dict]:
    """List generated annotation files for the current project."""
    response = s3.list_objects_v2(Bucket=get_bucket_name(), Prefix=_annotated_prefix())
    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.endswith("/"):
            continue
        files.append({
            "name": key.rsplit("/", 1)[-1],
            "size": obj["Size"],
            "last_modified": obj["LastModified"].strftime("%Y-%m-%d %H:%M:%S"),
        })
    return files


def get_download_filename(is_full_download: bool = False) -> str:
    """Compose the export filename (ported verbatim)."""
    project_name = db.get_proj_name()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
    if is_full_download:
        return f"annotations_full_{project_name}_{timestamp}.csv"
    return f"annotations_compact_{project_name}_{timestamp}.csv"


def create_download(project_id: str, is_full: bool = False) -> str:
    """Enqueue generation of an annotations export; returns the job id."""
    filename = get_download_filename(is_full)
    job = queues.ops_queue.enqueue(ops_tasks.download_annotations,
                                   project_id, filename, is_full)
    return job.get_id()


def check_job(job_id: str) -> dict:
    """Report the status of a generation job."""
    job = queues.ops_queue.fetch_job(job_id)
    if job is None:
        return {"status": "not_found"}
    if job.is_finished:
        return {"status": "finished"}
    if job.is_failed:
        return {"status": "failed"}
    return {"status": "in_progress"}


def get_file_bytes(filename: str) -> bytes:
    """Return the raw bytes of a generated CSV."""
    key = f"{_annotated_prefix()}{filename}"
    response = s3.get_object(Bucket=get_bucket_name(), Key=key)
    return response["Body"].read()


def delete_file(filename: str) -> None:
    """Delete all versions of a generated CSV from S3."""
    key = f"{_annotated_prefix()}{filename}"
    bucket = s3_resource.Bucket(get_bucket_name())
    bucket.object_versions.filter(Prefix=key).delete()
