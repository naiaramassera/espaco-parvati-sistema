import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.clinicorp_export_patients import flatten_value


OUT = Path(r"C:\tmp\clinicorp_export_all")


def rows_from_data(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "List", "items", "data", "Plans", "DefaultPlansList"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def consolidate_jsonl(path):
    records = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            records.append(json.loads(line))

    json_path = path.with_suffix(".json")
    csv_path = path.with_suffix(".csv")
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    flat_rows = []
    for item in records:
        data = item.get("data")
        rows = rows_from_data(data)
        if rows:
            for row in rows:
                if isinstance(row, dict):
                    flat_rows.append({
                        "patient_id": item.get("patient_id"),
                        "patient_name": item.get("patient_name"),
                        **row,
                    })
        elif isinstance(data, dict) and not data.get("_error"):
            flat_rows.append({
                "patient_id": item.get("patient_id"),
                "patient_name": item.get("patient_name"),
                **data,
            })

    if flat_rows:
        fields = []
        for row in flat_rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in flat_rows:
                writer.writerow({key: flatten_value(row.get(key)) for key in fields})

    return {
        "records": len(records),
        "json": str(json_path),
        "csv": str(csv_path) if flat_rows else "",
        "flat_rows": len(flat_rows),
    }


def main():
    summary = {}
    for path in sorted(OUT.glob("*.jsonl")):
        summary[path.stem] = consolidate_jsonl(path)

    for path in sorted(OUT.glob("*.json")):
        if path.name == "summary.json":
            continue
        summary.setdefault(path.stem, {
            "records": None,
            "json": str(path),
            "csv": str(path.with_suffix(".csv")) if path.with_suffix(".csv").exists() else "",
        })

    summary["notes"] = {
        "patient_pictures": "Parcial: endpoint lento; 50 pacientes processados nesta rodada.",
        "patients_expected": 521,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
