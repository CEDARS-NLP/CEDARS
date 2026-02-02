import pandas as pd
import logging
from pymongo import MongoClient

# Assuming the necessary MongoDB client is initialized
client = MongoClient('mongodb://admin:password@localhost:27018/')
db = client['admin']

logger = logging.getLogger(__name__)


def get_aggregated_data():
    pipeline = [
    ]
    res = list(db.PATIENTS.aggregate(pipeline))
    print(res)
    return res


def download_annotations(filename: str = "annotations.csv"):
    """
    Download annotations from the database and upload as a CSV file to MinIO.

    Args:
        filename (str): The name of the CSV file to be saved.

    Returns:
        bool: True if the upload was successful, False otherwise.
    """
    try:
        data = get_aggregated_data()
        logger.info(f"Retrieved aggregated data for {len(data)} patients")
    except Exception as e:
        logger.error(f"Failed to retrieve aggregated data: {e}")
        return False

    processed_data = []
    for record in data:
        try:
            patient_id = record["_id"]
            notes = record["notes"]
            reviewed_notes = record["reviewed_notes"]
            reviewed_sentences = record["reviewed_sentences"]
            unreviewed_sentences = record["unreviewed_sentences"]
            sentences = reviewed_sentences + unreviewed_sentences
            total_sentences = len(sentences)
            event_date = record.get("event_date", "")
            first_note_date = record.get("first_note_date", "")
            last_note_date = record.get("last_note_date", "")

            processed_data.append([
                patient_id,
                len(notes),
                len(reviewed_notes),
                total_sentences,
                len(reviewed_sentences),
                "\n".join(sentences),
                event_date,
                first_note_date,
                last_note_date
            ])
        except Exception as e:
            logger.error(f"Error processing patient {patient_id}: {e}")
            continue

    if not processed_data:
        logger.warning("No data to write to CSV.")
        return False

    try:
        df = pd.DataFrame(processed_data, columns=[
            "patient_id",
            "total_notes",
            "reviewed_notes",
            "total_sentences",
            "reviewed_sentences",
            "sentences",
            "event_date",
            "first_note_date",
            "last_note_date"
        ])
        print(df)
        df.to_csv(filename, index=False)

    except Exception as e:
        logger.error(f"Failed to upload annotations to s3: {filename}, Error: {e}")
        return False


if __name__ == "__main__":
    download_annotations()
