import json
import os
import urllib.parse
from functools import wraps
from datetime import date
from datetime import datetime, timedelta

from flask import render_template, request, redirect, flash, url_for, jsonify
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from parvati_system.app import app, CORES_PROFISSIONAIS, PROFISSIONAIS
from parvati_system.models import (
    db, Cliente, Agenda, Anamnese, User, Financeiro, DisparoCampanha,
    FotoEvolucao, ProdutoEstoque, MovimentacaoEstoque, ProcedimentoCatalogo,
    ProcedimentoInsumo, CampanhaIA, LeadComercial
)
from parvati_system.automacoes import (disparar_aniversarios, recuperar_clientes_inativos, lembrar_retorno_procedimento,
                                       campanha_promocional, criar_link_whatsapp, registrar_disparo)
from parvati_system.ai_engine import gerar_campanha_ia, montar_contexto_marketing
from parvati_system.meta_marketing import publicar_campanha
from parvati_system.sales_agent import gerar_abordagem_lead, recomendacoes_comerciais, somente_digitos


def data_hoje_texto():
    return date.today().strftime("%Y-%m-%d")


def url_publica(endpoint, **valores):
    return url_for(endpoint, _external=True, **valores)


def gerar_linha_digitavel_simulada(financeiro):
    base = f"{financeiro.id:06d}{int((financeiro.valor or 0) * 100):010d}"
    return f"34191.79001 {base[:5]}.{base[5:10]} {base[10:15]}.{base[15:]} 1 00000000000000"


STATUS_AGENDAMENTO = {
    "agendado": "Agendado",
    "confirmado": "Confirmado",
    "atendido": "Atendido",
    "cancelado": "Cancelado",
    "faltou": "Faltou",
    "bloqueado": "Bloqueado",
}

NOME_CLINICA = "Parvati Estetica"


def usuario_admin():
    return getattr(current_user, "perfil", None) == "admin"


def usuario_pode_ver_agendamento(agendamento):
    if usuario_admin():
        return True

    return (
        agendamento.tipo == "atendimento"
        and current_user.profissional
        and agendamento.profissional == current_user.profissional
    )


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not usuario_admin():
            flash("Acesso restrito a administradora.")
            return redirect(url_for("agenda"))

        return func(*args, **kwargs)

    return wrapper


def senha_valida(user, senha):
    if not user or not user.senha:
        return False

    if user.senha.startswith("scrypt:") or user.senha.startswith("pbkdf2:"):
        return check_password_hash(user.senha, senha)

    # Compatibilidade com senhas antigas salvas em texto puro.
    if user.senha == senha:
        user.senha = generate_password_hash(senha)
        db.session.commit()
        return True

    return False


def senha_forte(senha):
    return senha and len(senha) >= 8


def agendamento_para_visao(agendamento):
    if agendamento.tipo == "bloqueio":
        agendamento.visivel_cliente = "Bloqueado"
        agendamento.visivel_procedimento = agendamento.procedimento or "Horario bloqueado"
        agendamento.visivel_valor = None
        agendamento.visivel_detalhes = usuario_admin() or agendamento.profissional == current_user.profissional
        return agendamento

    if usuario_pode_ver_agendamento(agendamento):
        agendamento.visivel_cliente = agendamento.cliente
        agendamento.visivel_procedimento = agendamento.procedimento
        agendamento.visivel_valor = agendamento.valor
        agendamento.visivel_detalhes = True
        return agendamento

    agendamento.visivel_cliente = "Horario ocupado"
    agendamento.visivel_procedimento = "Atendimento reservado"
    agendamento.visivel_valor = None
    agendamento.visivel_detalhes = False
    return agendamento


def calcular_custo_real_procedimento(procedimento_id):
    insumos = ProcedimentoInsumo.query.filter_by(procedimento_id=procedimento_id).all()
    total = 0

    for insumo in insumos:
        produto = ProdutoEstoque.query.get(insumo.produto_id)
        custo_unitario = (produto.custo_unitario if produto and produto.custo_unitario is not None else insumo.custo_unitario_snapshot) or 0
        total += (insumo.quantidade or 0) * custo_unitario

    return total


def definir_status(agendamento, status):
    if status not in STATUS_AGENDAMENTO:
        status = "agendado"

    agendamento.status = status


def bloquear_se_sem_permissao(agendamento):
    if usuario_pode_ver_agendamento(agendamento) or (
        agendamento.tipo == "bloqueio"
        and (usuario_admin() or agendamento.profissional == current_user.profissional)
    ):
        return None

    flash("Voce pode ver que o horario esta ocupado, mas os dados do cliente sao restritos.")
    return redirect(url_for("agenda", data=agendamento.data))


def localizar_cliente_agendamento(nome=None, telefone=None):
    cliente = None

    if telefone:
        cliente = Cliente.query.filter_by(telefone=telefone).first()

    if not cliente and nome:
        cliente = Cliente.query.filter_by(nome=nome).first()

    return cliente


def query_atendimentos_cliente(cliente):
    return Agenda.query.filter(
        or_(Agenda.cliente_id == cliente.id, Agenda.cliente == cliente.nome)
    ).order_by(Agenda.data.desc(), Agenda.hora.desc())


def data_agendamento_para_date(data_texto):
    try:
        return datetime.strptime(data_texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def gerar_mensagem_confirmacao(agendamento):
    cliente = Cliente.query.get(agendamento.cliente_id) if agendamento.cliente_id else localizar_cliente_agendamento(
        agendamento.cliente,
        agendamento.telefone
    )

    links = []
    if cliente:
        links.append(f"Anamnese: {url_publica('anamnese_cliente_publica', id=cliente.id)}")

    links.append(f"Contrato/termo: {url_publica('contrato_procedimento', id=agendamento.id)}")

    mensagem = f"""Ola {agendamento.cliente}!

Seu atendimento na {NOME_CLINICA} esta agendado.

Data: {agendamento.data}
Hora: {agendamento.hora}
Procedimento: {agendamento.procedimento}
Profissional: {agendamento.profissional}

Responda esta mensagem para confirmar sua presenca.
"""

    return mensagem + "\n" + "\n".join(links)


def horario_ocupado(data, hora, profissional, ignorar_id=None):
    consulta = Agenda.query.filter_by(data=data, hora=hora, profissional=profissional).filter(Agenda.status != "cancelado")

    if ignorar_id:
        consulta = consulta.filter(Agenda.id != ignorar_id)

    return consulta.first() is not None


# ROUTES
@app.route('/')
@app.route("/home")
@login_required
def home():
    if not usuario_admin():
        return redirect(url_for('agenda'))

    hoje = date.today().strftime('%Y-%m-%d')

    total_hoje = Agenda.query.filter_by(data=hoje).count()

    total_clientes = Cliente.query.count()

    total_procedimentos = Agenda.query.count()

    faturamento = db.session.query(db.func.sum(Agenda.valor)).filter(Agenda.tipo != "bloqueio").scalar() or 0
    custo_estimado = db.session.query(db.func.sum(Agenda.custo_estimado)).filter(Agenda.tipo != "bloqueio").scalar() or 0
    lucro_estimado = faturamento - custo_estimado

    agenda_hoje = Agenda.query.filter_by(data=hoje).all()

    return render_template(
        'home.html',
        total_hoje=total_hoje,
        total_clientes=total_clientes,
        total_procedimentos=total_procedimentos,
        faturamento=faturamento,
        custo_estimado=custo_estimado,
        lucro_estimado=lucro_estimado,
        agenda_hoje=agenda_hoje,
        status_agendamento=STATUS_AGENDAMENTO
    )

@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        user = User.query.filter_by(email=email).first()

        if user and user.ativo and (senha_valida(user, senha) or senha_valida(user, senha.strip())):
            login_user(user)
            return redirect(url_for('home'))

        flash('Email ou senha inválidos')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


from datetime import datetime, timedelta, date

@app.route('/agenda')
@login_required
def agenda():
    profissionais = PROFISSIONAIS

    data_texto = request.args.get("data") or date.today().strftime("%Y-%m-%d")

    try:
        data_agenda = datetime.strptime(data_texto, "%Y-%m-%d").date()
    except ValueError:
        data_agenda = date.today()
        data_texto = data_agenda.strftime("%Y-%m-%d")

    horarios = [
        "08:00", "09:00", "10:00", "11:00",
        "12:00", "13:00", "14:00", "15:00",
        "16:00", "17:00", "18:00"
    ]

    agendamentos = Agenda.query.filter_by(data=data_texto).order_by(Agenda.hora.asc()).all()
    metricas_agenda = {
        "total": sum(1 for item in agendamentos if item.tipo != "bloqueio"),
        "confirmados": sum(1 for item in agendamentos if item.status == "confirmado" and item.tipo != "bloqueio"),
        "atendidos": sum(1 for item in agendamentos if item.status == "atendido" and item.tipo != "bloqueio"),
        "faltas": sum(1 for item in agendamentos if item.status == "faltou" and item.tipo != "bloqueio"),
        "bloqueios": sum(1 for item in agendamentos if item.tipo == "bloqueio"),
        "livres": len(profissionais) * len(horarios) - len(agendamentos),
    }
    agenda_por_profissional = {
        profissional: {horario: [] for horario in horarios}
        for profissional in profissionais
    }

    for agendamento in agendamentos:
        if agendamento.profissional not in agenda_por_profissional:
            agenda_por_profissional[agendamento.profissional] = {horario: [] for horario in horarios}

        if agendamento.hora not in agenda_por_profissional[agendamento.profissional]:
            agenda_por_profissional[agendamento.profissional][agendamento.hora] = []

        agenda_por_profissional[agendamento.profissional][agendamento.hora].append(agendamento_para_visao(agendamento))

    return render_template(
        'agenda.html',
        profissionais=profissionais,
        horarios=horarios,
        data_agenda=data_agenda,
        data_texto=data_texto,
        data_anterior=(data_agenda - timedelta(days=1)).strftime("%Y-%m-%d"),
        data_proxima=(data_agenda + timedelta(days=1)).strftime("%Y-%m-%d"),
        agenda_por_profissional=agenda_por_profissional,
        metricas_agenda=metricas_agenda,
        status_agendamento=STATUS_AGENDAMENTO,
        usuario_admin=usuario_admin()
    )


@app.route('/cancelar/<int:id>')
@login_required
def cancelar(id):

    ag = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(ag)
    if bloqueio:
        return bloqueio

    if ag.tipo == "bloqueio":
        data_retorno = ag.data
        db.session.delete(ag)
        db.session.commit()
        flash("Bloqueio removido da agenda.")
        return redirect(url_for('agenda', data=data_retorno))

    definir_status(ag, "cancelado")

    db.session.commit()

    return redirect(url_for('agenda', data=ag.data))


@app.route('/confirmar/<int:id>')
@login_required
def confirmar(id):
    ag = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(ag)
    if bloqueio:
        return bloqueio

    definir_status(ag, "confirmado")

    db.session.commit()

    return redirect(url_for('agenda', data=ag.data))


@app.route('/enviar_confirmacao/<int:id>')
@login_required
def enviar_confirmacao_agendamento(id):
    agendamento = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(agendamento)
    if bloqueio:
        return bloqueio

    mensagem = gerar_mensagem_confirmacao(agendamento)
    link = criar_link_whatsapp(agendamento.telefone, mensagem)

    cliente = Cliente.query.get(agendamento.cliente_id) if agendamento.cliente_id else localizar_cliente_agendamento(
        agendamento.cliente,
        agendamento.telefone
    )
    if cliente:
        registrar_disparo(cliente.id, "confirmacao", "Confirmacao de agenda enviada", link, mensagem)

    return redirect(link)


@app.route('/agenda/<int:id>/reagendar', methods=['POST'])
@login_required
def reagendar_agendamento(id):
    agendamento = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(agendamento)
    if bloqueio:
        return bloqueio

    nova_data = request.form.get('data')
    nova_hora = request.form.get('hora')
    profissional = request.form.get('profissional') or agendamento.profissional

    if not nova_data or not nova_hora:
        flash("Informe data e horario para reagendar.")
        return redirect(url_for('agenda', data=agendamento.data))

    if horario_ocupado(nova_data, nova_hora, profissional, ignorar_id=agendamento.id):
        flash("Este horario ja esta ocupado para essa profissional.")
        return redirect(url_for('agenda', data=agendamento.data))

    agendamento.data = nova_data
    agendamento.hora = nova_hora
    agendamento.profissional = profissional
    agendamento.status = "agendado"

    db.session.commit()
    flash("Agendamento reagendado. Envie a nova confirmacao pelo WhatsApp.")
    return redirect(url_for('agenda', data=nova_data))


@app.route('/atendido/<int:id>')
@login_required
def atendido(id):

    ag = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(ag)
    if bloqueio:
        return bloqueio

    ja_atendido = ag.status == "atendido"

    definir_status(ag, "atendido")

    cliente = Cliente.query.get(ag.cliente_id) if ag.cliente_id else localizar_cliente_agendamento(ag.cliente, ag.telefone)
    if cliente:
        ag.cliente_id = cliente.id
        cliente.ultima_visita = data_agendamento_para_date(ag.data) or cliente.ultima_visita

    if not ja_atendido:
        registro = Financeiro(
            data=ag.data,
            cliente=ag.cliente,
            procedimento=ag.procedimento,
            valor=ag.valor or 0,
            tipo="entrada",
            forma_pagamento=ag.pagamento
        )
        db.session.add(registro)

    db.session.commit()

    return redirect(url_for('agenda', data=ag.data))

@app.route('/faltou/<int:id>')
@login_required
def faltou(id):

    ag = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(ag)
    if bloqueio:
        return bloqueio

    definir_status(ag, "faltou")

    db.session.commit()

    return redirect(url_for('agenda', data=ag.data))


@app.route('/agenda/<int:id>/observacoes', methods=['POST'])
@login_required
def salvar_observacoes_agendamento(id):
    agendamento = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(agendamento)
    if bloqueio:
        return bloqueio

    agendamento.observacoes = request.form.get('observacoes')

    cliente = Cliente.query.get(agendamento.cliente_id) if agendamento.cliente_id else localizar_cliente_agendamento(
        agendamento.cliente,
        agendamento.telefone
    )
    if cliente:
        agendamento.cliente_id = cliente.id

    db.session.commit()
    flash("Observacoes do atendimento salvas.")
    return redirect(url_for('agenda', data=agendamento.data))


import urllib.parse

@app.route('/novo_agendamento', methods=['GET', 'POST'])
@login_required
def novo_agendamento():

    data_selecionada = request.args.get('data')
    hora_selecionada = request.args.get('hora')
    profissional_selecionada = request.args.get('profissional')
    profissionais = PROFISSIONAIS if usuario_admin() else [current_user.profissional]
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.categoria.asc(),
        ProcedimentoCatalogo.nome.asc()
    ).all()
    custos_reais = {
        item.id: calcular_custo_real_procedimento(item.id)
        for item in procedimentos
    }

    if not usuario_admin() and profissional_selecionada != current_user.profissional:
        profissional_selecionada = current_user.profissional

    if request.method == 'POST':

        data = request.form['data']
        hora = request.form['hora']
        profissional = request.form['profissional'] if usuario_admin() else current_user.profissional
        procedimento_catalogo = None
        procedimento_id = request.form.get('procedimento_id')
        if procedimento_id:
            procedimento_catalogo = ProcedimentoCatalogo.query.get(procedimento_id)
        custo_real = calcular_custo_real_procedimento(procedimento_catalogo.id) if procedimento_catalogo else 0

        if horario_ocupado(data, hora, profissional):

            flash("⚠️ Este horário já está ocupado para essa profissional.")

            return redirect(url_for('novo_agendamento', data=data, hora=hora, profissional=profissional))

        cliente_cadastro = localizar_cliente_agendamento(request.form['cliente'], request.form['telefone'])
        if not cliente_cadastro:
            cliente_cadastro = Cliente(nome=request.form['cliente'], telefone=request.form['telefone'])
            db.session.add(cliente_cadastro)
            db.session.flush()

        novo = Agenda(
            cliente_id=cliente_cadastro.id,
            telefone=request.form['telefone'],
            data=request.form['data'],
            hora=request.form['hora'],
            cliente=request.form['cliente'],
            profissional=profissional,
            procedimento=request.form.get('procedimento') or (procedimento_catalogo.nome if procedimento_catalogo else ""),
            procedimento_id=procedimento_catalogo.id if procedimento_catalogo else None,
            valor=float(request.form.get('valor') or (procedimento_catalogo.valor_padrao if procedimento_catalogo else 0) or 0),
            custo_estimado=float(request.form.get('custo_estimado') or custo_real or (procedimento_catalogo.custo_estimado if procedimento_catalogo else 0) or 0),
            duracao_minutos=int(request.form.get('duracao_minutos') or (procedimento_catalogo.duracao_minutos if procedimento_catalogo else 60) or 60),
            retorno_dias=int(request.form.get('retorno_dias') or procedimento_catalogo.retorno_dias or 0) if (request.form.get('retorno_dias') or (procedimento_catalogo and procedimento_catalogo.retorno_dias)) else None,
            pagamento=request.form['pagamento'],
            status="agendado",
            observacoes=request.form.get('observacoes'),
            tipo="atendimento",
            criado_por_id=current_user.id
        )

        db.session.add(novo)
        db.session.commit()

        # ===== WHATSAPP =====

        mensagem = gerar_mensagem_confirmacao(novo)
        texto = urllib.parse.quote(mensagem)

        telefone = novo.telefone.strip().replace(" ", "").replace("-", "")

        link = f"https://wa.me/55{telefone}?text={texto}"

        return redirect(link)

    return render_template(
        "novo_agendamento.html",
        data=data_selecionada,
        hora=hora_selecionada,
        profissional=profissional_selecionada,
        profissionais=profissionais,
        procedimentos=procedimentos,
        custos_reais=custos_reais
    )


@app.route('/novo_bloqueio', methods=['GET', 'POST'])
@login_required
def novo_bloqueio():
    data_selecionada = request.args.get('data')
    hora_selecionada = request.args.get('hora')
    profissional_selecionada = request.args.get('profissional')
    profissionais = PROFISSIONAIS if usuario_admin() else [current_user.profissional]

    if not usuario_admin() and profissional_selecionada != current_user.profissional:
        profissional_selecionada = current_user.profissional

    if request.method == 'POST':
        data = request.form['data']
        hora = request.form['hora']
        profissional = request.form['profissional'] if usuario_admin() else current_user.profissional

        if horario_ocupado(data, hora, profissional):
            flash("Este horario ja esta ocupado para essa profissional.")
            return redirect(url_for('novo_bloqueio', data=data, hora=hora, profissional=profissional))

        bloqueio = Agenda(
            data=data,
            hora=hora,
            profissional=profissional,
            procedimento=request.form.get('motivo') or "Horario bloqueado",
            status="bloqueado",
            observacoes=request.form.get('observacoes'),
            tipo="bloqueio",
            criado_por_id=current_user.id
        )

        db.session.add(bloqueio)
        db.session.commit()

        flash("Horario bloqueado na agenda.")
        return redirect(url_for('agenda', data=data))

    return render_template(
        "novo_bloqueio.html",
        data=data_selecionada,
        hora=hora_selecionada,
        profissional=profissional_selecionada,
        profissionais=profissionais
    )

@app.route('/clientes')
@login_required
@admin_required
def clientes():
    lista = Cliente.query.order_by(Cliente.nome.asc()).all()
    return render_template('clientes.html', clientes=lista)


@app.route('/anamnese', methods=['GET', 'POST'])
@login_required
@admin_required
def anamnese():
    clientes = Cliente.query.all()

    if request.method == 'POST':
        nova = Anamnese(
            cliente_id=request.form['cliente_id'],
            doencas=request.form.get('doencas'),
            medicamentos=request.form.get('medicamentos'),
            alergias=request.form.get('alergias'),
            procedimentos_anteriores=request.form.get('procedimentos'),
            tipo_pele=request.form.get('tipo_pele'),
            sensibilidade=request.form.get('sensibilidade'),
            avaliacao=request.form.get('avaliacao'),
            plano_tratamento=request.form.get('plano')
        )

        db.session.add(nova)
        db.session.commit()

        flash("Anamnese salva")

        return redirect(url_for('anamnese'))

    return render_template('anamnese.html', clientes=clientes)

@app.route('/anamneses')
@login_required
@admin_required
def lista_anamneses():

    anamneses = Anamnese.query.all()
    clientes = {cliente.id: cliente for cliente in Cliente.query.all()}

    return render_template("lista_anamnese.html", lista=anamneses, clientes=clientes)

@app.route('/anamnese/<int:id>')
@login_required
@admin_required
def ver_anamnese(id):

    anamnese = Anamnese.query.get_or_404(id)

    cliente = Cliente.query.get(anamnese.cliente_id)

    return render_template("ver_anamnese.html", anamnese=anamnese, cliente=cliente)


@app.route('/cliente/<int:id>/anamnese', methods=['GET', 'POST'])
def anamnese_cliente_publica(id):
    cliente = Cliente.query.get_or_404(id)

    if request.method == 'POST':
        cliente.idade = request.form.get('idade') or cliente.idade
        cliente.sexo = request.form.get('sexo') or cliente.sexo
        cliente.observacao = request.form.get('observacoes') or cliente.observacao

        nova = Anamnese(
            cliente_id=cliente.id,
            doencas=request.form.get('doenca'),
            medicamentos=request.form.get('medicacao'),
            alergias=request.form.get('alergias'),
            procedimentos_anteriores=request.form.get('procedimento'),
            avaliacao=request.form.get('observacoes')
        )

        db.session.add(nova)
        db.session.commit()

        return render_template('obrigado.html')

    return render_template('anamnese_cliente.html', cliente=cliente)


@app.route('/enviar_anamnese/<int:id>')
@login_required
@admin_required
def enviar_anamnese_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    link_formulario = url_publica('anamnese_cliente_publica', id=cliente.id)
    mensagem = f"""Ola, {cliente.nome}!

Antes do seu atendimento na Parvati Estetica, preencha sua anamnese pelo link:
{link_formulario}

Obrigada."""
    link = criar_link_whatsapp(cliente.telefone, mensagem)
    registrar_disparo(cliente.id, "anamnese", "Link de anamnese enviado", link, mensagem)
    return redirect(link)


@app.route('/contrato/<int:id>')
def contrato_procedimento(id):
    agendamento = Agenda.query.get_or_404(id)
    return render_template('contrato.html', agendamento=agendamento)


@app.route('/enviar_contrato/<int:id>')
@login_required
def enviar_contrato_cliente(id):
    agendamento = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(agendamento)
    if bloqueio:
        return bloqueio

    cliente = Cliente.query.filter_by(nome=agendamento.cliente).first()
    link_contrato = url_publica('contrato_procedimento', id=agendamento.id)
    mensagem = f"""Ola, {agendamento.cliente}!

Segue o contrato/termo do procedimento {agendamento.procedimento}:
{link_contrato}

Leia com atencao antes do atendimento."""
    link = criar_link_whatsapp(agendamento.telefone, mensagem)

    if cliente:
        registrar_disparo(cliente.id, "contrato", "Contrato de procedimento enviado", link, mensagem)

    return redirect(link)


@app.route('/novo_cliente', methods=['GET', 'POST'])
@login_required
@admin_required
def novo_cliente():

    if request.method == 'POST':

        from datetime import datetime

        nascimento_texto = request.form['nascimento'] or None
        aniversario = datetime.strptime(
            request.form['nascimento'],
            "%Y-%m-%d"
        ).date() if request.form['nascimento'] else None

        cliente = Cliente(
            nome=request.form['nome'],
            telefone=request.form['telefone'],
            email=request.form['email'],
            observacao=request.form['observacao'],
            nascimento=nascimento_texto,
            aniversario=aniversario
        )

        db.session.add(cliente)
        db.session.commit()

        flash("Cliente cadastrado")

        return redirect(url_for('clientes'))

    return render_template('novo_cliente.html')

@app.route('/buscar_cliente')
@login_required
@admin_required
def buscar_cliente():
    termo = request.args.get('q', '')

    clientes = Cliente.query.filter(Cliente.nome.contains(termo)).order_by(Cliente.nome.asc()).all()


    return render_template('clientes.html', clientes=clientes)


@app.route('/funcionarias', methods=['GET', 'POST'])
@login_required
@admin_required
def funcionarias():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '').strip()

        if user_id:
            funcionaria = User.query.get_or_404(user_id)
        else:
            if User.query.filter_by(email=email).first():
                flash("Ja existe uma funcionaria com este e-mail.")
                return redirect(url_for('funcionarias'))

            funcionaria = User()
            db.session.add(funcionaria)

        funcionaria.nome = request.form.get('nome', '').strip()
        funcionaria.email = email
        funcionaria.profissional = request.form.get('profissional')
        funcionaria.perfil = request.form.get('perfil') if usuario_admin() else "profissional"
        funcionaria.ativo = request.form.get('ativo') == "on"

        if senha:
            if not senha_forte(senha):
                flash("A senha precisa ter pelo menos 8 caracteres.")
                return redirect(url_for('funcionarias'))
            funcionaria.senha = generate_password_hash(senha)

        if not funcionaria.senha:
            funcionaria.senha = generate_password_hash("Parvati@2026")

        db.session.commit()
        flash("Funcionaria salva.")
        return redirect(url_for('funcionarias'))

    usuarios = User.query.order_by(User.nome.asc()).all()
    return render_template(
        "funcionarias.html",
        usuarios=usuarios,
        profissionais=PROFISSIONAIS
    )


@app.route('/minha_senha', methods=['GET', 'POST'])
@login_required
def minha_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '')
        nova_senha = request.form.get('nova_senha', '')
        confirmar_senha = request.form.get('confirmar_senha', '')

        if not senha_valida(current_user, senha_atual):
            flash("Senha atual incorreta.")
            return redirect(url_for('minha_senha'))

        if nova_senha != confirmar_senha:
            flash("A confirmacao da nova senha nao confere.")
            return redirect(url_for('minha_senha'))

        if not senha_forte(nova_senha):
            flash("A nova senha precisa ter pelo menos 8 caracteres.")
            return redirect(url_for('minha_senha'))

        current_user.senha = generate_password_hash(nova_senha)
        db.session.commit()
        flash("Senha alterada com sucesso.")
        return redirect(url_for('agenda'))

    return render_template("minha_senha.html")


@app.route('/procedimentos', methods=['GET', 'POST'])
@login_required
@admin_required
def procedimentos():
    if request.method == 'POST':
        procedimento = ProcedimentoCatalogo(
            nome=request.form.get('nome'),
            categoria=request.form.get('categoria'),
            duracao_minutos=int(request.form.get('duracao_minutos') or 60),
            valor_padrao=float(request.form.get('valor_padrao') or 0),
            custo_estimado=float(request.form.get('custo_estimado') or 0),
            retorno_dias=int(request.form.get('retorno_dias') or 0) or None,
            orientacoes=request.form.get('orientacoes'),
            ativo=True
        )
        db.session.add(procedimento)
        db.session.commit()
        flash("Procedimento cadastrado.")
        return redirect(url_for('procedimentos'))

    lista = ProcedimentoCatalogo.query.order_by(
        ProcedimentoCatalogo.ativo.desc(),
        ProcedimentoCatalogo.categoria.asc(),
        ProcedimentoCatalogo.nome.asc()
    ).all()
    custos_reais = {
        item.id: calcular_custo_real_procedimento(item.id)
        for item in lista
    }
    return render_template("procedimentos.html", procedimentos=lista, custos_reais=custos_reais)


@app.route('/procedimentos/<int:id>/calculadora', methods=['GET', 'POST'])
@login_required
@admin_required
def calculadora_procedimento(id):
    procedimento = ProcedimentoCatalogo.query.get_or_404(id)

    if request.method == 'POST':
        produto = ProdutoEstoque.query.get_or_404(request.form.get('produto_id'))
        quantidade = float(request.form.get('quantidade') or 0)

        if quantidade <= 0:
            flash("Informe uma quantidade valida.")
            return redirect(url_for('calculadora_procedimento', id=id))

        insumo = ProcedimentoInsumo(
            procedimento_id=procedimento.id,
            produto_id=produto.id,
            quantidade=quantidade,
            custo_unitario_snapshot=produto.custo_unitario or 0,
            observacao=request.form.get('observacao')
        )
        db.session.add(insumo)
        db.session.commit()

        procedimento.custo_estimado = calcular_custo_real_procedimento(procedimento.id)
        db.session.commit()

        flash("Insumo adicionado ao calculo.")
        return redirect(url_for('calculadora_procedimento', id=id))

    insumos = ProcedimentoInsumo.query.filter_by(procedimento_id=procedimento.id).order_by(ProcedimentoInsumo.id.desc()).all()
    produtos = ProdutoEstoque.query.filter_by(ativo=True).order_by(ProdutoEstoque.categoria.asc(), ProdutoEstoque.nome.asc()).all()
    produtos_por_id = {produto.id: produto for produto in produtos}
    total = calcular_custo_real_procedimento(procedimento.id)

    return render_template(
        "calculadora_procedimento.html",
        procedimento=procedimento,
        insumos=insumos,
        produtos=produtos,
        produtos_por_id=produtos_por_id,
        total=total,
        lucro=(procedimento.valor_padrao or 0) - total
    )


@app.route('/procedimentos/<int:procedimento_id>/calculadora/<int:insumo_id>/remover')
@login_required
@admin_required
def remover_insumo_procedimento(procedimento_id, insumo_id):
    insumo = ProcedimentoInsumo.query.get_or_404(insumo_id)
    if insumo.procedimento_id != procedimento_id:
        flash("Insumo nao pertence a este procedimento.")
        return redirect(url_for('calculadora_procedimento', id=procedimento_id))

    db.session.delete(insumo)
    db.session.commit()

    procedimento = ProcedimentoCatalogo.query.get_or_404(procedimento_id)
    procedimento.custo_estimado = calcular_custo_real_procedimento(procedimento.id)
    db.session.commit()

    flash("Insumo removido do calculo.")
    return redirect(url_for('calculadora_procedimento', id=procedimento_id))


@app.route('/procedimentos/<int:id>/desativar')
@login_required
@admin_required
def desativar_procedimento(id):
    procedimento = ProcedimentoCatalogo.query.get_or_404(id)
    procedimento.ativo = False
    db.session.commit()
    flash("Procedimento desativado.")
    return redirect(url_for('procedimentos'))


@app.route('/estoque', methods=['GET', 'POST'])
@login_required
@admin_required
def estoque():
    if request.method == 'POST':
        produto = ProdutoEstoque(
            nome=request.form['nome'],
            categoria=request.form['categoria'],
            marca=request.form.get('marca'),
            lote=request.form.get('lote'),
            custo_unitario=float(request.form.get('custo_unitario') or 0),
            unidade=request.form.get('unidade') or 'unidade',
            quantidade=float(request.form.get('quantidade') or 0),
            estoque_minimo=float(request.form.get('estoque_minimo') or 0),
            validade=request.form.get('validade'),
            fornecedor=request.form.get('fornecedor'),
            registro_anvisa=request.form.get('registro_anvisa'),
            local_armazenamento=request.form.get('local_armazenamento'),
            observacao=request.form.get('observacao'),
            ativo=True
        )
        db.session.add(produto)
        db.session.commit()
        flash("Produto cadastrado no estoque.")
        return redirect(url_for('estoque'))

    busca = request.args.get('q', '').strip()
    categoria = request.args.get('categoria', '').strip()
    status = request.args.get('status', '').strip()

    query = ProdutoEstoque.query.filter_by(ativo=True)

    if busca:
        query = query.filter(ProdutoEstoque.nome.contains(busca))

    if categoria:
        query = query.filter_by(categoria=categoria)

    produtos = query.order_by(ProdutoEstoque.categoria.asc(), ProdutoEstoque.nome.asc()).all()

    if status == "baixo":
        produtos = [p for p in produtos if (p.quantidade or 0) <= (p.estoque_minimo or 0)]

    categorias = [
        item[0]
        for item in db.session.query(ProdutoEstoque.categoria)
        .filter_by(ativo=True)
        .distinct()
        .order_by(ProdutoEstoque.categoria.asc())
        .all()
    ]

    total_produtos = len(produtos)
    baixo_estoque = sum(1 for p in produtos if (p.quantidade or 0) <= (p.estoque_minimo or 0))
    vencendo = sum(1 for p in produtos if p.validade and p.validade <= (date.today() + timedelta(days=30)).strftime("%Y-%m-%d"))
    movimentacoes = MovimentacaoEstoque.query.order_by(MovimentacaoEstoque.id.desc()).limit(12).all()

    return render_template(
        'estoque.html',
        produtos=produtos,
        categorias=categorias,
        busca=busca,
        categoria_selecionada=categoria,
        status=status,
        total_produtos=total_produtos,
        baixo_estoque=baixo_estoque,
        vencendo=vencendo,
        movimentacoes=movimentacoes
    )


@app.route('/estoque/<int:id>/movimentar', methods=['POST'])
@login_required
@admin_required
def movimentar_estoque(id):
    produto = ProdutoEstoque.query.get_or_404(id)
    tipo = request.form.get('tipo')
    quantidade = float(request.form.get('quantidade') or 0)
    motivo = request.form.get('motivo')

    if quantidade <= 0 or tipo not in ["entrada", "saida"]:
        flash("Informe uma quantidade valida.")
        return redirect(url_for('estoque'))

    if tipo == "entrada":
        produto.quantidade = (produto.quantidade or 0) + quantidade
    else:
        produto.quantidade = max((produto.quantidade or 0) - quantidade, 0)

    movimentacao = MovimentacaoEstoque(
        produto_id=produto.id,
        tipo=tipo,
        quantidade=quantidade,
        motivo=motivo
    )
    db.session.add(movimentacao)
    db.session.commit()

    flash("Estoque atualizado.")
    return redirect(url_for('estoque'))


@app.route('/estoque/<int:id>/desativar')
@login_required
@admin_required
def desativar_produto(id):
    produto = ProdutoEstoque.query.get_or_404(id)
    produto.ativo = False
    db.session.commit()
    flash("Produto removido da lista ativa.")
    return redirect(url_for('estoque'))



@app.route('/cliente/<int:id>/historico')
@login_required
@admin_required
def historico(id):

    cliente = Cliente.query.get_or_404(id)
    agendamentos = query_atendimentos_cliente(cliente).all()
    anamneses = Anamnese.query.filter_by(cliente_id=cliente.id).order_by(Anamnese.data.desc()).all()

    return render_template(
        'historico.html',
        agendamentos=agendamentos,
        cliente=cliente,
        anamneses=anamneses,
        status_agendamento=STATUS_AGENDAMENTO
    )


@app.route('/historico/<nome>')
@login_required
@admin_required
def historico_por_nome(nome):
    cliente = Cliente.query.filter_by(nome=nome).first()
    if cliente:
        return redirect(url_for('historico', id=cliente.id))

    flash("Cliente nao encontrado para abrir o historico.")
    return redirect(url_for('clientes'))

@app.route('/disparar_aniversario')
@login_required
@admin_required
def disparar_aniversario():

    hoje = datetime.today().strftime("%m-%d")

    clientes = Cliente.query.all()

    aniversariantes = []

    for c in clientes:

        if c.aniversario:

            if c.aniversario.strftime("%m-%d") == hoje:

                mensagem = f"""
Feliz aniversário {c.nome}! 🎉

A Parvati Estetica deseja um dia maravilhoso.

Temos um presente especial para você ✨
"""

                texto = urllib.parse.quote(mensagem)

                telefone = c.telefone.replace(" ", "").replace("-", "")

                link = f"https://wa.me/55{telefone}?text={texto}"

                aniversariantes.append(link)

    return render_template(
        "aniversarios.html",
        links=aniversariantes
    )

@app.route('/eventos')
@login_required
def eventos():

    agendamentos = Agenda.query.all()

    eventos = []

    for a in agendamentos:
        item = agendamento_para_visao(a)

        cor = CORES_PROFISSIONAIS.get(
            a.profissional,
            "#B22222"  # cor padrão
        )

        eventos.append({
            "title": f"{item.visivel_procedimento} - {item.visivel_cliente}",
            "start": f"{a.data}T{a.hora}",
            "color": cor
        })

    return jsonify(eventos)


# MAIN
if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        # VERIFICAR SE JÁ EXISTE ADMIN
        admin = User.query.filter_by(email='naiara@espacoparvati.com').first()

        if not admin:
            admin = User(
                nome='Naiara Massera',
                email='naiara@espacoparvati.com',
                senha='Parvati@2026'
            )
            db.session.add(admin)
            db.session.commit()
            print('✅ Admin Naiara criado com sucesso!')

    app.run(debug=True)


@app.route('/financeiro', methods=['GET', 'POST'])
@login_required
@admin_required
def financeiro():
    financeiros = Financeiro.query.order_by(Financeiro.data.desc()).all()

    entradas = sum((f.valor or 0) for f in financeiros if f.tipo == "entrada")
    saidas = sum((f.valor or 0) for f in financeiros if f.tipo == "saida")
    saldo = entradas - saidas
    custo_atendimentos = db.session.query(db.func.sum(Agenda.custo_estimado)).filter(Agenda.tipo != "bloqueio").scalar() or 0
    lucro_estimado = entradas - saidas - custo_atendimentos


    if request.method == 'POST':
        novo = Financeiro(

            cliente=request.form['cliente'],
            procedimento=request.form['procedimento'],
            valor=float(request.form.get('valor') or 0),
            tipo=request.form.get('tipo', 'entrada'),
            forma_pagamento=request.form['forma_pagamento'],
            data=request.form['data'],
            vencimento=request.form.get('vencimento'),
            boleto_status=request.form.get('boleto_status', 'nao_gerado'),
            boleto_link=request.form.get('boleto_link'),
            linha_digitavel=request.form.get('linha_digitavel'),
            integracao_boleto=request.form.get('integracao_boleto', 'manual')
        )

        db.session.add(novo)
        db.session.commit()

        flash("Pagamento registrado")

        return redirect(url_for('financeiro'))

    pagamentos = Financeiro.query.all()

    return render_template(
        'financeiro.html',
        financeiros=financeiros,
        entradas=entradas,
        saidas=saidas,
        saldo=saldo,
        custo_atendimentos=custo_atendimentos,
        lucro_estimado=lucro_estimado,
        total_mes=entradas,
        entradas_hoje=entradas,
        saidas_hoje=saidas,
        pagamentos=pagamentos
    )


@app.route('/financeiro/boleto/<int:id>')
@login_required
@admin_required
def gerar_boleto(id):
    financeiro = Financeiro.query.get_or_404(id)

    financeiro.boleto_status = "pronto_para_integracao"
    financeiro.integracao_boleto = financeiro.integracao_boleto or "manual"
    financeiro.nosso_numero = financeiro.nosso_numero or f"PARVATI{id:06d}"
    financeiro.linha_digitavel = financeiro.linha_digitavel or gerar_linha_digitavel_simulada(financeiro)
    financeiro.boleto_link = financeiro.boleto_link or url_publica('boleto_cliente', id=financeiro.id)

    db.session.commit()
    flash("Boleto preparado para integracao. Confira link e linha digitavel.")
    return redirect(url_for('financeiro'))


@app.route('/boleto/<int:id>')
def boleto_cliente(id):
    financeiro = Financeiro.query.get_or_404(id)
    return render_template('boleto_cliente.html', financeiro=financeiro)


@app.route('/financeiro/boletos/json')
@login_required
@admin_required
def boletos_json():
    financeiros = Financeiro.query.filter(Financeiro.forma_pagamento.contains("Boleto")).all()

    return jsonify([
        {
            "id": item.id,
            "cliente": item.cliente,
            "procedimento": item.procedimento,
            "valor": item.valor,
            "vencimento": item.vencimento,
            "status": item.boleto_status,
            "linha_digitavel": item.linha_digitavel,
            "boleto_link": item.boleto_link,
            "integracao": item.integracao_boleto,
        }
        for item in financeiros
    ])

@app.route('/prontuario/<int:id>')
@login_required
@admin_required
def prontuario(id):
    cliente = Cliente.query.get_or_404(id)
    anamnese = Anamnese.query.filter_by(cliente_id=id).order_by(Anamnese.id.desc()).first()
    historico = query_atendimentos_cliente(cliente).all()

    fotos = FotoEvolucao.query.filter_by(cliente_id=id).order_by(FotoEvolucao.id.desc()).all()
    foto_antes = next((foto for foto in fotos if (foto.descricao or "").lower() == "antes"), None)
    foto_depois = next((foto for foto in fotos if (foto.descricao or "").lower() == "depois"), None)

    return render_template(
        'prontuario.html',
        cliente=cliente,
        anamnese=anamnese,
        historico=historico,
        fotos=fotos,
        foto_antes=foto_antes,
        foto_depois=foto_depois,
        status_agendamento=STATUS_AGENDAMENTO
    )

@app.route('/dashboard')
@login_required
@admin_required
def dashboard():

    total_clientes = Cliente.query.count()

    total_agendamentos = Agenda.query.count()

    faturamento = db.session.query(db.func.sum(Agenda.valor)).filter(Agenda.tipo != "bloqueio").scalar() or 0
    custo_estimado = db.session.query(db.func.sum(Agenda.custo_estimado)).filter(Agenda.tipo != "bloqueio").scalar() or 0

    return render_template(
        "dashbord.html",
        clientes=total_clientes,
        agendamentos=total_agendamentos,
        faturamento=faturamento,
        custo_estimado=custo_estimado,
        lucro_estimado=faturamento - custo_estimado
    )


def cliente_com_ultima_visita(cliente):
    atendimentos = query_atendimentos_cliente(cliente).all()
    datas_validas = [
        data_agendamento_para_date(item.data)
        for item in atendimentos
        if data_agendamento_para_date(item.data)
    ]

    ultima_visita = cliente.ultima_visita
    if datas_validas:
        ultima_visita = max(datas_validas)

    return cliente, ultima_visita, atendimentos


@app.route('/central-ia')
@login_required
@admin_required
def central_ia():
    hoje = date.today()
    hoje_texto = hoje.strftime("%Y-%m-%d")
    inicio_mes = hoje.replace(day=1).strftime("%Y-%m-%d")

    agendamentos = Agenda.query.filter(Agenda.tipo != "bloqueio").all()
    agenda_hoje = [item for item in agendamentos if item.data == hoje_texto]
    proximos_agendamentos = [
        item for item in agendamentos
        if item.data and hoje_texto <= item.data <= (hoje + timedelta(days=7)).strftime("%Y-%m-%d")
    ]
    faltas_recentes = [
        item for item in agendamentos
        if item.status == "faltou" and item.data and item.data >= (hoje - timedelta(days=30)).strftime("%Y-%m-%d")
    ]
    cancelamentos_recentes = [
        item for item in agendamentos
        if item.status == "cancelado" and item.data and item.data >= (hoje - timedelta(days=30)).strftime("%Y-%m-%d")
    ]
    confirmacoes_pendentes = [
        item for item in proximos_agendamentos
        if item.status == "agendado"
    ]

    retornos = []
    for item in agendamentos:
        data_atendimento = data_agendamento_para_date(item.data)
        if item.status == "atendido" and item.retorno_dias and data_atendimento:
            data_retorno = data_atendimento + timedelta(days=item.retorno_dias)
            if hoje - timedelta(days=7) <= data_retorno <= hoje + timedelta(days=14):
                cliente = Cliente.query.get(item.cliente_id) if item.cliente_id else localizar_cliente_agendamento(
                    item.cliente,
                    item.telefone
                )
                retornos.append({
                    "cliente": cliente,
                    "agendamento": item,
                    "data_retorno": data_retorno,
                    "dias": (data_retorno - hoje).days,
                    "whatsapp": criar_link_whatsapp(
                        item.telefone,
                        f"Ola {item.cliente}! Ja esta no periodo ideal para seu retorno de {item.procedimento}. Quer que eu veja um horario para voce?"
                    )
                })

    clientes_inativos = []
    clientes_sem_agenda = []
    for cliente in Cliente.query.order_by(Cliente.nome.asc()).all():
        cliente, ultima_visita, atendimentos = cliente_com_ultima_visita(cliente)
        tem_agenda_futura = any(
            item.data and item.data >= hoje_texto and item.status not in ["cancelado", "faltou"]
            for item in atendimentos
        )

        if not tem_agenda_futura:
            clientes_sem_agenda.append(cliente)

        if ultima_visita and (hoje - ultima_visita).days >= 90 and not tem_agenda_futura:
            clientes_inativos.append({
                "cliente": cliente,
                "ultima_visita": ultima_visita,
                "dias": (hoje - ultima_visita).days,
                "whatsapp": criar_link_whatsapp(
                    cliente.telefone,
                    f"Ola {cliente.nome}! Sentimos sua falta na Parvati Estetica. Posso te mostrar alguns horarios para uma avaliacao ou retorno?"
                )
            })

    receita_mes = db.session.query(db.func.sum(Agenda.valor)).filter(
        Agenda.tipo != "bloqueio",
        Agenda.status == "atendido",
        Agenda.data >= inicio_mes
    ).scalar() or 0
    custo_mes = db.session.query(db.func.sum(Agenda.custo_estimado)).filter(
        Agenda.tipo != "bloqueio",
        Agenda.status == "atendido",
        Agenda.data >= inicio_mes
    ).scalar() or 0
    ticket_medio = receita_mes / max(1, len([item for item in agendamentos if item.status == "atendido" and item.data >= inicio_mes]))

    tarefas_crc = [
        {
            "titulo": "Confirmar agenda dos proximos 7 dias",
            "quantidade": len(confirmacoes_pendentes),
            "acao": "Abrir agenda",
            "url": url_for("agenda")
        },
        {
            "titulo": "Reativar clientes inativos",
            "quantidade": len(clientes_inativos),
            "acao": "Abrir campanhas",
            "url": url_for("campanhas")
        },
        {
            "titulo": "Resgatar faltas e cancelamentos recentes",
            "quantidade": len(faltas_recentes) + len(cancelamentos_recentes),
            "acao": "Ver oportunidades",
            "url": url_for("central_ia") + "#oportunidades"
        },
        {
            "titulo": "Agendar retornos previstos",
            "quantidade": len(retornos),
            "acao": "Ver retornos",
            "url": url_for("central_ia") + "#retornos"
        }
    ]

    insights = [
        "Use WhatsApp para confirmar horarios, reduzir faltas e acelerar reagendamentos.",
        "Priorize retornos e inativos antes de campanhas gerais: sao contatos com maior contexto e chance de conversao.",
        "Registre antes/depois no prontuario para transformar proposta estetica em uma conversa visual.",
        "Acompanhe ticket medio, lucro estimado e ocupacao para decidir promocoes com margem."
    ]

    mensagens_ia = [
        {
            "titulo": "Confirmacao de agenda",
            "texto": "Ola {nome}! Passando para confirmar seu horario na Parvati Estetica em {data} as {hora}. Pode responder SIM para confirmar?"
        },
        {
            "titulo": "Retorno de procedimento",
            "texto": "Ola {nome}! Ja esta no periodo ideal para avaliarmos seu resultado e planejarmos o proximo cuidado. Quer que eu veja um horario?"
        },
        {
            "titulo": "Cliente inativo",
            "texto": "Ola {nome}! Sentimos sua falta por aqui. A Parvati Estetica separou alguns horarios para avaliacao ou retorno. Posso te enviar as opcoes?"
        },
        {
            "titulo": "Orcamento pendente",
            "texto": "Ola {nome}! Ficou alguma duvida sobre o tratamento que conversamos? Posso te ajudar a escolher a melhor forma de iniciar."
        }
    ]

    return render_template(
        "central_ia.html",
        agenda_hoje=agenda_hoje,
        proximos_agendamentos=proximos_agendamentos,
        confirmacoes_pendentes=confirmacoes_pendentes[:10],
        faltas_recentes=faltas_recentes[:10],
        cancelamentos_recentes=cancelamentos_recentes[:10],
        retornos=retornos[:12],
        clientes_inativos=clientes_inativos[:12],
        clientes_sem_agenda=len(clientes_sem_agenda),
        receita_mes=receita_mes,
        custo_mes=custo_mes,
        lucro_mes=receita_mes - custo_mes,
        ticket_medio=ticket_medio,
        tarefas_crc=tarefas_crc,
        insights=insights,
        mensagens_ia=mensagens_ia,
        status_agendamento=STATUS_AGENDAMENTO
    )


def centavos_para_reais(valor):
    return (valor or 0) / 100


def reais_para_centavos(valor):
    texto = str(valor or "0").strip()
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return max(0, int(round(float(texto) * 100)))
    except ValueError:
        return 0


def contexto_marketing_ia():
    hoje = date.today()
    hoje_texto = hoje.strftime("%Y-%m-%d")
    inicio_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
    agendamentos = Agenda.query.filter(Agenda.tipo != "bloqueio").all()

    retornos = []
    for item in agendamentos:
        data_atendimento = data_agendamento_para_date(item.data)
        if item.status == "atendido" and item.retorno_dias and data_atendimento:
            data_retorno = data_atendimento + timedelta(days=item.retorno_dias)
            if hoje - timedelta(days=7) <= data_retorno <= hoje + timedelta(days=14):
                retornos.append({
                    "agendamento": item,
                    "data_retorno": data_retorno,
                    "dias": (data_retorno - hoje).days,
                })

    clientes_inativos = []
    clientes_sem_agenda = 0
    for cliente in Cliente.query.order_by(Cliente.nome.asc()).all():
        cliente, ultima_visita, atendimentos = cliente_com_ultima_visita(cliente)
        tem_agenda_futura = any(
            item.data and item.data >= hoje_texto and item.status not in ["cancelado", "faltou"]
            for item in atendimentos
        )
        if not tem_agenda_futura:
            clientes_sem_agenda += 1
        if ultima_visita and (hoje - ultima_visita).days >= 90 and not tem_agenda_futura:
            clientes_inativos.append({
                "cliente": cliente,
                "ultima_visita": ultima_visita,
                "dias": (hoje - ultima_visita).days,
            })

    receita_mes = db.session.query(db.func.sum(Agenda.valor)).filter(
        Agenda.tipo != "bloqueio",
        Agenda.status == "atendido",
        Agenda.data >= inicio_mes
    ).scalar() or 0
    custo_mes = db.session.query(db.func.sum(Agenda.custo_estimado)).filter(
        Agenda.tipo != "bloqueio",
        Agenda.status == "atendido",
        Agenda.data >= inicio_mes
    ).scalar() or 0
    atendidos_mes = len([
        item for item in agendamentos
        if item.status == "atendido" and item.data and item.data >= inicio_mes
    ])

    metricas = {
        "receita_mes": receita_mes,
        "lucro_estimado": receita_mes - custo_mes,
        "ticket_medio": receita_mes / max(1, atendidos_mes),
        "clientes_sem_agenda": clientes_sem_agenda,
        "retornos_em_janela": len(retornos),
        "clientes_inativos": len(clientes_inativos),
    }
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.categoria.asc(),
        ProcedimentoCatalogo.nome.asc(),
    ).all()

    return montar_contexto_marketing(metricas, procedimentos, retornos, clientes_inativos)


@app.route("/marketing-ia", methods=["GET", "POST"])
@login_required
@admin_required
def marketing_ia():
    contexto = contexto_marketing_ia()

    if request.method == "POST":
        objetivo = request.form.get("objetivo", "").strip()
        publico = request.form.get("publico", "").strip()
        canais = ",".join(request.form.getlist("canais")) or "facebook,instagram"
        orcamento_centavos = reais_para_centavos(request.form.get("orcamento"))

        try:
            gerada = gerar_campanha_ia(objetivo, publico, contexto, orcamento_centavos)
            campanha = CampanhaIA(
                tipo="meta",
                objetivo=objetivo,
                publico=publico,
                pesquisa=gerada.get("pesquisa"),
                estrategia=gerada.get("estrategia"),
                legenda=gerada.get("legenda"),
                chamada=gerada.get("chamada"),
                hashtags=gerada.get("hashtags"),
                canais=canais,
                orcamento_centavos=gerada.get("orcamento_centavos", orcamento_centavos),
                status="rascunho",
                criado_por_id=current_user.id,
            )
            db.session.add(campanha)
            db.session.commit()
            flash("Campanha gerada como rascunho. Revise e aprove o valor antes de publicar.")
            return redirect(url_for("marketing_ia"))
        except Exception as exc:
            flash(f"Nao foi possivel gerar campanha IA: {exc}")

    campanhas_ia = CampanhaIA.query.order_by(CampanhaIA.id.desc()).limit(30).all()
    return render_template(
        "marketing_ia.html",
        contexto=contexto,
        campanhas_ia=campanhas_ia,
        centavos_para_reais=centavos_para_reais,
    )


@app.route("/marketing-ia/<int:id>/aprovar", methods=["POST"])
@login_required
@admin_required
def aprovar_marketing_ia(id):
    campanha = CampanhaIA.query.get_or_404(id)
    campanha.orcamento_centavos = reais_para_centavos(request.form.get("orcamento"))
    campanha.status = "aprovada"
    campanha.aprovado_em = datetime.utcnow()
    campanha.aprovado_por_id = current_user.id
    db.session.commit()
    flash("Campanha aprovada. Agora ela pode ser publicada na Meta.")
    return redirect(url_for("marketing_ia"))


@app.route("/marketing-ia/<int:id>/publicar", methods=["POST"])
@login_required
@admin_required
def publicar_marketing_ia(id):
    campanha = CampanhaIA.query.get_or_404(id)
    if campanha.status != "aprovada":
        flash("A campanha precisa ser aprovada antes da publicacao.")
        return redirect(url_for("marketing_ia"))

    try:
        resultado = publicar_campanha(campanha)
        campanha.meta_resultado = json.dumps(resultado, ensure_ascii=False)
        campanha.status = "publicada"
        campanha.publicado_em = datetime.utcnow()
        campanha.erro = None
        flash("Publicacao enviada para a Meta ou simulada, conforme configuracao.")
    except Exception as exc:
        campanha.status = "erro"
        campanha.erro = str(exc)
        flash(f"Falha ao publicar na Meta: {exc}")

    db.session.commit()
    return redirect(url_for("marketing_ia"))


@app.route("/captar-lead", methods=["GET", "POST"])
def captar_lead():
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.categoria.asc(),
        ProcedimentoCatalogo.nome.asc()
    ).all()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        telefone = request.form.get("telefone", "").strip()
        email = request.form.get("email", "").strip().lower()
        interesse = request.form.get("interesse", "").strip()
        mensagem = request.form.get("mensagem", "").strip()
        origem = request.form.get("origem", "landing").strip() or "landing"

        if not nome or not telefone:
            flash("Informe nome e WhatsApp para enviarmos as opcoes.")
            return redirect(url_for("captar_lead"))

        lead = LeadComercial(
            nome=nome,
            telefone=somente_digitos(telefone),
            email=email,
            interesse=interesse,
            mensagem=mensagem,
            origem=origem,
            status="novo",
        )
        analise = gerar_abordagem_lead(lead, procedimentos)
        lead.score = analise["score"]
        lead.prioridade = analise["prioridade"]
        lead.resposta_ia = analise["resposta_ia"]
        lead.link_whatsapp = criar_link_whatsapp(lead.telefone, analise["mensagem"])
        db.session.add(lead)
        db.session.commit()
        return render_template("lead_obrigado.html")

    return render_template("captar_lead.html", procedimentos=procedimentos)


@app.route("/agente-comercial", methods=["GET", "POST"])
@login_required
@admin_required
def agente_comercial():
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.categoria.asc(),
        ProcedimentoCatalogo.nome.asc()
    ).all()

    if request.method == "POST":
        lead = LeadComercial(
            nome=request.form.get("nome", "").strip(),
            telefone=somente_digitos(request.form.get("telefone", "")),
            email=request.form.get("email", "").strip().lower(),
            interesse=request.form.get("interesse", "").strip(),
            origem=request.form.get("origem", "manual").strip() or "manual",
            mensagem=request.form.get("mensagem", "").strip(),
            criado_por_id=current_user.id,
        )
        if not lead.nome or not lead.telefone:
            flash("Informe nome e telefone do lead.")
            return redirect(url_for("agente_comercial"))

        analise = gerar_abordagem_lead(lead, procedimentos)
        lead.score = analise["score"]
        lead.prioridade = analise["prioridade"]
        lead.resposta_ia = analise["resposta_ia"]
        lead.link_whatsapp = criar_link_whatsapp(lead.telefone, analise["mensagem"])
        db.session.add(lead)
        db.session.commit()
        flash("Lead criado e qualificado pelo agente comercial.")
        return redirect(url_for("agente_comercial"))

    leads = LeadComercial.query.order_by(
        LeadComercial.score.desc(),
        LeadComercial.criado_em.desc()
    ).all()

    hoje = date.today()
    hoje_texto = hoje.strftime("%Y-%m-%d")
    clientes_inativos = []
    for cliente in Cliente.query.order_by(Cliente.nome.asc()).all():
        cliente, ultima_visita, atendimentos = cliente_com_ultima_visita(cliente)
        tem_agenda_futura = any(
            item.data and item.data >= hoje_texto and item.status not in ["cancelado", "faltou"]
            for item in atendimentos
        )
        if ultima_visita and (hoje - ultima_visita).days >= 90 and not tem_agenda_futura:
            clientes_inativos.append({
                "cliente": cliente,
                "ultima_visita": ultima_visita,
                "dias": (hoje - ultima_visita).days,
                "whatsapp": criar_link_whatsapp(
                    cliente.telefone,
                    f"Ola {cliente.nome}! Sentimos sua falta na Parvati Estetica. Quer que eu te envie horarios para uma avaliacao ou retorno?"
                ),
            })

    retornos = []
    for item in Agenda.query.filter(Agenda.tipo != "bloqueio").all():
        data_atendimento = data_agendamento_para_date(item.data)
        if item.status == "atendido" and item.retorno_dias and data_atendimento:
            data_retorno = data_atendimento + timedelta(days=item.retorno_dias)
            if hoje - timedelta(days=7) <= data_retorno <= hoje + timedelta(days=14):
                retornos.append({
                    "agendamento": item,
                    "data_retorno": data_retorno,
                    "dias": (data_retorno - hoje).days,
                    "whatsapp": criar_link_whatsapp(
                        item.telefone,
                        f"Ola {item.cliente}! Ja esta no periodo ideal para avaliarmos seu resultado de {item.procedimento}. Quer que eu veja um horario?"
                    ),
                })

    tarefas = recomendacoes_comerciais(leads, clientes_inativos, retornos)
    return render_template(
        "agente_comercial.html",
        leads=leads,
        tarefas=tarefas,
        clientes_inativos=clientes_inativos[:20],
        retornos=retornos[:20],
        procedimentos=procedimentos,
        url_captura=url_publica("captar_lead"),
    )


@app.route("/agente-comercial/<int:id>/qualificar", methods=["POST"])
@login_required
@admin_required
def qualificar_lead(id):
    lead = LeadComercial.query.get_or_404(id)
    procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).order_by(
        ProcedimentoCatalogo.categoria.asc(),
        ProcedimentoCatalogo.nome.asc()
    ).all()
    analise = gerar_abordagem_lead(lead, procedimentos)
    lead.score = analise["score"]
    lead.prioridade = analise["prioridade"]
    lead.resposta_ia = analise["resposta_ia"]
    lead.link_whatsapp = criar_link_whatsapp(lead.telefone, analise["mensagem"])
    lead.atualizado_em = datetime.utcnow()
    db.session.commit()
    flash("Lead requalificado e mensagem atualizada.")
    return redirect(url_for("agente_comercial"))


@app.route("/agente-comercial/<int:id>/whatsapp")
@login_required
@admin_required
def whatsapp_lead(id):
    lead = LeadComercial.query.get_or_404(id)
    if not lead.link_whatsapp:
        procedimentos = ProcedimentoCatalogo.query.filter_by(ativo=True).all()
        analise = gerar_abordagem_lead(lead, procedimentos)
        lead.link_whatsapp = criar_link_whatsapp(lead.telefone, analise["mensagem"])
    lead.status = "em_contato"
    lead.ultimo_contato_em = datetime.utcnow()
    db.session.commit()
    return redirect(lead.link_whatsapp)


@app.route("/agente-comercial/<int:id>/converter", methods=["POST"])
@login_required
@admin_required
def converter_lead(id):
    lead = LeadComercial.query.get_or_404(id)
    cliente = None
    if lead.telefone:
        cliente = Cliente.query.filter_by(telefone=lead.telefone).first()
    if not cliente and lead.nome:
        cliente = Cliente.query.filter_by(nome=lead.nome).first()
    if not cliente:
        cliente = Cliente(
            nome=lead.nome,
            telefone=lead.telefone,
            email=lead.email,
            indicado_por=f"Lead: {lead.origem}",
            observacao=f"Interesse inicial: {lead.interesse or ''} | Mensagem: {lead.mensagem or ''}",
        )
        db.session.add(cliente)
        db.session.flush()

    lead.cliente_id = cliente.id
    lead.status = "convertido"
    lead.atualizado_em = datetime.utcnow()
    db.session.commit()
    flash("Lead convertido em cliente.")
    return redirect(url_for("prontuario", id=cliente.id))


@app.route("/agente-comercial/<int:id>/status", methods=["POST"])
@login_required
@admin_required
def status_lead(id):
    lead = LeadComercial.query.get_or_404(id)
    status = request.form.get("status")
    if status in ["novo", "em_contato", "agendado", "convertido", "perdido"]:
        lead.status = status
        lead.atualizado_em = datetime.utcnow()
        db.session.commit()
        flash("Status do lead atualizado.")
    return redirect(url_for("agente_comercial"))


@app.route('/importar_clientes', methods=['GET','POST'])
@login_required
@admin_required
def importar_clientes():
    import pandas as pd

    if request.method == 'POST':

        arquivo = request.files['arquivo']

        df = pd.read_excel(arquivo)

        df.columns = df.columns.str.lower().str.strip()

        df['aniversario'] = pd.to_datetime(df['aniversario'], errors='coerce')
        df['data_procedimento'] = pd.to_datetime(df['data_procedimento'], errors='coerce')

        for _, row in df.iterrows():

            cliente = Cliente(

                nome=row['nome'],

                documento=row['documento'],
                outro_documento=row['outro_documento'],

                idade=row['idade'],

                endereco=row['endereco'],
                bairro=row['bairro'],
                estado=row['estado'],
                cep=row['cep'],

                estado_civil=row['estado_civil'],
                grau=row['grau'],

                email=row['email'],
                telefone=str(row['telefone']),

                indicado_por=row['indicado_por'],

                aniversario=row['aniversario'].date() if pd.notnull(row['aniversario']) else None,
                data_procedimento=row['data_procedimento'].date() if pd.notnull(row['data_procedimento']) else None,

                sexo=row['sexo'],

                nome_pai=row['nome_pai']
            )

            db.session.add(cliente)

        db.session.commit()

        flash("Clientes importados com sucesso!")

        return redirect(url_for('clientes'))

    return render_template('importar_clientes.html')

@app.route('/importar_agenda_excel', methods=['GET','POST'])
@login_required
@admin_required
def importar_agenda_excel():
    import pandas as pd

    if request.method == "POST":

        arquivo = request.files['arquivo']

        caminho = os.path.join("parvati_system/static/upload", secure_filename(arquivo.filename))
        arquivo.save(caminho)

        df = pd.read_excel(caminho)

        for _, row in df.iterrows():

            # procurar cliente existente
            cliente = Cliente.query.filter_by(telefone=str(row['telefone'])).first()

            if not cliente:

                cliente = Cliente(
                    nome=row['cliente'],
                    telefone=str(row['telefone']),
                    email=row['email']
                )

                db.session.add(cliente)
                db.session.commit()

            # criar agendamento
            agenda = Agenda(
                cliente_id=cliente.id,
                cliente=row['cliente'],
                telefone=str(row['telefone']),
                data=row['data'],
                hora=row['hora'],
                profissional=row['profissional'],
                procedimento=row['procedimento'],
                valor=row['valor'],
                pagamento=row['pagamento'],
                status="agendado"
            )

            db.session.add(agenda)

            # criar financeiro automático
            financeiro = Financeiro(
                data=row['data'],
                cliente=row['cliente'],
                procedimento=row['procedimento'],
                valor=row['valor'],
                tipo="entrada",
                forma_pagamento=row['pagamento']
            )

            db.session.add(financeiro)

        db.session.commit()

        flash("Agenda importada com sucesso!")

        return redirect(url_for('agenda'))

    return render_template("importar_agenda_excel.html")

@app.route('/eventos_agenda')
@login_required
def eventos_agenda():

    profissional = request.args.get("profissional")

    query = Agenda.query

    if profissional:
        query = query.filter_by(profissional=profissional)

    agendamentos = query.all()

    eventos = []

    for a in agendamentos:
        item = agendamento_para_visao(a)

        eventos.append({

            "id":a.id,

            "title":f"{item.visivel_cliente} - {item.visivel_procedimento}",

            "start":f"{a.data}T{a.hora}",

            "color":CORES_PROFISSIONAIS.get(a.profissional,"#6d2735")

        })

    return jsonify(eventos)

@app.route('/mover_agenda', methods=['POST'])
@login_required
def mover_agenda():

    payload = request.get_json(silent=True) or request.form

    id = payload.get('id')
    data = payload.get('data')
    hora = payload.get('hora')

    if not id or not data:
        return "dados invalidos", 400

    ag = Agenda.query.get_or_404(id)
    bloqueio = bloquear_se_sem_permissao(ag)
    if bloqueio:
        return "sem permissao", 403

    profissional = payload.get('profissional') or ag.profissional

    if hora and horario_ocupado(data, hora, profissional, ignorar_id=ag.id):
        return "horario ocupado", 409

    ag.data = data
    ag.hora = hora
    ag.profissional = profissional

    db.session.commit()

    return "ok"


@app.route('/upload_foto/<int:id>', methods=['POST'])
@login_required
@admin_required
def upload_foto(id):
    foto = request.files.get('foto')
    tipo_foto = request.form.get('tipo_foto')

    if not foto or foto.filename == '':
        flash('Selecione uma foto.')
        return redirect(url_for('prontuario', id=id))

    nome_arquivo = secure_filename(foto.filename)
    pasta_upload = os.path.join(app.static_folder, 'upload')
    os.makedirs(pasta_upload, exist_ok=True)
    caminho = os.path.join(pasta_upload, nome_arquivo)
    foto.save(caminho)

    nova_foto = FotoEvolucao(
        cliente_id=id,
        imagem=nome_arquivo,
        descricao=tipo_foto
    )
    db.session.add(nova_foto)
    db.session.commit()

    flash('Foto salva com sucesso!')
    return redirect(url_for('prontuario', id=id))

@app.route("/campanhas", methods=["GET", "POST"])
@login_required
@admin_required
def campanhas():
    links_gerados = []

    if request.method == "POST":
        titulo = request.form.get("titulo", "Promocao Parvati")
        mensagem = request.form.get("mensagem", "")

        if not mensagem:
            mensagem = """Ola, {nome}!

A Parvati Estetica preparou uma condicao especial para voce.

Responda esta mensagem para reservar seu horario."""

        links_gerados = campanha_promocional(
            mensagem_base=mensagem,
            observacao=f"Campanha manual: {titulo}"
        )
        flash(f"Campanha preparada para {len(links_gerados)} clientes.")

    disparos = DisparoCampanha.query.order_by(DisparoCampanha.id.desc()).all()

    return render_template(
        "campanhas.html",
        disparos=disparos,
        links_gerados=links_gerados,
        DisparoCampanha=DisparoCampanha
    )


@app.route("/aniversarios")
@login_required
@admin_required
def aniversarios():

    hoje = date.today()

    clientes = Cliente.query.all()

    aniversariantes = []

    for cliente in clientes:

        if cliente.aniversario:

            if cliente.aniversario.day == hoje.day and cliente.aniversario.month == hoje.month:

                aniversariantes.append(cliente)

    return render_template(
        "aniversarios.html",
        aniversariantes=aniversariantes
    )


@app.route('/enviar_aniversario/<int:id>')
@login_required
@admin_required
def enviar_aniversario_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    cupom = cliente.cupom_aniversario or f"PARVATI{cliente.id:04d}"
    cliente.cupom_aniversario = cupom

    mensagem = f"""Feliz aniversario, {cliente.nome}!

A Parvati Estetica deseja um dia especial para voce.

Use o cupom {cupom} para ganhar uma condicao especial no seu proximo procedimento."""
    link = criar_link_whatsapp(cliente.telefone, mensagem)
    registrar_disparo(cliente.id, "aniversario", f"Mensagem manual de aniversario: {cupom}", link, mensagem)
    db.session.commit()

    return redirect(link)

@app.route('/campanhas/aniversario')
@login_required
@admin_required
def campanhas_aniversarios():
    disparar_aniversarios()
    flash('Campanha de aniversário executada!')
    return redirect(url_for('campanhas'))

@app.route('/campanhas/promocao')
@login_required
@admin_required
def campanhas_promocao():
    campanha_promocional()
    flash('Campanha promocional executada!')
    return redirect(url_for('campanhas'))

@app.route('/campanhas/inativos')
@login_required
@admin_required
def campanhas_inativos():
    recuperar_clientes_inativos()
    flash('Campanha inativos executada!')
    return redirect(url_for('campanhas'))

@app.route('/campanhas/retorno')
@login_required
@admin_required
def campanhas_retorno():
    lembrar_retorno_procedimento()
    flash('Campanha retorno executada!')
    return redirect(url_for('campanhas'))


# ── Webhooks WhatsApp ─────────────────────────────────────────────────────────

def _extrair_mensagem_webhook(payload: dict) -> tuple[str, str, str] | None:
    """
    Extrai (telefone, texto, nome) de payloads dos provedores suportados.
    Retorna None se não for uma mensagem de texto válida.
    """
    # Z-API
    if "phone" in payload and "text" in payload:
        texto = payload.get("text", {})
        if isinstance(texto, dict):
            texto = texto.get("message", "")
        return payload["phone"], str(texto), payload.get("senderName", "")

    # Evolution API
    data = payload.get("data", {})
    if data.get("messageType") == "conversation":
        numero = data.get("key", {}).get("remoteJid", "").replace("@s.whatsapp.net", "")
        texto = data.get("message", {}).get("conversation", "")
        nome = data.get("pushName", "")
        if numero and texto:
            return numero, texto, nome

    return None


@app.route('/webhook/whatsapp/agenda', methods=['POST'])
def webhook_agenda():
    """Webhook para o chatbot de agendamento da Parvati Estética."""
    from parvati_system.chatbot_agenda import processar_mensagem
    from parvati_system.whatsapp import enviar_mensagem

    payload = request.get_json(silent=True) or {}
    resultado = _extrair_mensagem_webhook(payload)
    if not resultado:
        return jsonify({"ok": True})

    telefone, texto, nome = resultado
    if not texto.strip():
        return jsonify({"ok": True})

    resposta = processar_mensagem(telefone, texto, nome)
    try:
        enviar_mensagem(telefone, resposta)
    except Exception as exc:
        app.logger.error("Erro ao enviar resposta WhatsApp: %s", exc)

    return jsonify({"ok": True, "resposta": resposta})


@app.route('/webhook/whatsapp/oraculos', methods=['POST'])
def webhook_oraculos():
    """Webhook para o agente IA dos Oráculos de Lemúria."""
    from parvati_system.oraculos_bot import processar_mensagem
    from parvati_system.whatsapp import enviar_mensagem

    payload = request.get_json(silent=True) or {}
    resultado = _extrair_mensagem_webhook(payload)
    if not resultado:
        return jsonify({"ok": True})

    telefone, texto, nome = resultado
    if not texto.strip():
        return jsonify({"ok": True})

    resposta = processar_mensagem(telefone, texto, nome)
    try:
        enviar_mensagem(telefone, resposta)
    except Exception as exc:
        app.logger.error("Erro ao enviar resposta Oráculos: %s", exc)

    return jsonify({"ok": True, "resposta": resposta})
