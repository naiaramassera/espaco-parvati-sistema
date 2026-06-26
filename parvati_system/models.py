from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


# MODELS
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    senha = db.Column(db.String(100))
    perfil = db.Column(db.String(30), default="profissional")
    profissional = db.Column(db.String(50))
    ativo = db.Column(db.Boolean, default=True)


class Cliente(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    nome = db.Column(db.String(150))
    documento = db.Column(db.String(50))
    outro_documento = db.Column(db.String(50))

    idade = db.Column(db.Integer)
    nascimento = db.Column(db.String(30))
    endereco = db.Column(db.String(200))
    bairro = db.Column(db.String(100))
    estado = db.Column(db.String(50))
    cep = db.Column(db.String(20))
    ultima_visita = db.Column(db.Date)
    estado_civil = db.Column(db.String(50))
    grau = db.Column(db.String(100))

    email = db.Column(db.String(150))
    telefone = db.Column(db.String(30))

    indicado_por = db.Column(db.String(150))

    cupom_aniversario = db.Column(db.String(50))

    aniversario = db.Column(db.Date)

    data_procedimento = db.Column(db.Date)

    sexo = db.Column(db.String(20))

    nome_pai = db.Column(db.String(150))

    observacao = db.Column(db.Text)

class Anamnese(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))

    doencas = db.Column(db.Text)
    medicamentos = db.Column(db.Text)
    alergias = db.Column(db.Text)

    procedimentos_anteriores = db.Column(db.Text)

    tipo_pele = db.Column(db.String(50))
    sensibilidade = db.Column(db.String(50))

    avaliacao = db.Column(db.Text)
    plano_tratamento = db.Column(db.Text)

    foto_antes = db.Column(db.String(200))
    foto_depois = db.Column(db.String(200))

    data = db.Column(db.DateTime, default=datetime.utcnow)


class Agenda(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    procedimento_id = db.Column(db.Integer, db.ForeignKey('procedimento_catalogo.id'), nullable=True)
    telefone = db.Column(db.String(20))
    valor = db.Column(db.Float, nullable=True)
    custo_estimado = db.Column(db.Float, nullable=True)
    duracao_minutos = db.Column(db.Integer, default=60)
    retorno_dias = db.Column(db.Integer, nullable=True)
    data = db.Column(db.String(10))   # 14/02/2026
    hora = db.Column(db.String(5))    # 14:00
    cliente = db.Column(db.String(100))
    profissional = db.Column(db.String(50))
    procedimento = db.Column(db.String(100))
    pagamento = db.Column(db.String(30))
    status = db.Column(db.String(20), default='agendado')
    observacoes = db.Column(db.Text)
    tipo = db.Column(db.String(20), default="atendimento")
    criado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


class ProcedimentoCatalogo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(80))
    duracao_minutos = db.Column(db.Integer, default=60)
    valor_padrao = db.Column(db.Float, default=0)
    custo_estimado = db.Column(db.Float, default=0)
    retorno_dias = db.Column(db.Integer, nullable=True)
    orientacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class ProcedimentoInsumo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    procedimento_id = db.Column(db.Integer, db.ForeignKey('procedimento_catalogo.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto_estoque.id'), nullable=False)
    quantidade = db.Column(db.Float, nullable=False, default=0)
    custo_unitario_snapshot = db.Column(db.Float, default=0)
    observacao = db.Column(db.String(200))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class Financeiro(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.String(20))
    cliente = db.Column(db.String(120))
    procedimento = db.Column(db.String(120))
    valor = db.Column(db.Float)
    tipo = db.Column(db.String(20))  # entrada ou saida
    forma_pagamento = db.Column(db.String(50))
    vencimento = db.Column(db.String(20))
    boleto_status = db.Column(db.String(30), default="nao_gerado")
    boleto_link = db.Column(db.String(300))
    linha_digitavel = db.Column(db.String(200))
    nosso_numero = db.Column(db.String(80))
    integracao_boleto = db.Column(db.String(50), default="manual")

class FotoEvolucao(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    cliente_id = db.Column(db.Integer)

    imagem = db.Column(db.String(200))

    descricao = db.Column(db.String(200))

class DisparoCampanha(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    cliente_id = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # aniversario, inativo, retorno, promocao
    data_envio = db.Column(db.Date, nullable=False)
    observacao = db.Column(db.String(200))
    canal = db.Column(db.String(30), default="whatsapp")
    link_whatsapp = db.Column(db.String(500))
    mensagem = db.Column(db.Text)


class CampanhaIA(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(40), default="meta")
    objetivo = db.Column(db.String(160))
    publico = db.Column(db.String(220))
    pesquisa = db.Column(db.Text)
    estrategia = db.Column(db.Text)
    legenda = db.Column(db.Text)
    chamada = db.Column(db.String(220))
    hashtags = db.Column(db.String(300))
    canais = db.Column(db.String(120), default="facebook,instagram")
    orcamento_centavos = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default="rascunho")
    meta_resultado = db.Column(db.Text)
    erro = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    aprovado_em = db.Column(db.DateTime)
    publicado_em = db.Column(db.DateTime)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    aprovado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


class LeadComercial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    interesse = db.Column(db.String(160))
    origem = db.Column(db.String(80), default="manual")
    mensagem = db.Column(db.Text)
    status = db.Column(db.String(30), default="novo")
    score = db.Column(db.Integer, default=0)
    prioridade = db.Column(db.String(30), default="normal")
    resposta_ia = db.Column(db.Text)
    link_whatsapp = db.Column(db.String(500))
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_contato_em = db.Column(db.DateTime)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


class ConversaBot(db.Model):
    """Rastreia o estado de conversas ativas no WhatsApp."""
    id = db.Column(db.Integer, primary_key=True)
    telefone = db.Column(db.String(30), nullable=False)
    canal = db.Column(db.String(30), nullable=False, default="agenda")  # agenda | oraculos
    estado = db.Column(db.String(40), nullable=False, default="inicio")
    nome_remetente = db.Column(db.String(150))
    agendamento_id = db.Column(db.Integer, db.ForeignKey('agenda.id'), nullable=True)
    dados = db.Column(db.JSON, default=dict)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow)


class ProdutoEstoque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(80), nullable=False)
    marca = db.Column(db.String(100))
    lote = db.Column(db.String(80))
    custo_unitario = db.Column(db.Float, default=0)
    unidade = db.Column(db.String(30), default="unidade")
    quantidade = db.Column(db.Float, default=0)
    estoque_minimo = db.Column(db.Float, default=0)
    validade = db.Column(db.String(20))
    fornecedor = db.Column(db.String(120))
    registro_anvisa = db.Column(db.String(80))
    local_armazenamento = db.Column(db.String(120))
    observacao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class MovimentacaoEstoque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto_estoque.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # entrada ou saida
    quantidade = db.Column(db.Float, nullable=False)
    motivo = db.Column(db.String(150))
    data = db.Column(db.DateTime, default=datetime.utcnow)
