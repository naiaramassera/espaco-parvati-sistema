import csv
import json
import time
from pathlib import Path

from clinicorp_export_patients import api_get, flatten_value


TMP = Path(r"C:\tmp")
IN_JSON = TMP / "clinicorp_patients.json"
OUT_JSON = TMP / "clinicorp_patient_details.json"
OUT_CSV = TMP / "clinicorp_patient_details.csv"
OUT_JSONL = TMP / "clinicorp_patient_details.jsonl"


def main():
    patients = json.loads(IN_JSON.read_text(encoding="utf-8"))
    done_ids = set()
    details = []

    if OUT_JSONL.exists():
        for line in OUT_JSONL.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            detail = json.loads(line)
            details.append(detail)
            if detail.get("id"):
                done_ids.add(str(detail["id"]))

    for index, patient in enumerate(patients, start=1):
        patient_id = patient.get("id")
        if not patient_id:
            continue
        if str(patient_id) in done_ids:
            continue
        try:
            detail = api_get("/patient/get", {"id": patient_id})
            if isinstance(detail, dict):
                details.append(detail)
                with OUT_JSONL.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(detail, ensure_ascii=False) + "\n")
        except Exception as exc:
            detail = {"id": patient_id, "_export_error": str(exc)}
            details.append(detail)
            with OUT_JSONL.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(detail, ensure_ascii=False) + "\n")
        if index % 25 == 0:
            print(f"processados={index}/{len(patients)}", flush=True)
        time.sleep(0.05)

    OUT_JSON.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = []
    for detail in details:
        for key in detail.keys():
            if key not in fields:
                fields.append(key)

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for detail in details:
            writer.writerow({key: flatten_value(detail.get(key)) for key in fields})

    print(f"detalhes={len(details)}")
    print(str(OUT_JSON))
    print(str(OUT_CSV))


if __name__ == "__main__":
    main()
