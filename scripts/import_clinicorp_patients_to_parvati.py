import csv
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parvati_system.app import app
from parvati_system.models import Cliente, db


DETAIL_SOURCE = Path(r"C:\tmp\clinicorp_patient_details.csv")
BASIC_SOURCE = Path(r"C:\tmp\clinicorp_patients.csv")
SOURCE = DETAIL_SOURCE if DETAIL_SOURCE.exists() else BASIC_SOURCE


def clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() in {"nan", "none", "nat"} else value


def digits(value):
    return "".join(ch for ch in clean(value) if ch.isdigit())


def parse_int(value):
    value = digits(value)
    return int(value) if value else None


def parse_date(value):
    value = clean(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def find_existing(nome, telefone, clinicorp_id):
    if clinicorp_id:
        found = Cliente.query.filter(Cliente.observacao.contains(f"Clinicorp ID: {clinicorp_id}")).first()
        if found:
            return found

    if telefone:
        found = Cliente.query.filter_by(telefone=telefone).first()
        if found:
            return found

    if nome:
        return Cliente.query.filter_by(nome=nome).first()

    return None


def update_if_empty(cliente, **fields):
    changed = False
    for key, value in fields.items():
        if value in (None, ""):
            continue
        if not getattr(cliente, key):
            setattr(cliente, key, value)
            changed = True
    return changed


def merge_observacao(existing, addition):
    existing = clean(existing)
    addition = clean(addition)
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing} | {addition}"


def row_to_fields(row):
    clinicorp_id = clean(row.get("id"))
    prontuario = clean(row.get("ClinicalRecordNumber"))
    telefone = (
        digits(row.get("MobilePhone"))
        or digits(row.get("OriginalMobilePhone"))
        or digits(row.get("Landline"))
    )
    nascimento_texto = clean(row.get("BirthDate"))
    nascimento = parse_date(nascimento_texto)
    cep = clean(row.get("Zip")) or clean(row.get("CEP"))
    endereco = " ".join(
        part
        for part in [
            clean(row.get("Address")),
            clean(row.get("AddressNumber")),
            clean(row.get("AddressComplement")),
        ]
        if part
    )
    indicado_por = (
        clean(row.get("IndicationSource"))
        or clean(row.get("HowDidMeet"))
        or clean(row.get("OthersSource"))
    )

    observacoes = []
    if clinicorp_id:
        observacoes.append(f"Clinicorp ID: {clinicorp_id}")
    if prontuario:
        observacoes.append(f"Prontuario Clinicorp: {prontuario}")
    if clean(row.get("ResponsiblePersonName")):
        observacoes.append(f"Responsavel: {clean(row.get('ResponsiblePersonName'))}")
    if digits(row.get("ResponsiblePersonMobilePhone")):
        observacoes.append(f"Telefone responsavel: {digits(row.get('ResponsiblePersonMobilePhone'))}")
    if clean(row.get("Notes")):
        observacoes.append(f"Notas Clinicorp: {clean(row.get('Notes'))}")
    if clean(row.get("Profession")):
        observacoes.append(f"Profissao: {clean(row.get('Profession'))}")
    if clean(row.get("Workplace")):
        observacoes.append(f"Local de trabalho: {clean(row.get('Workplace'))}")

    return {
        "clinicorp_id": clinicorp_id,
        "nome": clean(row.get("Name")),
        "documento": clean(row.get("DocumentId")),
        "outro_documento": digits(row.get("OtherDocumentId")),
        "idade": parse_int(row.get("Age")),
        "email": clean(row.get("Email")),
        "telefone": telefone,
        "nascimento": nascimento_texto,
        "endereco": endereco,
        "bairro": clean(row.get("Neighborhood")),
        "estado": clean(row.get("state")),
        "cep": cep,
        "estado_civil": clean(row.get("CivilStatus")),
        "grau": clean(row.get("Education")),
        "indicado_por": indicado_por,
        "aniversario": nascimento,
        "sexo": clean(row.get("Sex")),
        "nome_pai": clean(row.get("fatherName")),
        "observacao": " | ".join(observacoes),
    }


def main():
    if not SOURCE.exists():
        raise SystemExit(f"Arquivo nao encontrado: {SOURCE}")

    created = 0
    updated = 0
    skipped = 0

    with app.app_context():
        with SOURCE.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                fields = row_to_fields(row)
                nome = fields.pop("nome")
                clinicorp_id = fields.pop("clinicorp_id")
                telefone = fields.get("telefone")

                if not nome:
                    skipped += 1
                    continue

                cliente = find_existing(nome, telefone, clinicorp_id)
                if cliente:
                    merged_observacao = merge_observacao(cliente.observacao, fields.pop("observacao"))
                    changed = update_if_empty(cliente, nome=nome, **fields, observacao=merged_observacao)
                    if cliente.observacao != merged_observacao:
                        cliente.observacao = merged_observacao
                        changed = True
                    updated += 1 if changed else 0
                    continue

                db.session.add(Cliente(nome=nome, **fields))
                created += 1

        db.session.commit()
        total = Cliente.query.count()

    print(f"origem={SOURCE}")
    print(f"criados={created}")
    print(f"atualizados={updated}")
    print(f"ignorados={skipped}")
    print(f"total_clientes={total}")


if __name__ == "__main__":
    main()
