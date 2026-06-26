"""
Chatbot de agendamento via WhatsApp.

Fluxo de conversa:
  INICIO → o cliente manda qualquer mensagem
  PROCEDIMENTO → bot lista procedimentos e pede escolha
  HORARIO → bot lista horários disponíveis e pede escolha
  CONFIRMAR → bot confirma os dados e pede confirmação
  CONCLUIDO → agendamento gravado, conversa encerrada

A conversa fica salva em ConversaBot no banco de dados.
O webhook em routes.py chama processar_mensagem() com a
mensagem recebida e o número do remetente.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from parvati_system.models import Agenda, Cliente, ConversaBot, ProcedimentoCatalogo, db

DIAS_DISPONIVEIS = 14  # quantos dias à frente oferecer horários
HORARIOS_PADRAO = ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"]
PROFISSIONAL_PADRAO = "Naiara"


# ── helpers ──────────────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    return str(texto or "").strip().lower()


def _digitos(valor: str) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _horarios_livres(data_str: str, profissional: str) -> list[str]:
    ocupados = {
        a.hora for a in Agenda.query.filter_by(
            data=data_str, profissional=profissional
        ).filter(Agenda.status.notin_(["cancelado", "bloqueado"])).all()
    }
    return [h for h in HORARIOS_PADRAO if h not in ocupados]


def _datas_com_vaga(profissional: str) -> list[tuple[str, str, list[str]]]:
    """Retorna até 5 datas com horários livres nos próximos DIAS_DISPONIVEIS dias."""
    resultado = []
    hoje = date.today()
    for delta in range(1, DIAS_DISPONIVEIS + 1):
        d = hoje + timedelta(days=delta)
        if d.weekday() == 6:  # domingo
            continue
        data_str = d.strftime("%d/%m/%Y")
        livres = _horarios_livres(data_str, profissional)
        if livres:
            dia_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"][d.weekday()]
            resultado.append((data_str, dia_semana, livres[:4]))
        if len(resultado) >= 5:
            break
    return resultado


def _encontrar_ou_criar_cliente(nome: str, telefone: str) -> Cliente:
    tel = _digitos(telefone)
    cliente = Cliente.query.filter(
        Cliente.telefone.contains(tel[-8:])
    ).first() if tel else None
    if not cliente:
        cliente = Cliente(nome=nome or "Cliente WhatsApp", telefone=telefone)
        db.session.add(cliente)
        db.session.flush()
    return cliente


# ── máquina de estados ────────────────────────────────────────────────────────

def _estado_inicio(conversa: ConversaBot, _texto: str) -> str:
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.nome
    ).limit(8).all()

    if not procedimentos:
        conversa.estado = "sem_catalogo"
        return (
            "Olá! 😊 Sou a assistente da Parvati Estética.\n\n"
            "No momento nosso catálogo está sendo atualizado. "
            "Vou chamar a equipe para te ajudar. Pode aguardar?"
        )

    lista = "\n".join(
        f"{i+1}. {p.nome}" + (f" – R$ {p.valor_padrao:.0f}" if p.valor_padrao else "")
        for i, p in enumerate(procedimentos)
    )
    conversa.estado = "procedimento"
    conversa.dados = {}
    return (
        f"Olá! 😊 Sou a assistente da *Parvati Estética*.\n\n"
        f"Temos os seguintes procedimentos disponíveis:\n\n{lista}\n\n"
        "Qual você tem interesse? Responda com o número ou o nome."
    )


def _estado_procedimento(conversa: ConversaBot, texto: str) -> str:
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.nome
    ).limit(8).all()

    escolhido: Optional[ProcedimentoCatalogo] = None

    if texto.isdigit():
        idx = int(texto) - 1
        if 0 <= idx < len(procedimentos):
            escolhido = procedimentos[idx]
    else:
        for p in procedimentos:
            if _normalizar(p.nome) in _normalizar(texto) or _normalizar(texto) in _normalizar(p.nome):
                escolhido = p
                break

    if not escolhido:
        lista = "\n".join(f"{i+1}. {p.nome}" for i, p in enumerate(procedimentos))
        return f"Não encontrei essa opção. Por favor, escolha pelo número:\n\n{lista}"

    dados = conversa.dados or {}
    dados["procedimento_id"] = escolhido.id
    dados["procedimento_nome"] = escolhido.nome
    dados["procedimento_valor"] = float(escolhido.valor_padrao or 0)
    dados["profissional"] = PROFISSIONAL_PADRAO
    conversa.dados = dados
    conversa.estado = "horario"

    datas = _datas_com_vaga(PROFISSIONAL_PADRAO)
    if not datas:
        conversa.estado = "sem_vaga"
        return (
            f"Que ótimo! Você escolheu *{escolhido.nome}*. 🌟\n\n"
            "No momento não encontrei horários disponíveis nos próximos dias. "
            "Vou passar seu contato para a equipe te chamar, tudo bem?"
        )

    linhas = []
    for i, (data_str, dia, horas) in enumerate(datas):
        horas_str = "  |  ".join(horas)
        linhas.append(f"{i+1}. *{dia} {data_str}* → {horas_str}")

    dados["datas_opcoes"] = [d[0] for d in datas]
    dados["datas_horas"] = {d[0]: d[2] for d in datas}
    conversa.dados = dados

    return (
        f"Ótima escolha! *{escolhido.nome}* ✨\n\n"
        "Estes são os horários disponíveis:\n\n"
        + "\n".join(linhas) +
        "\n\nResponda com o número da data e o horário desejado.\n"
        "Exemplo: *1 14:00*"
    )


def _estado_horario(conversa: ConversaBot, texto: str) -> str:
    dados = conversa.dados or {}
    datas = dados.get("datas_opcoes", [])
    horas_por_data = dados.get("datas_horas", {})

    match = re.search(r"(\d+)[\s\-:]*(\d{1,2}[:h]\d{2})", texto)
    if not match:
        return (
            "Por favor, responda com o número da data e o horário.\n"
            "Exemplo: *1 14:00*"
        )

    idx = int(match.group(1)) - 1
    hora_raw = match.group(2).replace("h", ":")
    if len(hora_raw) == 4:
        hora_raw = "0" + hora_raw  # 9:00 → 09:00

    if idx < 0 or idx >= len(datas):
        return f"Data inválida. Escolha entre 1 e {len(datas)}."

    data_str = datas[idx]
    horas_livres = horas_por_data.get(data_str, [])
    hora_normalizada = None
    for h in horas_livres:
        if h.replace(":", "") == hora_raw.replace(":", ""):
            hora_normalizada = h
            break

    if not hora_normalizada:
        return (
            f"Esse horário não está disponível em {data_str}.\n"
            "Horários livres: " + "  |  ".join(horas_livres)
        )

    dados["data"] = data_str
    dados["hora"] = hora_normalizada
    conversa.dados = dados
    conversa.estado = "confirmar"

    return (
        f"Perfeito! Confirmando seu agendamento:\n\n"
        f"📋 *Procedimento:* {dados['procedimento_nome']}\n"
        f"📅 *Data:* {data_str}\n"
        f"🕐 *Horário:* {hora_normalizada}\n"
        + (f"💰 *Valor:* R$ {dados['procedimento_valor']:.2f}\n" if dados.get('procedimento_valor') else "") +
        "\nConfirma? Responda *SIM* para confirmar ou *NÃO* para cancelar."
    )


def _estado_confirmar(conversa: ConversaBot, texto: str) -> str:
    dados = conversa.dados or {}
    resposta = _normalizar(texto)

    if resposta in ("nao", "não", "n", "cancelar"):
        conversa.estado = "cancelado"
        return "Tudo bem! Se quiser agendar outro horário, é só me chamar. 😊"

    if resposta not in ("sim", "s", "confirmar", "ok", "yes"):
        return "Responda *SIM* para confirmar ou *NÃO* para cancelar."

    cliente = _encontrar_ou_criar_cliente(conversa.nome_remetente, conversa.telefone)

    agendamento = Agenda(
        cliente_id=cliente.id,
        cliente=conversa.nome_remetente or "Cliente WhatsApp",
        telefone=conversa.telefone,
        procedimento=dados["procedimento_nome"],
        procedimento_id=dados.get("procedimento_id"),
        data=dados["data"],
        hora=dados["hora"],
        profissional=dados.get("profissional", PROFISSIONAL_PADRAO),
        valor=dados.get("procedimento_valor"),
        status="agendado",
        observacoes="Agendado via WhatsApp",
    )
    db.session.add(agendamento)

    conversa.estado = "concluido"
    conversa.agendamento_id = agendamento.id
    db.session.commit()

    return (
        f"✅ *Agendamento confirmado!*\n\n"
        f"Te esperamos em *{dados['data']}* às *{dados['hora']}* "
        f"para *{dados['procedimento_nome']}*.\n\n"
        "Qualquer dúvida é só chamar. Até lá! 🌸"
    )


# ── entry point ───────────────────────────────────────────────────────────────

_HANDLERS = {
    "inicio": _estado_inicio,
    "procedimento": _estado_procedimento,
    "horario": _estado_horario,
    "confirmar": _estado_confirmar,
}


def processar_mensagem(telefone: str, texto: str, nome: str = "") -> str:
    """
    Recebe uma mensagem do WhatsApp e retorna a resposta do bot.
    Deve ser chamado dentro do app context do Flask.
    """
    tel = _digitos(telefone)
    conversa = ConversaBot.query.filter_by(telefone=tel, canal="agenda").filter(
        ConversaBot.estado.notin_(["concluido", "cancelado", "sem_catalogo", "sem_vaga"])
    ).order_by(ConversaBot.atualizado_em.desc()).first()

    if not conversa:
        conversa = ConversaBot(
            telefone=tel,
            canal="agenda",
            estado="inicio",
            nome_remetente=nome or "",
            dados={},
        )
        db.session.add(conversa)

    if nome and not conversa.nome_remetente:
        conversa.nome_remetente = nome

    conversa.atualizado_em = datetime.utcnow()
    estado = conversa.estado

    handler = _HANDLERS.get(estado)
    if handler:
        resposta = handler(conversa, texto.strip())
    else:
        resposta = "Seu agendamento já foi registrado! Se precisar de mais alguma coisa, é só chamar. 😊"

    db.session.commit()
    return resposta
