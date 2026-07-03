"""
Chatbot inteligente para WhatsApp — Massera Estética.
Usa IA (Claude) para responder perguntas sobre procedimentos,
valores e promoções de forma natural.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from typing import Optional

from parvati_system.models import Agenda, Cliente, ConversaBot, ProcedimentoCatalogo, db

logger = logging.getLogger(__name__)

DIAS_DISPONIVEIS = 14
HORARIOS_PADRAO = ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"]
PROFISSIONAL_PADRAO = "Naiara"

SYSTEM_PROMPT = """Você é a assistente virtual da *Massera Estética*, uma clínica de estética em Minas Gerais. Seu nome é Mari.

Responda de forma simpática, natural e objetiva, como uma atendente humana no WhatsApp. Use emojis com moderação. Mensagens curtas e diretas.

== PROCEDIMENTOS E VALORES PROMOCIONAIS (por sessão) ==

CORPO:
• Barriga Zero — de R$ 899 por R$ 209,90/sessão
• Drenagem Linfática — de R$ 150 por R$ 120/sessão
• Radiofrequência — de R$ 120 por R$ 90/sessão
• Carboxiterapia — de R$ 150 por R$ 110/sessão
• Lipoenzimatica — de R$ 150 por R$ 130/sessão
• Hidrolipo — de R$ 450 por R$ 250/sessão
• Bumbum UP — de R$ 480 por R$ 350/sessão

FACIAL:
• Limpeza Facial — de R$ 180 por R$ 130/sessão
• Skinbooster — de R$ 500 por R$ 350/sessão
• Botox / Toxina Botulínica — de R$ 990 por R$ 800

Obs: esses são valores por sessão. Temos pacotes com valores ainda melhores — pergunte!

== OUTROS SERVIÇOS ==
• Tirzepatida (aplicação) — consulte valores
• MAF / Massagem MAF — consulte valores
• Corrente Russa — consulte valores
• Manta Térmica — consulte valores
• Lipocavitação — consulte valores
• Lipolaser — consulte valores
• Preenchimento Labial — consulte valores
• Aplicação capilar / vitaminas — consulte valores

== REGRAS ==
- Se perguntarem sobre pacotes, diga que temos e que a equipe vai passar os valores personalizados.
- Se a pessoa quiser agendar, diga que a equipe vai entrar em contato para confirmar horário.
- Nunca invente valores que não estão listados — diga "consulte nossa equipe".
- Não fale sobre temas fora da clínica.
- Se a pessoa mandar "oi", "olá" ou cumprimento sem pergunta, responda com boas-vindas e pergunte como pode ajudar.
- NUNCA mencione ebooks, livros digitais, infoprodutos ou qualquer produto digital a menos que a pessoa pergunte diretamente. Foque apenas nos procedimentos estéticos da clínica.

== QUANDO TRANSFERIR PARA HUMANO ==
Se qualquer um dos casos abaixo ocorrer, responda APENAS com o texto exato: [PRECISO_DE_HUMANO]
- A pergunta está fora do escopo da clínica (assuntos pessoais, outros negócios, etc.)
- Você não tem certeza da resposta e não quer inventar
- O cliente pede para falar com uma atendente ou pessoa real
- O cliente parece frustrado ou insistente com algo que você já respondeu
- O cliente menciona reclamação, problema com serviço, ou situação delicada
Não escreva mais nada além de [PRECISO_DE_HUMANO] nesses casos."""


def _chamar_ia(nome: str, historico: list[dict], mensagem: str) -> str:
    """Chama a API do Claude para gerar resposta inteligente."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    if not api_key:
        return "Olá! Para mais informações sobre procedimentos e valores, entre em contato com nossa equipe. 😊"

    messages = list(historico[-10:])  # últimas 10 mensagens de contexto
    messages.append({"role": "user", "content": mensagem})

    system = SYSTEM_PROMPT
    if nome:
        system += f"\n\nO nome da cliente nesta conversa é: {nome}."

    payload = json.dumps({
        "model": model,
        "max_tokens": 300,
        "system": system,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"].strip()
    except Exception:
        return "Desculpe, tive um probleminha aqui! Nossa equipe vai te atender em breve. 😊"


def _notificar_equipe(telefone_cliente: str, nome_cliente: str, ultima_mensagem: str) -> None:
    """Notifica a equipe via WhatsApp quando cliente precisa de atendimento humano."""
    numero = os.environ.get("NOTIFICACAO_NUMERO", "")
    if not numero:
        logger.info("NOTIFICACAO_NUMERO não configurado — handoff sem notificação")
        return
    try:
        from parvati_system.whatsapp import enviar_mensagem
        msg = (
            f"⚠️ *Cliente aguardando atendimento*\n\n"
            f"📱 Tel: {telefone_cliente}\n"
            f"👤 Nome: {nome_cliente or 'Não informado'}\n"
            f"💬 Mensagem: {ultima_mensagem[:200]}"
        )
        enviar_mensagem(numero, msg)
    except Exception as exc:
        logger.warning("Falha ao notificar equipe: %s", exc)


# ── helpers ──────────────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    return str(texto or "").strip().lower()


def _data_display(data_iso: str) -> str:
    """Converte YYYY-MM-DD para DD/MM/YYYY para exibição no chat."""
    try:
        return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return data_iso


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
        data_str = d.strftime("%Y-%m-%d")  # formato do banco
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


def _verificar_cliente_retornando(tel: str) -> Optional[str]:
    """
    Retorna o nome do cliente se já é conhecido (retornando), None se novo.
    Verifica tabela Cliente e conversas anteriores concluídas.
    """
    if not tel:
        return None

    # Busca no cadastro de clientes
    cliente = Cliente.query.filter(
        Cliente.telefone.contains(tel[-8:])
    ).first()
    if cliente and cliente.nome and cliente.nome not in ("Cliente WhatsApp", ""):
        return cliente.nome

    # Busca em conversas anteriores com nome registrado
    conversa_anterior = ConversaBot.query.filter_by(
        telefone=tel, canal="agenda"
    ).filter(
        ConversaBot.estado.in_(["concluido", "cancelado"]),
        ConversaBot.nome_remetente.isnot(None),
        ConversaBot.nome_remetente != "",
    ).order_by(ConversaBot.atualizado_em.desc()).first()

    if conversa_anterior and conversa_anterior.nome_remetente:
        return conversa_anterior.nome_remetente

    return None


# ── máquina de estados ────────────────────────────────────────────────────────

def _estado_inicio(conversa: ConversaBot, _texto: str) -> str:
    conversa.estado = "busca"
    conversa.dados = {}
    return (
        "Olá! 😊 Sou a Mari, assistente da *Massera Estética*.\n\n"
        "Qual é o seu nome?"
    )


def _estado_busca_nome(conversa: ConversaBot, texto: str) -> str:
    dados = conversa.dados or {}
    nome = texto.strip().title()
    dados["nome_cliente"] = nome
    dados["historico"] = []
    conversa.dados = dados
    conversa.nome_remetente = nome
    conversa.estado = "ia"
    return f"Prazer, *{nome}*! 🌸 Como posso te ajudar hoje?"


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
        linhas.append(f"{i+1}. *{dia} {_data_display(data_str)}* → {horas_str}")

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
        f"📅 *Data:* {_data_display(data_str)}\n"
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
        f"Te esperamos em *{_data_display(dados['data'])}* às *{dados['hora']}* "
        f"para *{dados['procedimento_nome']}*.\n\n"
        "Qualquer dúvida é só chamar. Até lá! 🌸"
    )


# ── entry point ───────────────────────────────────────────────────────────────

def _estado_ia(conversa: ConversaBot, texto: str) -> str:
    dados = conversa.dados or {}
    nome = dados.get("nome_cliente", conversa.nome_remetente or "")
    historico = dados.get("historico", [])

    # Detecta pedido explícito de falar com humano antes de chamar IA
    _texto_norm = _normalizar(texto)
    _pedido_humano = any(p in _texto_norm for p in (
        "falar com atendente", "falar com pessoa", "falar com humano",
        "quero atendente", "chamar atendente", "me chame", "me liga",
        "falar com a naiara", "quero falar com alguem", "quero falar com alguém",
    ))

    if _pedido_humano:
        conversa.estado = "aguardando_humano"
        _notificar_equipe(conversa.telefone, nome, texto)
        return (
            "Claro! 😊 Vou chamar uma atendente para te ajudar melhor.\n"
            "Em breve nossa equipe entrará em contato! 🌸"
        )

    resposta = _chamar_ia(nome, historico, texto)

    if "[PRECISO_DE_HUMANO]" in resposta:
        conversa.estado = "aguardando_humano"
        _notificar_equipe(conversa.telefone, nome, texto)
        return (
            "Entendido! 😊 Vou chamar nossa equipe para te ajudar melhor com isso.\n"
            "Em breve alguém entrará em contato! 🌸"
        )

    historico.append({"role": "user", "content": texto})
    historico.append({"role": "assistant", "content": resposta})
    dados["historico"] = historico[-20:]  # mantém últimas 20 mensagens
    conversa.dados = dados

    return resposta


def _estado_aguardando_humano(conversa: ConversaBot, _texto: str) -> str:
    """Cliente está aguardando atendimento humano — bot para de responder."""
    return "Nossa equipe logo entrará em contato com você! 😊"


_HANDLERS = {
    "inicio": _estado_inicio,
    "busca": _estado_busca_nome,
    "ia": _estado_ia,
    "aguardando_humano": _estado_aguardando_humano,
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

    nova_sessao_retorno = False

    if not conversa:
        nome_retorno = _verificar_cliente_retornando(tel)
        if nome_retorno:
            # Cliente já conhecido — pula etapa de nome
            conversa = ConversaBot(
                telefone=tel,
                canal="agenda",
                estado="ia",
                nome_remetente=nome_retorno,
                dados={"nome_cliente": nome_retorno, "historico": []},
            )
            nova_sessao_retorno = True
        else:
            # Primeiro contato — vai perguntar o nome
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

    # Cliente retornando: saúda pelo nome sem passar a mensagem pela IA
    if nova_sessao_retorno:
        nome_retorno = conversa.nome_remetente
        saudacao = f"Olá de volta, *{nome_retorno}*! 🌸 Como posso te ajudar hoje?"
        dados = conversa.dados or {}
        dados["historico"] = [{"role": "assistant", "content": saudacao}]
        conversa.dados = dados
        db.session.commit()
        return saudacao

    estado = conversa.estado
    handler = _HANDLERS.get(estado)
    if handler:
        resposta = handler(conversa, texto.strip())
    else:
        resposta = "Seu agendamento já foi registrado! Se precisar de mais alguma coisa, é só chamar. 😊"

    db.session.commit()
    return resposta
