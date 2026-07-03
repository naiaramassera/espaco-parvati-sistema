import os

from flask import Flask
from flask_login import LoginManager
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
from parvati_system.models import db, User, ProdutoEstoque, Agenda, Cliente, ProcedimentoCatalogo, ProcedimentoInsumo

app = Flask(__name__)

PROFISSIONAIS = ["Polyana", "Ana Claudia", "Lizandra", "Naiara"]

CORES_PROFISSIONAIS = {
    "Naiara": "#7B2CBF",      # Roxo
    "Polyana": "#2E8B57",     # Verde
    "Ana Claudia": "#FF8C00",# Laranja
    "Lizandra": "#DAA520"    # Dourado
}

# CONFIG

app.config["SECRET_KEY"] = os.environ.get("PARVATI_SECRET_KEY", "parvati-secret-local")

_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url:
    # Vercel tem filesystem read-only; usa /tmp para SQLite
    _sqlite_path = "/tmp/parvati.db" if os.environ.get("VERCEL") else "parvati.db"
    _db_url = f"sqlite:///{_sqlite_path}"
# Render.com entrega "postgres://..." mas SQLAlchemy 1.4+ exige "postgresql://"
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
if os.environ.get("PARVATI_SECURE_COOKIES") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["REMEMBER_COOKIE_SECURE"] = True


db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def garantir_colunas():
    colunas = {
        "financeiro": {
            "vencimento": "VARCHAR(20)",
            "boleto_status": "VARCHAR(30) DEFAULT 'nao_gerado'",
            "boleto_link": "VARCHAR(300)",
            "linha_digitavel": "VARCHAR(200)",
            "nosso_numero": "VARCHAR(80)",
            "integracao_boleto": "VARCHAR(50) DEFAULT 'manual'",
        },
        "disparo_campanha": {
            "canal": "VARCHAR(30) DEFAULT 'whatsapp'",
            "link_whatsapp": "VARCHAR(500)",
            "mensagem": "TEXT",
        },
        "agenda": {
            "cliente_id": "INTEGER",
            "procedimento_id": "INTEGER",
            "custo_estimado": "FLOAT",
            "duracao_minutos": "INTEGER DEFAULT 60",
            "retorno_dias": "INTEGER",
            "observacoes": "TEXT",
            "tipo": "VARCHAR(20) DEFAULT 'atendimento'",
            "criado_por_id": "INTEGER",
        },
        "user": {
            "perfil": "VARCHAR(30) DEFAULT 'profissional'",
            "profissional": "VARCHAR(50)",
            "telefone": "VARCHAR(20)",
            "ativo": "BOOLEAN DEFAULT 1",
        },
        "produto_estoque": {
            "marca": "VARCHAR(100)",
            "lote": "VARCHAR(80)",
            "custo_unitario": "FLOAT DEFAULT 0",
        },
    }

    for tabela, novas_colunas in colunas.items():
        existentes = {
            coluna[1]
            for coluna in db.session.execute(text(f"PRAGMA table_info({tabela})")).fetchall()
        }

        for nome, tipo in novas_colunas.items():
            if nome not in existentes:
                db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))

    db.session.commit()

    normalizar_agendamentos_existentes()
    normalizar_usuarios_existentes()


def normalizar_agendamentos_existentes():
    mapa_status = {
        "agendado": "agendado",
        "Agendado": "agendado",
        "confirmado": "confirmado",
        "Confirmado": "confirmado",
        "atendido": "atendido",
        "Atendido": "atendido",
        "cancelado": "cancelado",
        "Cancelado": "cancelado",
        "faltou": "faltou",
        "Faltou": "faltou",
    }

    alterou = False

    for agendamento in Agenda.query.all():
        if not agendamento.tipo:
            agendamento.tipo = "atendimento"
            alterou = True

        status_normalizado = mapa_status.get(agendamento.status, "agendado")
        if agendamento.status != status_normalizado:
            agendamento.status = status_normalizado
            alterou = True

        if not agendamento.cliente_id:
            cliente = None
            if agendamento.telefone:
                cliente = Cliente.query.filter_by(telefone=agendamento.telefone).first()

            if not cliente and agendamento.cliente:
                cliente = Cliente.query.filter_by(nome=agendamento.cliente).first()

            if cliente:
                agendamento.cliente_id = cliente.id
                alterou = True

    if alterou:
        db.session.commit()


def normalizar_usuarios_existentes():
    alterou = False

    admin = User.query.filter_by(email="naiara@espacoparvati.com").first()
    if admin:
        if admin.perfil != "admin":
            admin.perfil = "admin"
            alterou = True
        if not admin.profissional:
            admin.profissional = "Naiara"
            alterou = True
        if admin.ativo is None:
            admin.ativo = True
            alterou = True
        if os.environ.get("VERCEL") and not check_password_hash(admin.senha or "", "Parvati@2026"):
            admin.senha = generate_password_hash("Parvati@2026")
            alterou = True

    if alterou:
        db.session.commit()


def popular_estoque_inicial():
    if ProdutoEstoque.query.first():
        return

    produtos = [
        ("Alcool 70%", "Biosseguranca", "frasco", 0, 3),
        ("Clorexidina", "Biosseguranca", "frasco", 0, 2),
        ("Desinfetante hospitalar", "Biosseguranca", "frasco", 0, 2),
        ("Sabonete antisseptico", "Biosseguranca", "frasco", 0, 2),
        ("Luva nitrilica", "EPI", "caixa", 0, 3),
        ("Luva de procedimento", "EPI", "caixa", 0, 3),
        ("Mascara descartavel", "EPI", "caixa", 0, 2),
        ("Touca descartavel", "EPI", "pacote", 0, 2),
        ("Avental descartavel", "EPI", "unidade", 0, 10),
        ("Gaze esteril", "Descartaveis", "pacote", 0, 5),
        ("Algodao", "Descartaveis", "pacote", 0, 3),
        ("Lenco descartavel", "Descartaveis", "pacote", 0, 3),
        ("Espatula descartavel", "Descartaveis", "pacote", 0, 2),
        ("Seringa descartavel", "Descartaveis", "unidade", 0, 20),
        ("Agulha descartavel", "Descartaveis", "unidade", 0, 20),
        ("Coletor perfurocortante", "Biosseguranca", "unidade", 0, 1),
        ("Gel de limpeza facial", "Limpeza de pele", "frasco", 0, 2),
        ("Demaquilante", "Limpeza de pele", "frasco", 0, 1),
        ("Esfoliante facial", "Limpeza de pele", "frasco", 0, 1),
        ("Emoliente", "Limpeza de pele", "frasco", 0, 1),
        ("Tonico facial", "Limpeza de pele", "frasco", 0, 1),
        ("Mascara calmante", "Limpeza de pele", "pote", 0, 1),
        ("Filtro solar facial", "Finalizacao", "frasco", 0, 2),
        ("Acido glicolico", "Peeling", "frasco", 0, 1),
        ("Acido mandelico", "Peeling", "frasco", 0, 1),
        ("Acido salicilico", "Peeling", "frasco", 0, 1),
        ("Neutralizante de peeling", "Peeling", "frasco", 0, 1),
        ("Serum hidratante", "Dermocosmeticos", "frasco", 0, 1),
        ("Serum vitamina C", "Dermocosmeticos", "frasco", 0, 1),
        ("Acido hialuronico cosmetico", "Dermocosmeticos", "frasco", 0, 1),
        ("Gel condutor", "Equipamentos", "frasco", 0, 2),
        ("Papel maca", "Descartaveis", "rolo", 0, 3),
    ]

    for nome, categoria, unidade, quantidade, minimo in produtos:
        db.session.add(ProdutoEstoque(
            nome=nome,
            categoria=categoria,
            unidade=unidade,
            quantidade=quantidade,
            estoque_minimo=minimo,
            observacao="Produto base sugerido. Conferir marca, validade e regularizacao antes de usar."
        ))

    db.session.commit()

with app.app_context():
    db.create_all()
    garantir_colunas()
    popular_estoque_inicial()
    if not ProcedimentoCatalogo.query.first():
        procedimentos = [
            ("Limpeza de pele", "Facial", 90, 180, 45, 30, "Enviar orientacoes de preparo e retorno em 30 dias."),
            ("Botox", "Injetaveis", 60, 900, 260, 15, "Registrar lote, pontos aplicados e retorno para revisao."),
            ("Peeling quimico", "Facial", 60, 250, 70, 21, "Avaliar fototipo, contraindicacoes e cuidados pos-procedimento."),
            ("Bioestimulador", "Injetaveis", 75, 1800, 720, 45, "Registrar produto, lote, areas tratadas e plano de sessoes."),
        ]
        for nome, categoria, duracao, valor, custo, retorno, orientacoes in procedimentos:
            db.session.add(ProcedimentoCatalogo(
                nome=nome,
                categoria=categoria,
                duracao_minutos=duracao,
                valor_padrao=valor,
                custo_estimado=custo,
                retorno_dias=retorno,
                orientacoes=orientacoes
            ))
    for nome in PROFISSIONAIS:
        email = f"{nome.lower().replace(' ', '.')}@espacoparvati.com"
        if not User.query.filter_by(email=email).first():
            db.session.add(User(
                nome=nome,
                email=email,
                senha=generate_password_hash("Parvati@2026"),
                perfil="admin" if nome == "Naiara" else "profissional",
                profissional=nome,
                ativo=True
            ))
    db.session.commit()


