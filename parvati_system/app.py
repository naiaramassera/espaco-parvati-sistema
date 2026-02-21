from flask import Flask, render_template, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user

import urllib.parse
from datetime import date

CORES_PROFISSIONAIS = {
    "Naiara": "#7B2CBF",      # Roxo
    "Marina": "#1E90FF",      # Azul
    "Polyana": "#2E8B57",     # Verde
    "Ana Claudia": "#FF8C00",# Laranja
    "Lizandra": "#DAA520"    # Dourado
}

# CONFIG
app = Flask(__name__)
app.config['SECRET_KEY'] = 'parvati-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = ('sqlite:///parvati.db')

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'


# MODELS
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    senha = db.Column(db.String(100))


class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100))
    telefone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    observacao = db.Column(db.Text)
    data_nascimento = db.Column(db.Date)
    nascimento = db.Column(db.Date)



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Agenda(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    telefone = db.Column(db.String(20))
    valor = db.Column(db.Float, nullable=True)

    data = db.Column(db.String(10))   # 14/02/2026
    hora = db.Column(db.String(5))    # 14:00

    cliente = db.Column(db.String(100))
    profissional = db.Column(db.String(50))
    procedimento = db.Column(db.String(100))


    status = db.Column(db.String(20), default='Agendado')

class Anamnese(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    cliente = db.Column(db.String(100))
    telefone = db.Column(db.String(30))

    idade = db.Column(db.String(10))
    sexo = db.Column(db.String(20))

    possui_doenca = db.Column(db.String(5))
    usa_medicacao = db.Column(db.String(5))

    alergias = db.Column(db.Text)
    observacoes = db.Column(db.Text)

    procedimento = db.Column(db.String(100))
    data = db.Column(db.String(20))


# ROUTES
@app.route('/')
@app.route("/home")
@login_required
def home():

    hoje = date.today().strftime('%Y-%m-%d')

    total_hoje = Agenda.query.filter_by(data=hoje).count()

    total_clientes = Cliente.query.count()

    total_procedimentos = Agenda.query.count()

    faturamento = db.session.query(
        db.func.sum(Agenda.valor)
    ).scalar() or 0

    agenda_hoje = Agenda.query.filter_by(data=hoje).all()

    return render_template(
        'home.html',
        total_hoje=total_hoje,
        total_clientes=total_clientes,
        total_procedimentos=total_procedimentos,
        faturamento=faturamento,
        agenda_hoje=agenda_hoje
    )

@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        user = User.query.filter_by(
            email=request.form['email']
        ).first()

        if user and user.senha == request.form['senha']:
            login_user(user)
            return redirect(url_for('agenda'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/agenda', methods=['GET', 'POST'])
@login_required
def agenda():

    if request.method == 'POST':

        novo = Agenda(
            data=request.form['data'],
            hora=request.form['hora'],
            cliente=request.form['cliente'],
            profissional=request.form['profissional'],
            procedimento=request.form['procedimento']
        )

        db.session.add(novo)
        db.session.commit()

        mensagem = f"""
                        Olá {novo.cliente} 💖

                        Seu atendimento foi agendado com sucesso!

                        📅 Data: {novo.data}
                        ⏰ Hora: {novo.hora}
                        💆‍♀️ Procedimento: {novo.procedimento}
                        👩‍⚕️ Profissional: {novo.profissional}

                        Espaço Parvati ✨
                        Beleza com consciência, elegância e naturalidade.
                        """

        texto = urllib.parse.quote(mensagem)

        telefone = novo.telefone.strip()

        link_whatsapp = f"https://wa.me/55{telefone}?text={texto}"

        return redirect(link_whatsapp)

    lista = Agenda.query.filter(
        Agenda.status.in_(['Agendado', 'Confirmado', 'Atendido', 'Faltou'])
    ).order_by(
        Agenda.data,
        Agenda.hora
    ).all()

    return render_template('agenda.html', lista=lista)


@app.route('/cancelar/<int:id>')
@login_required
def cancelar(id):

    ag = Agenda.query.get(id)

    if ag:
        ag.status = 'Cancelado'
        db.session.commit()

    return redirect(url_for('agenda'))

@app.route('/confirmar/<int:id>')
@login_required
def confirmar(id):

    ag = Agenda.query.get(id)

    if ag:
        ag.status = 'Confirmado'
        db.session.commit()

    return redirect(url_for('agenda'))


@app.route('/atendido/<int:id>')
@login_required
def atendido(id):

    ag = Agenda.query.get(id)

    if ag:
        ag.status = 'Atendido'
        db.session.commit()

    return redirect(url_for('agenda'))


@app.route('/faltou/<int:id>')
@login_required
def faltou(id):

    ag = Agenda.query.get(id)

    if ag:
        ag.status = 'Faltou'
        db.session.commit()

    return redirect(url_for('agenda'))


import urllib.parse

@app.route('/novo_agendamento', methods=['GET', 'POST'])
@login_required
def novo_agendamento():

    data_selecionada = request.args.get('data')

    if request.method == 'POST':

        novo = Agenda(
            telefone=request.form['telefone'],
            data=request.form['data'],
            hora=request.form['hora'],
            cliente=request.form['cliente'],
            profissional=request.form['profissional'],
            procedimento=request.form['procedimento']
        )

        db.session.add(novo)
        db.session.commit()

        # ===== WHATSAPP =====

        mensagem = f"""
Olá {novo.cliente} 💖

Seu atendimento no Espaço Parvati foi confirmado!

📅 Data: {novo.data}
⏰ Hora: {novo.hora}
💆 Procedimento: {novo.procedimento}
👩 Profissional: {novo.profissional}

Te aguardamos com carinho ✨
"""

        texto = urllib.parse.quote(mensagem)

        telefone = novo.telefone.strip().replace(" ", "").replace("-", "")

        link = f"https://wa.me/55{telefone}?text={texto}"

        return redirect(link)

    return render_template(
        'novo_agendamento.html',
        data=data_selecionada
    )

@app.route('/clientes')
@login_required
def clientes():
    lista = Cliente.query.all()
    return render_template('clientes.html', clientes=lista)

from datetime import datetime

@app.route('/anamnese', methods=['GET', 'POST'])
@login_required
def anamnese():

    if request.method == 'POST':

        nova = Anamnese(

            cliente=request.form['cliente'],
            telefone=request.form['telefone'],

            idade=request.form['idade'],
            sexo=request.form['sexo'],

            possui_doenca=request.form['doenca'],
            usa_medicacao=request.form['medicacao'],

            alergias=request.form['alergias'],
            observacoes=request.form['observacoes'],

            procedimento=request.form['procedimento'],
            data=request.form['data']
        )

        db.session.add(nova)
        db.session.commit()

        return redirect(url_for('lista_anamnese'))

    return render_template('anamnese.html')

@app.route('/anamnese_cliente', methods=['GET', 'POST'])
def anamnese_cliente():

    if request.method == 'POST':

        nova = Anamnese(

            cliente=request.form['cliente'],
            telefone=request.form['telefone'],

            idade=request.form['idade'],
            sexo=request.form['sexo'],

            possui_doenca=request.form['doenca'],
            usa_medicacao=request.form['medicacao'],

            alergias=request.form['alergias'],
            observacoes=request.form['observacoes'],

            procedimento=request.form['procedimento'],
            data=request.form['data']
        )

        db.session.add(nova)
        db.session.commit()

        return render_template('obrigado.html')

    return render_template('anamnese_cliente.html')

@app.route('/lista_anamnese')
@login_required
def lista_anamnese():

    lista = Anamnese.query.order_by(Anamnese.data.desc()).all()

    return render_template('lista_anamnese.html', lista=lista)

@app.route('/ver_anamnese/<int:id>')
@login_required
def ver_anamnese(id):

    item = Anamnese.query.get(id)

    return render_template('ver_anamnese.html', item=item)

@app.route('/novo_cliente', methods=['GET', 'POST'])
@login_required
def novo_cliente():

    if request.method == 'POST':

        from datetime import datetime

        cliente = Cliente(
            nome=request.form['nome'],
            telefone=request.form['telefone'],
            email=request.form['email'],
            observacao=request.form['observacao'],
            nascimento=datetime.strptime(
                request.form['nascimento'],
                "%Y-%m-%d"
            ) if request.form['nascimento'] else None
        )

        db.session.add(cliente)
        db.session.commit()

        return redirect(url_for('clientes'))

    return render_template('novo_cliente.html')

@app.route('/buscar_cliente')
def buscar_cliente():
    nome = request.args.get('nome')

    cliente = Cliente.query.filter_by(nome=nome).first()

    if cliente:
        return {
            "telefone": cliente.telefone,
            "email": cliente.email,
            "observacao": cliente.observacao
        }

    return {}

@app.route('/historico/<nome>')
@login_required
def historico(nome):

    agendamentos = Agenda.query.filter_by(cliente=nome).all()

    cliente = Cliente.query.filter_by(nome=nome).first()

    return render_template(
        'historico.html',
        agendamentos=agendamentos,
        cliente=cliente
    )

@app.route('/disparar_aniversarios')
@login_required
def disparar_aniversarios():

    hoje = date.today()

    clientes = Cliente.query.filter(
        db.extract('month', Cliente.nascimento) == hoje.month,
        db.extract('day', Cliente.nascimento) == hoje.day
    ).all()

    if not clientes:
        return "Nenhum aniversariante hoje 🎂"

    links = []

    for c in clientes:

        msg = f"""
Olá {c.nome} 💖

O Espaço Parvati deseja um feliz aniversário! 🎉✨

Hoje temos um presente especial pra você 🎁

Agende seu horário com desconto 💆‍♀️🌸
"""

        texto = urllib.parse.quote(msg)

        telefone = c.telefone.replace(" ", "").replace("-", "")

        link = f"https://wa.me/55{telefone}?text={texto}"

        links.append(link)

    return "<br>".join([
        f'<a href="{l}" target="_blank">Enviar WhatsApp</a>'
        for l in links
    ])

@app.route('/eventos')
@login_required
def eventos():

    agendamentos = Agenda.query.all()

    eventos = []

    for a in agendamentos:

        cor = CORES_PROFISSIONAIS.get(
            a.profissional,
            "#B22222"  # cor padrão
        )

        eventos.append({
            "title": f"{a.procedimento} - {a.cliente}",
            "start": f"{a.data}T{a.hora}",
            "color": cor
        })

    return eventos


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

