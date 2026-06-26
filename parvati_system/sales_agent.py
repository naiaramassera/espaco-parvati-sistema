from datetime import datetime


PALAVRAS_QUENTES = {
    "botox": 28,
    "bioestimulador": 28,
    "preenchimento": 26,
    "peeling": 18,
    "limpeza": 14,
    "avaliacao": 12,
    "avaliacao facial": 16,
    "valor": 18,
    "preco": 18,
    "agenda": 16,
    "horario": 16,
    "urgente": 22,
    "hoje": 18,
    "semana": 12,
}


def somente_digitos(valor):
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def normalizar_texto(valor):
    return str(valor or "").strip().lower()


def calcular_score_lead(lead):
    texto = " ".join([
        normalizar_texto(lead.nome),
        normalizar_texto(lead.interesse),
        normalizar_texto(lead.mensagem),
        normalizar_texto(lead.origem),
    ])
    score = 10

    if somente_digitos(lead.telefone):
        score += 22
    if lead.email:
        score += 8
    if lead.mensagem and len(lead.mensagem) > 25:
        score += 10
    if lead.origem and lead.origem != "manual":
        score += 8

    for palavra, peso in PALAVRAS_QUENTES.items():
        if palavra in texto:
            score += peso

    return max(0, min(100, score))


def prioridade_por_score(score):
    if score >= 75:
        return "quente"
    if score >= 45:
        return "morno"
    return "normal"


def melhor_procedimento(lead, procedimentos):
    texto = normalizar_texto(f"{lead.interesse} {lead.mensagem}")
    for procedimento in procedimentos:
        nome = normalizar_texto(procedimento.nome)
        categoria = normalizar_texto(procedimento.categoria)
        if nome and nome in texto:
            return procedimento
        if categoria and categoria in texto:
            return procedimento
    return procedimentos[0] if procedimentos else None


def gerar_abordagem_lead(lead, procedimentos):
    score = calcular_score_lead(lead)
    prioridade = prioridade_por_score(score)
    procedimento = melhor_procedimento(lead, procedimentos)
    interesse = lead.interesse or (procedimento.nome if procedimento else "avaliacao estetica")

    if prioridade == "quente":
        tom = "Vi seu interesse e consigo te ajudar a escolher o melhor horario."
    elif prioridade == "morno":
        tom = "Posso te explicar as opcoes e ver se faz sentido para o seu objetivo."
    else:
        tom = "Obrigada pelo contato. Posso entender melhor o que voce procura?"

    valor = ""
    if procedimento and procedimento.valor_padrao:
        valor = f"\n\nA referencia inicial de {procedimento.nome} fica a partir de R$ {procedimento.valor_padrao:.2f}, mas confirmamos tudo apos avaliacao."

    mensagem = (
        f"Ola {lead.nome}! Aqui e da Parvati Estetica.\n\n"
        f"{tom}\n\n"
        f"Voce comentou sobre {interesse}. Quer que eu te envie algumas opcoes de horario para avaliacao?"
        f"{valor}"
    )

    resumo = (
        f"Lead {prioridade} com score {score}. Prioridade por interesse, telefone informado "
        f"e sinais de intencao na mensagem."
    )

    return {
        "score": score,
        "prioridade": prioridade,
        "mensagem": mensagem,
        "resposta_ia": resumo,
        "procedimento": procedimento.nome if procedimento else "",
        "atualizado_em": datetime.utcnow(),
    }


def recomendacoes_comerciais(leads, clientes_inativos, retornos):
    tarefas = []
    leads_quentes = [lead for lead in leads if lead.prioridade == "quente" and lead.status in ("novo", "em_contato")]
    leads_novos = [lead for lead in leads if lead.status == "novo"]

    tarefas.append({
        "titulo": "Responder leads quentes",
        "quantidade": len(leads_quentes),
        "acao": "Abrir agente comercial",
        "ancora": "#leads-quentes",
    })
    tarefas.append({
        "titulo": "Qualificar novos leads",
        "quantidade": len(leads_novos),
        "acao": "Gerar abordagem",
        "ancora": "#leads-novos",
    })
    tarefas.append({
        "titulo": "Reativar clientes inativos",
        "quantidade": len(clientes_inativos),
        "acao": "Enviar convite de retorno",
        "ancora": "#clientes-inativos",
    })
    tarefas.append({
        "titulo": "Fechar retornos previstos",
        "quantidade": len(retornos),
        "acao": "Chamar no WhatsApp",
        "ancora": "#retornos",
    })
    return tarefas
