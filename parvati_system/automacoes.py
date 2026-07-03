import logging
import random
import time
import urllib.parse
from datetime import date, timedelta

import schedule

from parvati_system.models import Cliente, DisparoCampanha, db
from parvati_system.whatsapp import enviar_mensagem as _wpp_enviar

logger = logging.getLogger(__name__)


def telefone_limpo(telefone):
    if not telefone:
        return ""
    return str(telefone).strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


def ja_disparou(cliente_id, tipo, data_hoje):
    disparo = DisparoCampanha.query.filter_by(
        cliente_id=cliente_id,
        tipo=tipo,
        data_envio=data_hoje
    ).first()

    return disparo is not None


def registrar_disparo(cliente_id, tipo, observacao="", link_whatsapp="", mensagem="", canal="whatsapp"):
    novo = DisparoCampanha(
        cliente_id=cliente_id,
        tipo=tipo,
        data_envio=date.today(),
        observacao=observacao,
        canal=canal,
        link_whatsapp=link_whatsapp,
        mensagem=mensagem
    )
    db.session.add(novo)
    db.session.commit()


def criar_link_whatsapp(telefone, mensagem):
    telefone = telefone_limpo(telefone)
    texto = urllib.parse.quote(mensagem)
    return f"https://wa.me/55{telefone}?text={texto}"


def gerar_cupom(nome):
    primeiro_nome = nome.strip().split()[0].upper() if nome else "CLIENTE"
    numero = random.randint(1000, 9999)
    return f"NIVER-{primeiro_nome}-{numero}"


def disparar_aniversarios():
    from parvati_system.app import app
    with app.app_context():
        hoje = date.today()
        links = []

        for cliente in Cliente.query.all():
            if not cliente.aniversario:
                continue

            if cliente.aniversario.day != hoje.day or cliente.aniversario.month != hoje.month:
                continue

            if ja_disparou(cliente.id, "aniversario", hoje):
                continue

            cupom = gerar_cupom(cliente.nome)
            cliente.cupom_aniversario = cupom
            db.session.commit()

            mensagem = f"""Feliz aniversario, {cliente.nome}!

A Parvati Estetica deseja um dia lindo para voce.

Preparamos um presente especial: use o cupom {cupom} no seu proximo procedimento."""

            link = criar_link_whatsapp(cliente.telefone, mensagem)
            enviado = False
            try:
                enviado = _wpp_enviar(cliente.telefone, mensagem)
            except Exception as exc:
                logger.error("Erro ao enviar aniversário para %s: %s", cliente.nome, exc)
            registrar_disparo(cliente.id, "aniversario", f"Cupom enviado: {cupom}", link, mensagem)
            links.append({"cliente": cliente.nome, "link": link, "mensagem": mensagem, "enviado": enviado})

        return links


def campanha_promocional(mensagem_base=None, observacao="Promocao automatica enviada"):
    from parvati_system.app import app
    with app.app_context():
        hoje = date.today()
        links = []

        for cliente in Cliente.query.all():
            if ja_disparou(cliente.id, "promocao", hoje):
                continue

            mensagem = mensagem_base or """Ola, {nome}!

Nesta semana a Parvati Estetica esta com uma condicao especial em procedimentos selecionados.

Entre em contato para garantir seu horario."""
            mensagem = mensagem.replace("{nome}", cliente.nome or "cliente")

            link = criar_link_whatsapp(cliente.telefone, mensagem)
            enviado = False
            try:
                enviado = _wpp_enviar(cliente.telefone, mensagem)
            except Exception as exc:
                logger.error("Erro ao enviar promoção para %s: %s", cliente.nome, exc)
            registrar_disparo(cliente.id, "promocao", observacao, link, mensagem)
            links.append({"cliente": cliente.nome, "link": link, "mensagem": mensagem, "enviado": enviado})

        return links


def recuperar_clientes_inativos():
    from parvati_system.app import app
    with app.app_context():
        hoje = date.today()
        limite = hoje - timedelta(days=90)
        links = []

        for cliente in Cliente.query.all():
            if not cliente.ultima_visita or cliente.ultima_visita > limite:
                continue

            if ja_disparou(cliente.id, "inativo", hoje):
                continue

            mensagem = f"""Oi, {cliente.nome}!

Sentimos sua falta na Parvati Estetica.

Preparamos uma condicao especial para seu retorno. Quer que eu te envie opcoes de horario?"""

            link = criar_link_whatsapp(cliente.telefone, mensagem)
            enviado = False
            try:
                enviado = _wpp_enviar(cliente.telefone, mensagem)
            except Exception as exc:
                logger.error("Erro ao enviar reativação para %s: %s", cliente.nome, exc)
            registrar_disparo(cliente.id, "inativo", "Campanha de retorno enviada", link, mensagem)
            links.append({"cliente": cliente.nome, "link": link, "mensagem": mensagem, "enviado": enviado})

        return links


def lembrar_retorno_procedimento():
    from parvati_system.app import app
    with app.app_context():
        hoje = date.today()
        links = []

        for cliente in Cliente.query.all():
            if not cliente.data_procedimento:
                continue

            dias = (hoje - cliente.data_procedimento).days
            if dias < 30 or ja_disparou(cliente.id, "retorno", hoje):
                continue

            mensagem = f"""Ola, {cliente.nome}!

Ja faz um tempinho desde seu ultimo procedimento na Parvati Estetica.

Esse pode ser um bom momento para retorno ou manutencao. Quer que eu separe alguns horarios?"""

            link = criar_link_whatsapp(cliente.telefone, mensagem)
            enviado = False
            try:
                enviado = _wpp_enviar(cliente.telefone, mensagem)
            except Exception as exc:
                logger.error("Erro ao enviar lembrete de retorno para %s: %s", cliente.nome, exc)
            registrar_disparo(cliente.id, "retorno", "Lembrete de retorno enviado", link, mensagem)
            links.append({"cliente": cliente.nome, "link": link, "mensagem": mensagem, "enviado": enviado})

        return links


def _disparar_lembretes_agendamento():
    """Envia lembretes WhatsApp para os agendamentos do dia seguinte."""
    from parvati_system.app import app
    from parvati_system.lembretes import enviar_lembretes
    with app.app_context():
        try:
            res = enviar_lembretes()
            logger.info(
                "Lembretes automáticos enviados — %s: %d clientes, %d profissionais, %d falhas",
                res["data"], res["clientes_enviados"], res["profissionais_enviados"], res["falhas"],
            )
        except Exception as exc:
            logger.error("Erro ao enviar lembretes automáticos: %s", exc)


schedule.every().day.at("09:00").do(disparar_aniversarios)
schedule.every().monday.at("10:00").do(campanha_promocional)
schedule.every().day.at("11:00").do(recuperar_clientes_inativos)
schedule.every().day.at("12:00").do(lembrar_retorno_procedimento)
schedule.every().day.at("08:00").do(_disparar_lembretes_agendamento)


def iniciar_automacoes():
    while True:
        schedule.run_pending()
        time.sleep(60)
