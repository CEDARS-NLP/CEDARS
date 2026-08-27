from sqlalchemy import select
from cedars.app.database.project_table_creation import NotesSummary

def get_notes_summary(project_engine, patient_id):
    '''
    Retrieves the summary of notes for a specific patient from the database.
    '''
    with project_engine.connect() as conn:
        stmt = select(
            NotesSummary
            ).where(NotesSummary.patient_id == patient_id)
        result = conn.execute(stmt).fetchone()

    return result