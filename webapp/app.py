# botloteria/webapp/app.py

from flask import Flask, render_template, request, jsonify, redirect, url_for
import sys
import os

# Añadir la ruta al directorio src para que Python pueda encontrar tus módulos
# Esto asume que el script se ejecuta desde la raíz del proyecto o que la raíz del proyecto
# está en la ruta de Python. Mantener esta línea es útil.
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Importar tus módulos existentes usando rutas absolutas desde la raíz del proyecto
# (Asumiendo que el directorio 'src' es un paquete Python y está accesible)
# Asegúrate de importar explícitamente las funciones o clases que necesitas de src.db
from src.db import ( # <-- Corregido: importación absoluta
    get_or_create_user,
    # Agrega aquí cualquier otra función que necesites de src.db
    # Por ejemplo, si implementaste get_finished_rounds_with_winners en db.py, impórtala aquí:
    # get_finished_rounds_with_winners,
)
import src.round_manager as round_manager # <-- Corregido: importación absoluta, usamos alias para mantener el código subsiguiente igual
import src.payment_manager as payment_manager # <-- Corregido: importación absoluta, usamos alias si se necesita payment_manager

# Importar constantes necesarias
# Asumiendo que MIN_PARTICIPANTS está definido en round_manager.py y quieres importarlo directamente
from src.round_manager import MIN_PARTICIPANTS # <-- Corregido: importación absoluta


app = Flask(__name__)

# --- Rutas para servir el frontend (HTML) ---

@app.route('/')
def index():
    # Renderiza tu archivo HTML principal (webapp/templates/index.html)
    # Flask busca templates por defecto en una carpeta 'templates' dentro del directorio de la app Flask
    return render_template('index.html')

# --- Rutas API para que el frontend interactúe con la lógica del bot ---

@app.route('/api/winners', methods=['GET'])
def get_winners():
    """Retorna la lista de ganadores recientes."""
    # --- Implementa la lógica real para obtener ganadores de tu base de datos ---
    # Necesitas una función en src.db (o src.payment_manager) que consulte la tabla draw_results
    # y users para obtener los ganadores recientes y sus premios simulados.
    # Ejemplo (debes implementar get_finished_rounds_with_winners en src/db.py):
    # try:
    #     winners_list = get_finished_rounds_with_winners(limit=50) # Llama a tu función implementada en src/db.py
    # except Exception as e:
    #     app.logger.error(f"Error al obtener ganadores: {e}")
    #     # Podrías retornar un error al frontend
    #     return jsonify({"error": "Error al cargar ganadores"}), 500

    # !!! TEMPORAL: Usando datos simulados si no has implementado la función get_finished_rounds_with_winners !!!
    # Borra esto una vez que implementes la función real en src/db.py
    winners_list = [
        {'round_id': 5, 'winner': '@Usuario1', 'prize': '4 unidades'},
        {'round_id': 5, 'winner': '@Usuario2', 'prize': '3 unidades'},
        {'round_id': 6, 'winner': '@UsuarioA', 'prize': '1 unidad'},
        # Agrega más datos simulados si quieres, o remueve esto al implementar la función real
    ]
    # !!! FIN TEMPORAL !!!


    return jsonify(winners_list)


@app.route('/api/open_rounds', methods=['GET'])
def get_open_rounds():
    """Retorna la lista de rondas abiertas con count de participantes."""
    # Llama a la función en round_manager.py
    # get_available_rounds() retorna (id, start_time, status, round_type, simulated_contract_address)
    try:
        open_rounds_data = round_manager.get_available_rounds() # Llama a tu función en src/round_manager.py
    except Exception as e:
         app.logger.error(f"Error al obtener rondas abiertas: {e}")
         return jsonify({"error": "Error al cargar rondas"}), 500


    formatted_rounds = []
    for ronda in open_rounds_data:
        if len(ronda) >= 5: # Asegurarse de que la tupla tiene el formato esperado
             # Desempaquetamos los datos de la ronda
             ronda_id, start_time, status, round_type, simulated_contract_address = ronda
             try:
                 # Llama a la función en round_manager.py para contar participantes
                 participants_count = round_manager.count_round_participants(ronda_id) # Llama a tu función en src/round_manager.py

                 formatted_rounds.append({
                     'id': ronda_id,
                     'type': round_type.replace('_', ' ').title(),
                     'status': status.replace('_', ' ').title(),
                     'participants': f"{participants_count}/{MIN_PARTICIPANTS}", # Usar la constante MIN_PARTICIPANTS
                     'start_time': start_time, # Puedes formatear la fecha/hora si quieres
                     'simulated_contract_address': simulated_contract_address,
                     # URL para compartir la ronda (deep link). Reemplaza YOUR_BOT_USERNAME con el @ de tu bot.
                     'share_url': f"https://t.me/@TONLottoMasterBot?start=join_round_{ronda_id}" # <-- ¡¡¡REEMPLAZA YOUR_BOT_USERNAME!!!
                 })
             except Exception as e:
                 app.logger.error(f"Error al procesar ronda {ronda_id} para API: {e}")
                 # Opcional: añadir un marcador de error para esta ronda en la lista
                 formatted_rounds.append({'id': ronda_id, 'error': 'Error al cargar detalles'})


        else:
             app.logger.error(f"get_available_rounds devolvió tupla inesperada: {ronda}")
             # Opcional: añadir un marcador de error para esta ronda en la lista
             formatted_rounds.append({'id': ronda[0] if len(ronda)>0 else '?', 'error': 'Formato de datos inesperado'})


    return jsonify(formatted_rounds)

@app.route('/api/join_round/<int:round_id>', methods=['POST'])
def join_round(round_id):
    """Maneja la solicitud para unirse a una ronda."""
    # Para unirse desde la Web App, necesitas obtener el telegram_id y username del usuario
    # de los datos pasados por Telegram Web App (Telegram.WebApp.initDataUnsafe o Telegram.WebApp.initData).
    # El frontend (index.html) debe enviar estos datos en el cuerpo de la solicitud POST.
    data = request.get_json()
    user_id_str = data.get('telegram_id') # Esperando 'telegram_id' en el JSON de la solicitud
    username = data.get('username') # Esperando 'username' en el JSON de la solicitud

    # *** NOTA DE SEGURIDAD ***
    # En producción, si la seguridad es crítica, DEBES validar Telegram.WebApp.initData
    # en el backend para asegurar que los datos del usuario son auténticos y no han sido manipulados.
    # Esto implica verificar la firma hash de Telegram.WebApp.initData.
    # Telegram proporciona documentación sobre cómo hacer esto. initDataUnsafe NO DEBE USARSE PARA LÓGICA SENSIBLE.
    # Por simplicidad en este MVP, usamos user_id y username directamente del frontend,
    # pero ten en cuenta este riesgo de seguridad para una implementación real.
    # Puedes obtener initDataUnsafe en el frontend con `tg.initDataUnsafe` y pasarlo aquí.
    # Luego, en el backend, parseas y verificas `initData`.

    if not user_id_str or not username:
         # Si faltan datos necesarios del usuario en la solicitud del frontend
         app.logger.warning("Solicitud /api/join_round sin telegram_id o username en el JSON.")
         return jsonify({'success': False, 'message': 'Error: Falta información del usuario.'}), 400

    try:
        # Asegurarse de que el usuario existe en la DB (llama a tu función en src/db.py)
        get_or_create_user(user_id_str, username) # Llama a tu función implementada

        # Llama a tu función existente en round_manager para añadir participante.
        # add_participant(round_id, telegram_id, username) retorna (success: bool, message: str, assigned_number: int | None, current_participants_count: int)
        success, message, assigned_number, current_participants_count = round_manager.add_participant(round_id, user_id_str, username) # Llama a tu función en src/round_manager.py

        # La respuesta de la API debe indicar éxito/fracaso y un mensaje para el frontend
        return jsonify({
            'success': success,
            'message': message, # Envía el mensaje generado por tu lógica existente (ej: "¡Te has unido!")
            'assigned_number': assigned_number,
            'current_participants_count': current_participants_count
        })

    except Exception as e:
        app.logger.error(f"Error inesperado en /api/join_round para user {user_id_str}, round {round_id}: {e}")
        return jsonify({'success': False, 'message': 'Ocurrió un error interno al unirse a la ronda.'}), 500 # Internal Server Error


@app.route('/api/create_round', methods=['POST'])
def create_round_api(): # Renombrada para no confundir con la función create_round del módulo round_manager
    """Maneja la solicitud para crear una nueva ronda."""
    # Similar a JOIN, necesitas obtener el user_id y username del creador desde la Web App.
    data = request.get_json()
    user_id_str = data.get('telegram_id') # Esperando 'telegram_id' en el JSON de la solicitud
    username = data.get('username') # Esperando 'username' en el JSON de la solicitud

    # *** NOTA DE SEGURIDAD ***
    # Validar initData aquí si la seguridad es crítica.

    if not user_id_str or not username:
         app.logger.warning("Solicitud /api/create_round sin telegram_id o username en el JSON.")
         return jsonify({'success': False, 'message': 'Error: Falta información del usuario.'}), 400

    try:
        get_or_create_user(user_id_str, username) # Asegurarse de que el usuario existe

        # Llama a tu función existente en round_manager para crear la ronda.
        # create_round(round_type='user_created', creator_telegram_id=user_id_str) retorna round_id | None
        round_id = round_manager.create_round(round_type='user_created', creator_telegram_id=user_id_str) # Llama a tu función en src/round_manager.py
        # Puedes hacer que el tipo de ronda sea un parámetro en la solicitud POST si quieres que la Web App cree diferentes tipos

        if round_id:
            # Opcional: Obtener la dirección simulada de la ronda recién creada para la respuesta
            created_round_data = round_manager.get_round(round_id) # Llama a round_manager
            simulated_contract_address = created_round_data[7] if created_round_data and len(created_round_data) >= 8 else None

            # Generar la URL para compartir la ronda
            # Reemplaza YOUR_BOT_USERNAME con el @ de tu bot
            share_url = f"https://t.me/@TONLottoMasterBot?start=join_round_{round_id}" # <-- ¡¡¡REEMPLAZA YOUR_BOT_USERNAME!!!


            # Retornar éxito y detalles de la ronda creada
            return jsonify({
                'success': True,
                'round_id': round_id,
                'simulated_contract_address': simulated_contract_address,
                'share_url': share_url, # Incluir la URL de compartir en la respuesta
                'message': f"Ronda personal creada con ID {round_id}." # Mensaje simple para el frontend
            })
        else:
            # Si create_round retornó None (falló la creación en DB)
            return jsonify({
                'success': False,
                'message': "Error al crear la ronda."
            }), 500 # Internal Server Error

    except Exception as e:
         app.logger.error(f"Error inesperado en /api/create_round para user {user_id_str}: {e}")
         return jsonify({'success': False, 'message': 'Ocurrió un error interno al crear la ronda.'}), 500 # Internal Server Error


# --- Cómo ejecutar la aplicación Flask (Solo para desarrollo/pruebas) ---
if __name__ == '__main__':
    # Asegúrate de que tu base de datos esté inicializada.
    # Puedes llamarla aquí si la webapp se inicia independientemente del bot principal.
    # Si el bot principal ya inicializa la DB y no se reinicia, es probable que ya exista.
    # db.init_db() # Opcional: Llama a init_db si la webapp puede iniciar sin que el bot lo haga primero


    # Para desarrollo, puedes usar el servidor de desarrollo de Flask.
    # En producción, usarías un servidor WSGI más robusto como Gunicorn o uWSGI.
    # app.run(debug=True, port=5000)

    # Para que flask run funcione correctamente, debes establecer la variable de entorno FLASK_APP
    # y ejecutar 'flask run' desde el directorio raíz del proyecto.
    # Las líneas de abajo solo se ejecutarían si corres este script directamente,
    # lo cual NO es la forma recomendada de correr la app Flask dentro del paquete.
    # La forma correcta es:
    # export FLASK_APP=webapp.app  # o set FLASK_APP=webapp.app en Windows cmd
    # flask run --debug
    pass # Eliminamos la llamada a app.run aquí ya que se ejecuta vía 'flask run'