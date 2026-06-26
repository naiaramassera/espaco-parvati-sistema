import csv
import json
import sys
import time
from pathlib import Path
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.clinicorp_export_patients import find_token, flatten_value


TMP = Path(r"C:\tmp")
OUT = TMP / "clinicorp_export_all"
PATIENTS_JSON = TMP / "clinicorp_patients.json"
TOKEN = None


def token():
    global TOKEN
    if TOKEN is None:
        TOKEN = find_token()
    return TOKEN


def api_request(method, path, params=None, data=None, base="api"):
    query = f"?{parse.urlencode(params or {}, doseq=True)}" if params else ""
    body = None
    headers = {
        "Authorization": f"Bearer {token()}",
        "Accept": "application/json",
        "Origin": "https://sistema.clinicorp.com",
        "Referer": "https://sistema.clinicorp.com/",
    }
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(
        f"https://api.clinicorp.com/{base}{path}{query}",
        data=body,
        method=method,
        headers=headers,
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"_error": f"HTTP {exc.code}", "_body": raw[:1000], "_path": path, "_params": params}
    except Exception as exc:
        return {"_error": str(exc), "_path": path, "_params": params}


def rows_from_data(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "List", "items", "data", "Plans", "DefaultPlansList"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def save_dataset(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / f"{name}.json"
    csv_path = OUT / f"{name}.csv"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = rows_from_data(data)
    if rows and all(isinstance(row, dict) for row in rows):
        fields = []
        for row in rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: flatten_value(row.get(key)) for key in fields})
        return len(rows), str(json_path), str(csv_path)

    return len(rows), str(json_path), ""


def load_patients():
    if not PATIENTS_JSON.exists():
        data = api_request("GET", "/patient/list_all", {"removeDeleted": "false"})
        save_dataset("patients", data)
        patients = rows_from_data(data)
    else:
        patients = json.loads(PATIENTS_JSON.read_text(encoding="utf-8"))
    return [p for p in patients if isinstance(p, dict) and p.get("id")]


def save_patient_dataset(name, patients, fetcher, pause=0.03):
    OUT.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUT / f"{name}.jsonl"
    final_json = OUT / f"{name}.json"
    final_csv = OUT / f"{name}.csv"

    done = set()
    records = []
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            records.append(item)
            if item.get("patient_id"):
                done.add(str(item["patient_id"]))

    for index, patient in enumerate(patients, start=1):
        patient_id = str(patient["id"])
        if patient_id in done:
            continue
        data = fetcher(patient_id)
        item = {"patient_id": patient_id, "patient_name": patient.get("Name"), "data": data}
        records.append(item)
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        if index % 50 == 0:
            print(f"{name}: {index}/{len(patients)}", flush=True)
        time.sleep(pause)

    final_json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    flat_rows = []
    for item in records:
        data = item.get("data")
        rows = rows_from_data(data)
        if rows:
            for row in rows:
                if isinstance(row, dict):
                    flat_rows.append({
                        "patient_id": item["patient_id"],
                        "patient_name": item.get("patient_name"),
                        **row,
                    })
        elif isinstance(data, dict) and not data.get("_error"):
            flat_rows.append({
                "patient_id": item["patient_id"],
                "patient_name": item.get("patient_name"),
                **data,
            })

    if flat_rows:
        fields = []
        for row in flat_rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
        with final_csv.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in flat_rows:
                writer.writerow({key: flatten_value(row.get(key)) for key in fields})

    return len(records), str(final_json), str(final_csv if flat_rows else "")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    patients = load_patients()
    summary = {}

    general_gets = {
        "patients": ("/patient/list_all", {"removeDeleted": "false"}),
        "professionals": ("/professional/list_professionals", {}),
        "dentists_all": ("/dentist/list_all", {}),
        "dentists_active": ("/dentist/list_active", {}),
        "prices": ("/price/get_all_prices", {"checkPriceTableIsActive": "X"}),
        "appointment_categories": ("/appointment/list_categories", {"__caller": "export"}),
        "statuses": ("/status/list_status", {}),
        "treatment_plans": ("/financial/plan_control/get_plans", {}),
        "business": ("/business/get", {}),
        "business_clinics_active": ("/business/clinics_active", {}),
        "tags": ("/core/tag/get-by-filter", {}),
    }
    for name, (path, params) in general_gets.items():
        data = api_request("GET", path, params)
        summary[name] = save_dataset(name, data)

    patient_gets = {
        "patient_details": lambda pid: api_request("GET", "/patient/get", {"id": pid}),
        "patient_appointments": lambda pid: api_request("GET", "/patient/appointment_list", {"id": pid}),
        "patient_receipts": lambda pid: api_request("GET", "/payment/list_all_patient_receipts", {"id": pid, "__caller": "export"}),
        "patient_overdue_payments": lambda pid: api_request("GET", "/payment/list_overdue_payments", {"person_id": pid, "__caller": "export"}),
        "patient_anamneses": lambda pid: api_request("GET", "/anamnesis_new/list_new_anamnesis", {"patient_id": pid, "__caller": "export"}),
        "patient_estimates": lambda pid: api_request("GET", "/treatment/list_estimates", {"patient_id": pid, "__caller": "export"}),
        "patient_clinical_sheets": lambda pid: api_request("GET", "/treatment/list_clinical_sheets", {"patient_id": pid, "__caller": "export"}),
        "patient_approved_treatment_plans": lambda pid: api_request("GET", "/treatment/list_treatment_plan_approved", {"patient_id": pid, "__caller": "export"}),
        "patient_recurring_plans": lambda pid: api_request("GET", "/financial/plan_control/get_patient_plans", {"PatientId": pid, "getInfo": "true"}),
        "patient_pictures": lambda pid: api_request("GET", "/patient/picture_list", {"id": pid, "__caller": "export"}),
        "patient_picture_folders": lambda pid: api_request("GET", "/folder/list_folders", {"id": pid, "ReferenceType": "PATIENT"}),
        "patient_financial_status": lambda pid: api_request("GET", "/patient/ext_financial_status/list_all", {"id": pid, "__caller": "export"}),
    }
    for name, fetcher in patient_gets.items():
        summary[name] = save_patient_dataset(name, patients, fetcher)

    # Calendar export by broad month windows. Clinicorp may ignore unsupported params, but keeps results separated.
    appointment_rows = []
    for year in range(2025, 2027):
        for month in range(1, 13):
            start = f"{year}{month:02d}01"
            end = f"{year}{month:02d}31"
            data = api_request("GET", "/appointment/list", {"from": start, "to": end, "__caller": "export"})
            appointment_rows.append({"from": start, "to": end, "data": data})
    summary["appointments_by_month"] = save_dataset("appointments_by_month", appointment_rows)

    summary_path = OUT / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
