from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import requests
import logging
import os
import math
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///transport.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'sua_chave_secreta'
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'AIzaSyBPdSOZF2maHURmdRmVzLgVo5YO2wliylo')

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Modelos
class Motorista(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cpf = db.Column(db.String(11), unique=True, nullable=False)

class Veiculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(7), unique=True, nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    disponivel = db.Column(db.Boolean, default=True)

class Viagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    motorista_id = db.Column(db.Integer, db.ForeignKey('motorista.id'), nullable=False)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'), nullable=False)
    cliente = db.Column(db.String(100), nullable=False)
    endereco_saida = db.Column(db.String(200), nullable=False)
    endereco_destino = db.Column(db.String(200), nullable=False)
    distancia_km = db.Column(db.Float, nullable=True)
    data_inicio = db.Column(db.DateTime, nullable=False)
    data_fim = db.Column(db.DateTime, nullable=True)
    duracao_segundos = db.Column(db.Integer, nullable=True)
    custo = db.Column(db.Float, nullable=True)
    forma_pagamento = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), nullable=False, default='pendente')
    observacoes = db.Column(db.Text, nullable=True)
    motorista = db.relationship('Motorista', backref='viagens')
    veiculo = db.relationship('Veiculo', backref='viagens')

# Função para calcular distância em linha reta usando a fórmula de Haversine
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Raio da Terra em quilômetros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Função para obter coordenadas de um endereço
def get_coordinates(endereco):
    url = 'https://maps.googleapis.com/maps/api/geocode/json'
    params = {'address': endereco, 'key': GOOGLE_MAPS_API_KEY}
    try:
        logger.debug(f"Obtendo coordenadas para o endereço: {endereco}")
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Resposta da Geocoding API: {data}")
        if data['status'] == 'OK' and len(data['results']) > 0:
            location = data['results'][0]['geometry']['location']
            return location['lat'], location['lng']
        else:
            logger.warning(f"Endereço não encontrado: {endereco}")
            return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao obter coordenadas: {str(e)}")
        return None, None

# Funções de API
def validar_endereco(endereco):
    url = 'https://maps.googleapis.com/maps/api/geocode/json'
    params = {'address': endereco, 'key': GOOGLE_MAPS_API_KEY}
    try:
        logger.debug(f"Validando endereço: {endereco}")
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Resposta da Geocoding API: {data}")
        return data['status'] == 'OK' and len(data['results']) > 0
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na Geocoding API: {str(e)}")
        return False

def calcular_distancia_e_duracao(origem, destino):
    url = 'https://maps.googleapis.com/maps/api/directions/json'
    params = {
        'origin': origem,
        'destination': destino,
        'key': GOOGLE_MAPS_API_KEY,
        'units': 'metric',
        'departure_time': 'now'
    }
    try:
        logger.debug(f"Calculando distância e duração entre {origem} e {destino}")
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Resposta da Directions API: {data}")
        if data['status'] == 'OK' and data['routes']:
            route = data['routes'][0]['legs'][0]
            distancia_km = route['distance']['value'] / 1000
            duracao_segundos = route['duration']['value']
            return distancia_km, duracao_segundos
        else:
            logger.warning(f"Erro na Directions API: {data.get('error_message', 'Erro desconhecido')}")
            lat1, lon1 = get_coordinates(origem)
            lat2, lon2 = get_coordinates(destino)
            if lat1 is None or lat2 is None:
                flash('Não foi possível calcular a distância entre os endereços fornecidos.', 'error')
                return None, None
            distancia_km = haversine_distance(lat1, lon1, lat2, lon2)
            velocidade_media_kmh = 60
            duracao_segundos = int((distancia_km / velocidade_media_kmh) * 3600)
            flash('A distância foi calculada em linha reta, pois não há rota direta disponível. A duração é estimada.', 'warning')
            return distancia_km, duracao_segundos
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro de conexão com a Directions API: {str(e)}")
        flash(f'Erro de conexão com a API do Google Maps: {str(e)}', 'error')
        return None, None

# Rotas
@app.route('/')
def index():
    motoristas = Motorista.query.all()
    veiculos = Veiculo.query.all()
    viagens = Viagem.query.all()

    # Verificar se há alguma viagem em andamento
    tem_viagem_em_andamento = any(viagem.status == 'em_andamento' for viagem in viagens)

    # Filtrar viagens com status pendente ou em_andamento para mostrar na dashboard
    viagens_ativas = Viagem.query.filter(Viagem.status.in_(['pendente', 'em_andamento'])).order_by(Viagem.data_inicio.desc()).all()

    return render_template(
        'index.html',
        motoristas=motoristas,
        veiculos=veiculos,
        viagens=viagens,
        tem_viagem_em_andamento=tem_viagem_em_andamento,
        viagens_ativas=viagens_ativas
    )


@app.route('/cadastrar_motorista', methods=['GET', 'POST'])
def cadastrar_motorista():
    if request.method == 'POST':
        nome = request.form['nome']
        cpf = request.form['cpf']
        motorista = Motorista(nome=nome, cpf=cpf)
        try:
            db.session.add(motorista)
            db.session.commit()
            flash('Motorista cadastrado com sucesso!', 'success')
            return redirect(url_for('index'))
        except:
            db.session.rollback()
            flash('Erro: CPF já cadastrado.', 'error')
    return render_template('cadastrar_motorista.html')

@app.route('/cadastrar_veiculo', methods=['GET', 'POST'])
def cadastrar_veiculo():
    if request.method == 'POST':
        placa = request.form['placa']
        modelo = request.form['modelo']
        veiculo = Veiculo(placa=placa, modelo=modelo)
        try:
            db.session.add(veiculo)
            db.session.commit()
            flash('Veículo cadastrado com sucesso!', 'success')
            return redirect(url_for('index'))
        except:
            db.session.rollback()
            flash('Erro: Placa já cadastrada.', 'error')
    return render_template('cadastrar_veiculo.html')

@app.route('/iniciar_viagem', methods=['GET', 'POST'])
def iniciar_viagem():
    if request.method == 'POST':
        try:
            motorista_id = request.form['motorista_id']
            veiculo_id = request.form['veiculo_id']
            cliente = request.form['cliente']
            endereco_saida = request.form['endereco_saida']
            endereco_destino = request.form['endereco_destino']
            data_inicio = datetime.strptime(request.form['data_inicio'], '%Y-%m-%dT%H:%M')
            custo = float(request.form['custo']) if request.form['custo'] else None
            forma_pagamento = request.form['forma_pagamento']
            status = request.form['status']
            observacoes = request.form['observacoes'] if request.form['observacoes'] else None

            logger.debug(f"Dados recebidos: motorista_id={motorista_id}, veiculo_id={veiculo_id}, cliente={cliente}, endereco_saida={endereco_saida}, endereco_destino={endereco_destino}")

            veiculo = Veiculo.query.get(veiculo_id)
            if not veiculo:
                flash('Erro: Veículo não encontrado.', 'error')
                return redirect(url_for('iniciar_viagem'))
            if not veiculo.disponivel:
                flash('Erro: Veículo já está em viagem.', 'error')
                return redirect(url_for('iniciar_viagem'))

            if data_inicio < datetime.now():
                flash('A data e hora da viagem não podem ser no passado.', 'error')
                return redirect(url_for('iniciar_viagem'))

            if not validar_endereco(endereco_saida):
                flash('Endereço de saída inválido. Por favor, insira um endereço válido.', 'error')
                return redirect(url_for('iniciar_viagem'))
            if not validar_endereco(endereco_destino):
                flash('Endereço de destino inválido. Por favor, insira um endereço válido.', 'error')
                return redirect(url_for('iniciar_viagem'))

            distancia_km, duracao_segundos = calcular_distancia_e_duracao(endereco_saida, endereco_destino)
            if distancia_km is None or duracao_segundos is None:
                flash('Não foi possível calcular a distância ou duração. Verifique os endereços ou a configuração da API.', 'error')
                return redirect(url_for('iniciar_viagem'))

            viagem = Viagem(
                motorista_id=motorista_id,
                veiculo_id=veiculo_id,
                cliente=cliente,
                endereco_saida=endereco_saida,
                endereco_destino=endereco_destino,
                distancia_km=distancia_km,
                data_inicio=data_inicio,
                duracao_segundos=duracao_segundos,
                custo=custo,
                forma_pagamento=forma_pagamento,
                status=status,
                observacoes=observacoes
            )
            veiculo.disponivel = False
            db.session.add(viagem)
            db.session.commit()
            flash(f'Viagem iniciada com sucesso! Distância: {distancia_km:.2f} km, Duração estimada: {duracao_segundos//60} minutos', 'success')
            return redirect(url_for('iniciar_viagem'))
        except Exception as e:
            logger.error(f"Erro ao iniciar viagem: {str(e)}")
            flash(f'Erro ao iniciar viagem: {str(e)}', 'error')
            return redirect(url_for('iniciar_viagem'))

    motoristas = Motorista.query.all()
    veiculos = Veiculo.query.filter_by(disponivel=True).all()
    viagens = Viagem.query.filter_by(data_fim=None).order_by(Viagem.data_inicio.desc()).all()
    # Preparar dados serializáveis para o JavaScript
    viagens_data = []
    for viagem in viagens:
        # Converter data_inicio para string e formatar como desejado
        data_inicio_formatada = viagem.data_inicio.strftime('%Y-%m-%d %H:%M:%S')[:-3]  # Remove os últimos 3 caracteres (milissegundos)
        horario_chegada = (viagem.data_inicio + timedelta(seconds=viagem.duracao_segundos)).strftime('%d/%m/%Y %H:%M') if viagem.duracao_segundos else 'Não calculado'
        viagem_dict = {
            'id': viagem.id,
            'motorista_id': viagem.motorista_id,
            'veiculo_id': viagem.veiculo_id,
            'cliente': viagem.cliente,
            'endereco_saida': viagem.endereco_saida,
            'endereco_destino': viagem.endereco_destino,
            'data_inicio': data_inicio_formatada,  # Usar a string formatada
            'duracao_segundos': viagem.duracao_segundos,
            'custo': viagem.custo,
            'forma_pagamento': viagem.forma_pagamento,
            'status': viagem.status,
            'observacoes': viagem.observacoes,
            'motorista_nome': viagem.motorista.nome,
            'veiculo_placa': viagem.veiculo.placa,
            'veiculo_modelo': viagem.veiculo.modelo,
            'distancia_km': viagem.distancia_km,
            'horario_chegada': horario_chegada
        }
        viagens_data.append(viagem_dict)
    return render_template('iniciar_viagem.html', motoristas=motoristas, veiculos=veiculos, viagens=viagens_data, GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY)

@app.route('/editar_viagem/<int:viagem_id>', methods=['GET', 'POST'])
def editar_viagem(viagem_id):
    viagem = Viagem.query.get_or_404(viagem_id)
    if request.method == 'POST':
        try:
            viagem.motorista_id = request.form['motorista_id']
            viagem.veiculo_id = request.form['veiculo_id']
            viagem.cliente = request.form['cliente']
            viagem.endereco_saida = request.form['endereco_saida']
            viagem.endereco_destino = request.form['endereco_destino']
            viagem.data_inicio = datetime.strptime(request.form['data_inicio'], '%Y-%m-%dT%H:%M')
            viagem.custo = float(request.form['custo']) if request.form['custo'] else None
            viagem.forma_pagamento = request.form['forma_pagamento']
            viagem.status = request.form['status']
            viagem.observacoes = request.form['observacoes'] if request.form['observacoes'] else None

            if not validar_endereco(viagem.endereco_saida) or not validar_endereco(viagem.endereco_destino):
                flash('Endereço inválido. Por favor, insira endereços válidos.', 'error')
                return redirect(url_for('iniciar_viagem'))

            distancia_km, duracao_segundos = calcular_distancia_e_duracao(viagem.endereco_saida, viagem.endereco_destino)
            if distancia_km is None or duracao_segundos is None:
                flash('Não foi possível recalcular a distância ou duração.', 'error')
                return redirect(url_for('iniciar_viagem'))

            viagem.distancia_km = distancia_km
            viagem.duracao_segundos = duracao_segundos
            db.session.commit()
            flash('Viagem atualizada com sucesso!', 'success')
            return redirect(url_for('iniciar_viagem'))
        except Exception as e:
            logger.error(f"Erro ao editar viagem: {str(e)}")
            flash(f'Erro ao editar viagem: {str(e)}', 'error')
            return redirect(url_for('iniciar_viagem'))

    motoristas = Motorista.query.all()
    veiculos = Veiculo.query.filter_by(disponivel=True).all()
    viagens = Viagem.query.filter_by(data_fim=None).order_by(Viagem.data_inicio.desc()).all()
    # Preparar dados serializáveis para o JavaScript
    viagens_data = []
    for v in viagens:
        horario_chegada = (v.data_inicio + timedelta(seconds=v.duracao_segundos)).strftime('%d/%m/%Y %H:%M') if v.duracao_segundos else 'Não calculado'
        viagem_dict = {
            'id': v.id,
            'motorista_id': v.motorista_id,
            'veiculo_id': v.veiculo_id,
            'cliente': v.cliente,
            'endereco_saida': v.endereco_saida,
            'endereco_destino': v.endereco_destino,
            'data_inicio': v.data_inicio.strftime('%Y-%m-%dT%H:%M:%S'),
            'duracao_segundos': v.duracao_segundos,
            'custo': v.custo,
            'forma_pagamento': v.forma_pagamento,
            'status': v.status,
            'observacoes': v.observacoes,
            'motorista_nome': v.motorista.nome,
            'veiculo_placa': v.veiculo.placa,
            'veiculo_modelo': v.veiculo.modelo,
            'distancia_km': v.distancia_km,
            'horario_chegada': horario_chegada
        }
        viagens_data.append(viagem_dict)
    return render_template('iniciar_viagem.html', motoristas=motoristas, veiculos=veiculos, viagens=viagens_data, viagem_edit=viagem, GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY)

@app.route('/excluir_viagem/<int:viagem_id>')
def excluir_viagem(viagem_id):
    viagem = Viagem.query.get_or_404(viagem_id)
    try:
        if not viagem.data_fim:
            viagem.veiculo.disponivel = True
        db.session.delete(viagem)
        db.session.commit()
        flash('Viagem excluída com sucesso!', 'success')
    except Exception as e:
        logger.error(f"Erro ao excluir viagem: {str(e)}")
        flash(f'Erro ao excluir viagem: {str(e)}', 'error')
    return redirect(url_for('index'))

@app.route('/finalizar_viagem/<int:viagem_id>')
def finalizar_viagem(viagem_id):
    viagem = Viagem.query.get_or_404(viagem_id)
    if viagem.data_fim:
        flash('Erro: Viagem já finalizada.', 'error')
    else:
        viagem.data_fim = datetime.now()
        viagem.veiculo.disponivel = True
        viagem.status = 'concluida'
        db.session.commit()
        flash('Viagem finalizada com sucesso!', 'success')
    return redirect(url_for('index'))

@app.route('/consultar_viagens')
def consultar_viagens():
    viagens = Viagem.query.order_by(Viagem.data_inicio.desc()).all()
    viagens_data = []
    for v in viagens:
        horario_chegada = (v.data_inicio + timedelta(seconds=v.duracao_segundos)).strftime('%d/%m/%Y %H:%M') if v.duracao_segundos and not v.data_fim else 'Concluída'
        viagem_dict = {
            'id': v.id,
            'motorista_nome': v.motorista.nome,
            'veiculo_placa': v.veiculo.placa,
            'veiculo_modelo': v.veiculo.modelo,
            'cliente': v.cliente,
            'endereco_saida': v.endereco_saida,
            'endereco_destino': v.endereco_destino,
            'data_inicio': v.data_inicio.strftime('%d/%m/%Y %H:%M'),
            'data_fim': v.data_fim.strftime('%d/%m/%Y %H:%M') if v.data_fim else 'Em andamento',
            'duracao_segundos': v.duracao_segundos,
            'custo': v.custo,
            'forma_pagamento': v.forma_pagamento,
            'status': v.status,
            'observacoes': v.observacoes,
            'horario_chegada': horario_chegada
        }
        viagens_data.append(viagem_dict)
    return render_template('consultar_viagens.html', viagens=viagens_data)

@app.route('/consultar_motoristas')
def consultar_motoristas():
    motoristas = Motorista.query.all()
    return render_template('consultar_motoristas.html', motoristas=motoristas)

@app.route('/get_active_trip')
def get_active_trip():
    viagem = Viagem.query.filter_by(data_fim=None, status='em_andamento').first()
    if viagem:
        horario_chegada = (viagem.data_inicio + timedelta(seconds=viagem.duracao_segundos)).strftime('%d/%m/%Y %H:%M') if viagem.duracao_segundos else 'Não calculado'
        trip_data = {
            'trip': {
                'motorista_nome': viagem.motorista.nome,
                'veiculo_placa': viagem.veiculo.placa,
                'veiculo_modelo': viagem.veiculo.modelo,
                'endereco_saida': viagem.endereco_saida,
                'endereco_destino': viagem.endereco_destino,
                'horario_chegada': horario_chegada
            }
        }
        return jsonify(trip_data)
    return jsonify({'trip': None})

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)