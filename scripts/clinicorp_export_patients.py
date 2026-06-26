import csv
import json
from pathlib import Path
from urllib import request, parse, error


TMP = Path(r"C:\tmp")
NETWORK_FILE = TMP / "clinicorp_network.jsonl"
STATE_FILE = TMP / "clinicorp_logged_state.json"
OUT_JSON = TMP / "clinicorp_patients.json"
OUT_CSV = TMP / "clinicorp_patients.csv"


def find_token():
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for cookie in state.get("cookies", []):
            if cookie.get("name") == "authorization" and cookie.get("value"):
                return cookie["value"].removeprefix("Bearer ")

    for line in NETWORK_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "security/user/login" not in line or '"success":true' not in line:
            continue
        record = json.loads(line)
        body = json.loads(record["body_start"])
        token = body.get("user", {}).get("token")
        if token:
            return token
    raise RuntimeError("Token de login nao encontrado em C:\\tmp\\clinicorp_network.jsonl")


def api_get(path, params=None):
    token = find_token()
    query = f"?{parse.urlencode(params or {})}" if params else ""
    req = request.Request(
        f"https://api.clinicorp.com/api{path}{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Origin": "https://sistema.clinicorp.com",
            "Referer": "https://sistema.clinicorp.com/",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc


def flatten_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else value


def main():
    data = api_get("/patient/list_all", {"removeDeleted": "false"})
    patients = data.get("list", data if isinstance(data, list) else [])
    OUT_JSON.write_text(json.dumps(patients, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = []
    for patient in patients:
        for key in patient.keys():
            if key not in fields:
                fields.append(key)

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for patient in patients:
            writer.writerow({key: flatten_value(patient.get(key)) for key in fields})

    print(f"pacientes={len(patients)}")
    print(str(OUT_JSON))
    print(str(OUT_CSV))


if __name__ == "__main__":
    main()
