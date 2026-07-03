"""
Envio de lembretes de agendamento via WhatsApp.

Pode ser chamado de duas formas:
  1. Pelo painel admin (rota /lembretes/enviar) — sem necessidade de cron externo.
  2. Por cron externo (ex: cron-job.org) via POST /api/lembretes com header X-Cron-Token.

Variáveis de ambiente para números dos profissionais (fallback se não cadastrado no sistema):
  WHATSAPP_NAIARA      = 5531991269732
  WHATSAPP_POLYANA     = 55319...
  WHATSAPP_ANA_CLAUDIA = 55319...
  WHATSAPP_LIZANDRA    = 55319...
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta

from parvati_system.models import Agenda

logger = logging.getLogger(__name__)


def _amanha_iso() -> str:
    """Retorna amanhã no formato YYYY-MM-DD (padrão do banco)."""
    return (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")


def _data_display(data_iso: str) -> str:
    """Converte YYYY-MM-DD para DD/MM/YYYY para exibição ao cliente."""
    try:
        return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return data_iso


def _numero_profissional(nome: str) -> str:
    """Busca o WhatsApp da profissional pelo cadastro de funcionárias."""
    from parvati_system.models import User
    usuario = User.query.filter_by(profissional=nome, ativo=True).first()
    if usuario and usuario.telefone:
        tel = usuario.telefone.strip()
        if not tel.startswith("55"):
            tel = "55" + tel
        return tel
    # Fallback para variável de ambiente
    chave = "WHATSAPP_" + nome.upper().replace(" ", "_")
    return os.environ.get(chave, "")


def _msg_cliente(ag: Agenda) -> str:
    nome = ag.cliente or "Cliente"
    data_display = _data_display(ag.data)
    return (
        f"Olá, *{nome}*! 😊\n\n"
        f"Lembrando que você tem um agendamento *amanhã* na *Massera Estética*:\n\n"
        f"📋 *{ag.procedimento}*\n"
        f"📅 {data_display}  🕐 {ag.hora}\n"
        + (f"👩 Com: {ag.profissional}\n" if ag.profissional else "") +
        f"\nTe esperamos! Se precisar reagendar, nos avise com antecedência. 🌸"
    )


def _msg_profissional(profissional: str, agendamentos: list[Agenda], data_iso: str) -> str:
    ags = sorted(agendamentos, key=lambda a: a.hora or "")
    data_display = _data_display(data_iso)
    linhas = [f"📅 *Agenda de amanhã — {data_display}*\n"]
    for ag in ags:
        linha = f"🕐 *{ag.hora}* — {ag.cliente or '?'} — {ag.procedimento or '?'}"
        if ag.telefone:
            linha += f"\n   📱 {ag.telefone}"
        linhas.append(linha)
    linhas.append(f"\nTotal: *{len(ags)}* atendimento(s). Bom trabalho! 💪")
    return "\n".join(linhas)


def enviar_lembretes(data_iso: str | None = None) -> dict:
    """
    Envia lembretes para os agendamentos da data informada.
    data_iso: formato YYYY-MM-DD (padrão do banco). Se None, usa amanhã.
    Retorna dict com resumo: total, clientes_enviados, profissionais_enviados, falhas.
    """
    from parvati_system.whatsapp import enviar_mensagem

    if not data_iso:
        data_iso = _amanha_iso()

    agendamentos = Agenda.query.filter(
        Agenda.data == data_iso,
        Agenda.status.in_(["agendado", "confirmado"]),
    ).all()

    resultado = {
        "data": data_iso,
        "total_agendamentos": len(agendamentos),
        "clientes_enviados": 0,
        "profissionais_enviados": 0,
        "falhas": 0,
        "erros": [],
    }

    if not agendamentos:
        return resultado

    # ── Lembretes individuais para clientes ──────────────────────────────
    for ag in agendamentos:
        if not ag.telefone:
            continue
        try:
            enviar_mensagem(ag.telefone, _msg_cliente(ag))
            resultado["clientes_enviados"] += 1
        except Exception as exc:
            resultado["falhas"] += 1
            resultado["erros"].append(f"{ag.cliente}: {exc}")
            logger.warning("Falha lembrete cliente %s: %s", ag.telefone, exc)

    # ── Resumo do dia para cada profissional ─────────────────────────────
    por_profissional: dict[str, list[Agenda]] = {}
    for ag in agendamentos:
        prof = ag.profissional or ""
        if prof:
            por_profissional.setdefault(prof, []).append(ag)

    for profissional, ags in por_profissional.items():
        numero = _numero_profissional(profissional)
        if not numero:
            continue
        try:
            enviar_mensagem(numero, _msg_profissional(profissional, ags, data_iso))
            resultado["profissionais_enviados"] += 1
        except Exception as exc:
            resultado["falhas"] += 1
            resultado["erros"].append(f"Prof {profissional}: {exc}")
            logger.warning("Falha lembrete profissional %s: %s", profissional, exc)

    return resultado


def enviar_lembretes_amanha() -> dict:
    return enviar_lembretes(None)
