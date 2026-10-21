import csv
import argparse
import random
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "frontend" / "public" / "sample-data" / "synthetic_major_bleeding_patient.csv"
SEED = 20261671
MIN_NOTE_LENGTH = 3000
QUERY = (
    "gib OR ?gib OR bleed* OR bled OR bloody OR brbpr OR epistax* OR "
    "exsanguinat* OR haemorrhag* OR hemarthros* OR hematemesis"
)

PATIENTS = [
    {"id": "SYNTH-P002", "label": "recent_major", "site": "gastrointestinal", "event_date": "2026-10-02", "criterion": "transfusion"},
    {"id": "SYNTH-P003", "label": "recent_major", "site": "intracranial", "event_date": "2026-09-29", "criterion": "critical_site"},
    {"id": "SYNTH-P004", "label": "recent_major", "site": "retroperitoneal", "event_date": "2026-10-01", "criterion": "extravasation"},
    {"id": "SYNTH-P005", "label": "non_major", "site": "epistaxis", "event_date": "2026-10-03", "criterion": "minor"},
    {"id": "SYNTH-P006", "label": "non_major", "site": "superficial", "event_date": "2026-10-04", "criterion": "minor"},
    {"id": "SYNTH-P007", "label": "remote_major", "site": "gastrointestinal", "event_date": "2018-04-16", "criterion": "transfusion"},
    {"id": "SYNTH-P008", "label": "remote_major", "site": "intracranial", "event_date": "2019-02-11", "criterion": "critical_site"},
    {"id": "SYNTH-P009", "label": "remote_major", "site": "retroperitoneal", "event_date": "2017-08-23", "criterion": "transfusion"},
    {"id": "SYNTH-P010", "label": "remote_major", "site": "gastrointestinal", "event_date": "2016-11-07", "criterion": "transfusion"},
]

ROUTINE_NOTES = [
    (
        "Cardiology follow-up: The patient reports a steady walking routine and no recent change in stamina. "
        "Heart rate is within the expected range on the current regimen.",
        "He continues to prepare meals at home and records his morning readings several times each week. "
        "The clinician reviewed the current plan and arranged routine follow-up.",
    ),
    (
        "Primary care visit: The patient is sleeping well and has maintained his usual appetite. "
        "He reports no new limitation with household activities.",
        "Examination is consistent with prior visits. The patient will continue the same daily routine and "
        "bring his home log to the next appointment.",
    ),
    (
        "Medication review: The patient confirms taking each prescribed medicine on schedule and reports "
        "no recent changes to supplements or over-the-counter products.",
        "The list was reconciled together. He understands the dosing plan and will call the clinic with "
        "questions before making changes.",
    ),
    (
        "Laboratory review: Kidney function and platelet count are within the patient's usual range. "
        "Hemoglobin is stable compared with the previous assessment.",
        "The results were discussed by telephone. Repeat testing is planned at the next scheduled visit, "
        "with no adjustment to the current care plan.",
    ),
    (
        "Nutrition consultation: The patient has reduced packaged foods and is eating regular meals. "
        "Weight is unchanged from the previous month.",
        "He plans to continue walking and add more vegetables to meals. The dietitian encouraged gradual "
        "changes that fit his usual schedule.",
    ),
    (
        "Imaging review: The recent study shows stable chronic findings and no new acute abnormality. "
        "The patient is comfortable and has no new abdominal or chest discomfort.",
        "The ordering clinician reviewed the result and recommended routine outpatient monitoring. "
        "The patient agrees with the follow-up plan.",
    ),
]

NEUTRAL_FILLER = [
    "Administrative summary: The visit information was organized into the appropriate sections of the record. "
    "The patient reviewed the appointment details and confirmed that the preferred contact information is current.",
    "Record coordination: The schedule and contact preferences were reviewed during this visit. "
    "A written copy of the appointment information was provided for the patient's personal records.",
    "Visit documentation: The clinic hours, scheduling process, and preferred method for routine correspondence "
    "were reviewed. The patient confirmed understanding of these administrative details.",
    "Care coordination note: The record was checked for completeness, and the appropriate visit sections were "
    "organized. The patient received the updated appointment summary before leaving.",
    "Administrative follow-up: The patient was given information about the next scheduled visit and how to contact "
    "the office for scheduling questions. Contact details were confirmed as current.",
    "Documentation note: The visit summary was reviewed for accuracy and filed in the patient's record. "
    "The patient was offered a printed copy of the scheduling information.",
    "Office coordination: The appointment calendar and correspondence preferences were reviewed. "
    "The patient confirmed that the listed contact method remains convenient.",
    "Record management: The visit paperwork was organized and the appointment summary was made available "
    "to the patient. The usual office contact details were included.",
    "Administrative review: The patient reviewed the written visit information and confirmed receipt. "
    "The clinic's regular scheduling and correspondence process was discussed.",
    "Visit summary: The appointment details were recorded in the appropriate section. "
    "The patient received a copy of the schedule and the office contact information.",
]


def note_count_allocation() -> dict[str, int]:
    rng = random.Random(SEED)
    allocation = {"SYNTH-P001": rng.randint(10, 20)}
    for patient in PATIENTS:
        allocation[patient["id"]] = rng.randint(10, 20)
    return allocation


def affirmative_target(note_count: int) -> int:
    return (note_count + 2) // 4


def pad_note_text(text: str, minimum: int = MIN_NOTE_LENGTH) -> str:
    if len(text) >= minimum:
        return text

    padded = text
    filler_index = 0
    while len(padded) < minimum:
        paragraph = NEUTRAL_FILLER[filler_index % len(NEUTRAL_FILLER)]
        padded = f"{padded.rstrip()}\n\n{paragraph}"
        filler_index += 1
    return padded


def routine_text(index: int, patient_id: str) -> str:
    first, second = ROUTINE_NOTES[index % len(ROUTINE_NOTES)]
    return f"{first}\n\n{second} Patient record {patient_id[-3:]} was reviewed and the next visit remains on schedule."


def event_text(patient: dict[str, str], occurrence: int) -> str:
    event_date = date.fromisoformat(patient["event_date"])
    if patient["label"] == "recent_major":
        if patient["criterion"] == "transfusion":
            evidence = (
                "Hemoglobin fell from 12.1 g/dL to 9.4 g/dL, a 2.7 g/dL decrease, and two units of packed red cells were transfused."
            )
        elif patient["criterion"] == "critical_site":
            evidence = (
                "Head imaging showed an acute intracranial hemorrhage with new confusion and severe headache, making this symptomatic bleeding in a critical organ."
            )
        else:
            evidence = (
                "Contrast imaging showed active extravasation into the retroperitoneal space, and the patient required urgent monitoring and transfusion."
            )
        summaries = [
            f"Emergency assessment: On {event_date.isoformat()}, the patient had a spontaneous {patient['site']} bleeding event. It was not caused by surgery or another invasive procedure. {evidence} This is explicitly classified as a major bleeding event because it meets the stated major-bleeding criterion.",
            f"Inpatient progress note: The same spontaneous {patient['site']} bleeding event from {event_date.isoformat()} remains the reason for admission. No surgery or invasive procedure preceded it. The documented findings meet criteria for a major bleeding event, and the team is following the established monitoring plan.",
            f"Discharge planning: The patient is recovering after the spontaneous {patient['site']} bleeding event on {event_date.isoformat()}. This event was unrelated to surgery or any invasive procedure and is documented as a major bleeding event based on the qualifying clinical evidence. Follow-up is arranged with the treating service.",
            f"Specialty follow-up: Records confirm the spontaneous {patient['site']} bleeding event on {event_date.isoformat()}, with no preceding surgery or invasive procedure. The episode is classified as a major bleeding event under the documented criterion. The patient is following the post-discharge plan.",
            f"Care coordination: The hospital record describes the spontaneous {patient['site']} bleeding event of {event_date.isoformat()} as a major bleeding event. It was not related to surgery or another invasive procedure. The patient and care team reviewed the follow-up schedule and medication plan.",
        ]
        first = summaries[(occurrence - 1) % len(summaries)]
        second = (
            "Current examination and vital signs were reviewed with the patient. The care team explained the next steps, "
            "and the patient was able to repeat the follow-up plan."
        )
        return f"{first}\n\n{second}"

    if patient["label"] == "non_major":
        if patient["site"] == "epistaxis":
            finding = "The patient had a brief episode of epistaxis after the room air became dry. It stopped on its own within several minutes."
        else:
            finding = "A shallow skin cut produced a small amount of bleeding while the patient was preparing food. It stopped with brief direct pressure."
        details = [
            f"Urgent care note: {finding} The event was minor and did not involve a critical site. Hemoglobin remained stable, there was no low blood pressure, and no transfusion or urgent procedure was needed.",
            f"Follow-up note: The earlier minor {patient['site']} bleeding episode has not recurred. It did not meet any major-event criterion, and the patient remained stable without a significant hemoglobin decrease or transfusion.",
            f"Telephone review: The patient describes the same self-limited {patient['site']} bleeding finding. It required no intervention beyond simple home care and caused no change in activity or vital signs.",
            f"Primary care note: The minor {patient['site']} bleeding episode resolved promptly. There was no critical-organ involvement, hemodynamic instability, qualifying hemoglobin fall, or need for transfusion.",
            f"Nursing follow-up: The patient has had no further issue after the brief {patient['site']} bleeding episode. The assessment remains non-major, with stable laboratory results and no need for additional treatment.",
        ]
        second = (
            "The clinician reviewed return precautions and documented that the patient can continue normal activity. "
            "Routine follow-up remains appropriate."
        )
        return f"{details[(occurrence - 1) % len(details)]}\n\n{second}"

    remote_years = (date(2026, 10, 20) - event_date).days // 365
    details = [
        f"History review: The record documents a spontaneous {patient['site']} bleeding event on {event_date.isoformat()}, approximately {remote_years} years ago. At that time it was classified as a major bleeding event based on the recorded hospital evidence. There has been no qualifying major event in the past 30 days.",
        f"Specialty history: The patient's major {patient['site']} bleeding event occurred on {event_date.isoformat()}, more than five years before this note. The old event was unrelated to a recent procedure and has not recurred in the current 30-day period.",
        f"Chart reconciliation: Prior records describe a major {patient['site']} bleeding event in {event_date.year}. It is a remote historical event, and the current review identifies no recent qualifying major event.",
        f"Anticoagulation review: The only major {patient['site']} bleeding event in the available history occurred on {event_date.isoformat()}, more than five years ago. The patient has had no qualifying major event during the past 30 days.",
        f"Longitudinal care note: The documented major {patient['site']} bleeding event is dated {event_date.isoformat()}, well over five years before the current assessment. It remains historical and there is no recent qualifying major event.",
    ]
    first = details[(occurrence - 1) % len(details)]
    second = (
        "Today the patient is at his usual activity level and has no new symptoms. The clinician reviewed the current "
        "medication plan and arranged routine follow-up."
    )
    return f"{first}\n\n{second}"


def generated_patient_rows(patient: dict[str, str], note_count: int) -> list[dict[str, str]]:
    match_count = affirmative_target(note_count)
    nonmatching_count = note_count - match_count
    rows = []
    for index in range(note_count):
        is_match = index >= nonmatching_count
        if is_match:
            occurrence = index - nonmatching_count + 1
            text = event_text(patient, occurrence)
            if patient["label"] == "recent_major":
                note_date = date(2026, 10, 2) + timedelta(days=occurrence)
            else:
                note_date = date(2026, 10, 1) + timedelta(days=4 * (occurrence - 1))
        else:
            first_date = date(2026, 7, 15)
            note_date = first_date + timedelta(days=(49 * index // max(nonmatching_count - 1, 1)))
            text = routine_text(index, patient["id"])
        rows.append({
            "patient_id": patient["id"],
            "text_id": f"{patient['id']}-NOTE-{index + 1:03d}",
            "text": text,
            "text_date": note_date.isoformat(),
        })
    return rows


def write_rows(rows: list[dict[str, str]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=["patient_id", "text_id", "text", "text_date"])
        writer.writeheader()
        writer.writerows(rows)


def pad_existing_csv() -> int:
    with CSV_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    padded_count = 0
    for row in rows:
        original_text = row["text"]
        row["text"] = pad_note_text(original_text)
        if row["text"] != original_text:
            if not row["text"].startswith(original_text):
                raise ValueError(f"Padding changed existing note text: {row['text_id']}")
            padded_count += 1
    write_rows(rows)
    return padded_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pad-existing",
        action="store_true",
        help="pad every current CSV row without regenerating patient notes",
    )
    args = parser.parse_args()
    if args.pad_existing:
        padded_count = pad_existing_csv()
        print(f"Padded {padded_count} notes to at least {MIN_NOTE_LENGTH} characters.")
        return

    with CSV_PATH.open(newline="", encoding="utf-8") as source:
        original_rows = list(csv.DictReader(source))
    patient_one = [row for row in original_rows if row["patient_id"] == "SYNTH-P001"]
    if len(patient_one) != 12:
        raise ValueError("Expected the existing 12 notes for SYNTH-P001")

    allocation = note_count_allocation()
    rows = patient_one[:]
    for patient in PATIENTS:
        rows.extend(generated_patient_rows(patient, allocation[patient["id"]]))
    rows = [{**row, "text": pad_note_text(row["text"])} for row in rows]
    write_rows(rows)

    print(f"Generated {len(rows)} notes across {len(allocation)} patients with seed {SEED}.")
    print("Notes per patient:", dict(allocation))
    print("Affirmative match targets:", {key: affirmative_target(value) for key, value in allocation.items()})


if __name__ == "__main__":
    main()