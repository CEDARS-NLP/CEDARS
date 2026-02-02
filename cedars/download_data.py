from pymongo import MongoClient
import csv
from datetime import datetime
from bson import ObjectId

# Connect to MongoDB

client = MongoClient("'mongodb://admin:password@localhost:27018/cedars?authSource=admin'")
db = client['cedars']

def get_patient_notes_and_annotations():
    # Get all patients
    patients = db.PATIENTS.find()

    for patient in patients:
        patient_id = patient['patient_id']
        event_annotation_id = patient.get('event_annotation_id')

        annotation = db.ANNOTATIONS.find_one({"_id": ObjectId(event_annotation_id)}) if event_annotation_id else None
        note = db.NOTES.find_one({'text_id': annotation["note_id"]}) if event_annotation_id else None
        score = db.PINES.find_one({"text_id": note["text_id"]})["predicted_score"] if event_annotation_id else None
        yield {
            'patient_id': patient_id,
            'event_date': patient["event_date"],
            'sentence': annotation["sentence"] if event_annotation_id else None,
            'note_id': note["text_id"] if event_annotation_id else None,
            'text': note["text"] if event_annotation_id else None,
            'reviewed_by': patient["reviewed_by"]
        }

def create_csv():
    filename = 'patient_notes_annotations.csv'

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        field_names = ["patient_id", "event_date", "sentence", "note_id","text", "reviewed_by"]
        writer = csv.DictWriter(csvfile, fieldnames=field_names)

        writer.writeheader()


        for row in get_patient_notes_and_annotations():
            patient_id = row['patient_id']
            writer.writerow(row)

    print(f"CSV file '{filename}' has been created successfully.")

if __name__ == "__main__":
    create_csv()