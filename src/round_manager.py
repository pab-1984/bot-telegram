# botloteria/src/round_manager.py

import logging
from datetime import datetime

# Importar las funciones de base de datos de bajo nivel
from .db import (
    create_new_round as db_create_new_round,
    get_active_round as db_get_active_round,
    get_round_by_id as db_get_round_by_id,
    get_open_rounds as db_get_open_rounds,
    add_participant_to_round as db_add_participant_to_round,
    count_participants_in_round as db_count_participants_in_round,
    update_round_status as db_update_round_status,
    mark_round_as_deleted as db_mark_round_as_deleted,
    get_participants_in_round as db_get_participants_in_round,
    update_participant_paid_status as db_update_participant_paid_status # <-- Importar esta función para marcar pago
)

logger = logging.getLogger(__name__)

# --- Constantes de Ronda ---
# Mínimo de participantes para que una ronda *pueda* sortearse por tiempo
MIN_PARTICIPANTS_FOR_TIMED_DRAW = 2
# Máximo de participantes para sorteo inmediato
MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW = 10

# El MIN_PARTICIPANTS original (10) ahora representa el límite máximo de participantes.
MIN_PARTICIPANTS = 10 # Límite máximo de participantes
DRAW_NUMBERS_COUNT = 1 # Número de números sorteados (siempre 1)

ROUND_STATUS_WAITING_TO_START = 'waiting_to_start'
ROUND_STATUS_WAITING_FOR_PAYMENTS = 'waiting_for_payments' # Este estado se usa brevemente antes de 'drawing'
ROUND_STATUS_DRAWING = 'drawing'
ROUND_STATUS_FINISHED = 'finished'
ROUND_STATUS_CANCELLED = 'cancelled'
ROUND_TYPE_SCHEDULED = 'scheduled'
ROUND_TYPE_BOT_CREATED = 'scheduled' # Alias
ROUND_TYPE_USER_CREATED = 'user_created'


# --- Funciones de Gestión de Rondas de Alto Nivel ---

def create_round(round_type: str = ROUND_TYPE_SCHEDULED, creator_telegram_id: str = None) -> int | None:
    """
    Crea una nueva ronda llamando a la función de base de datos.
    Retorna el ID de la nueva ronda o None.
    """
    logger.info(f"Intentando crear nueva ronda de tipo '{round_type}' (Creador: {creator_telegram_id}).")
    round_id = db_create_new_round(round_type, creator_telegram_id)
    if round_id:
        logger.info(f"Ronda creada exitosamente con ID: {round_id}.")
    else:
        logger.error("Falló la creación de la ronda en la base de datos.")
    return round_id

def get_current_active_round() -> tuple | None:
    """
    Obtiene la ronda activa actual (esperando participantes o pagos).
    Llama a la función de base de datos.
    Retorna los datos de la ronda o None.
    """
    logger.debug("Buscando ronda activa actual.")
    return db_get_active_round()

def get_round(round_id: int) -> tuple | None:
    """
    Obtiene los datos de una ronda específica por su ID.
    Llama a la función de base de datos.
    Retorna los datos de la ronda o None.
    """
    logger.debug(f"Buscando ronda por ID: {round_id}.")
    return db_get_round_by_id(round_id)

def get_available_rounds() -> list[tuple]:
    """
    Obtiene una lista de rondas abiertas (esperando participantes o pagos).
    Llama a la función de base de datos.
    Retorna una lista de rondas.
    """
    logger.debug("Buscando rondas abiertas.")
    return db_get_open_rounds()

def add_participant(round_id: int, telegram_id: str, username: str) -> tuple:
    """
    Intenta añadir un usuario como participante a una ronda.
    Asigna el siguiente número disponible y lo marca como pagado.
    Retorna (éxito: bool, mensaje: str, assigned_number: int | None, current_participants_count: int)
    """
    logger.info(f"Intentando añadir participante {telegram_id} ({username}) a ronda {round_id}.")

    # Verificar si la ronda existe y está abierta
    ronda_data = get_round(round_id)
    if not ronda_data:
         logger.error(f"Intento de añadir participante a ronda inexistente: {round_id}.")
         return False, "Error interno: La ronda especificada no existe.", None, 0


    # Desempaquetamos para verificar estado y si está eliminada
    ronda_id_db, _, _, status, _, _, deleted, _ = ronda_data
    # La ronda está abierta si está en waiting_to_start O waiting_for_payments (para permitir unirse si llegó a 10 pero aún no sorteó)
    if deleted or status not in [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS]:
         logger.warning(f"Intento de añadir participante {telegram_id} a ronda no abierta {round_id} (Estado: {status}, Eliminada: {deleted}).")
         return False, f"⚠️ La ronda ID {round_id} no está abierta para unirse.", None, 0


    current_participants_count = count_round_participants(round_id)

    # Verificar si la ronda ya está llena (máximo 10 participantes)
    if current_participants_count >= MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW: # Comparar con el máximo (10)
        logger.warning(f"Intento de añadir participante {telegram_id} a ronda llena {round_id}.")
        return False, f"⚠️ La ronda ID {round_id} ya está llena ({current_participants_count}/{MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW}).", None, current_participants_count


    # Asignar el siguiente número disponible (basado en la cuenta actual)
    assigned_number = current_participants_count + 1

    # Añadir el participante a la base de datos
    # db_add_participant_to_round retorna True si la inserción fue exitosa, False si ya existía (UNIQUE constraint)
    success_add_db = db_add_participant_to_round(round_id, telegram_id, assigned_number)

    if success_add_db:
        # --- Marcar al participante como pagado inmediatamente al unirse ---
        # paid_real = True indica que ha "comprado el boleto" simulado.
        # update_participant_paid_status llama a db.py
        success_update_paid = db_update_participant_paid_status(round_id, telegram_id, paid_real=True) # <-- Marcar como pagado

        if success_update_paid:
            current_participants_count += 1 # Incrementar la cuenta local solo si se añadió y marcó como pagado
            logger.info(f"Participante {telegram_id} añadido y marcado como pagado en ronda {round_id}. Número asignado: {assigned_number}. Total: {current_participants_count}.")
            # Mensaje de éxito actualizado para reflejar que el pago es al unirse
            return True, f"✅ ¡Te has unido a la ronda ID <code>{round_id}</code> y has comprado tu boleto! Tu número asignado es el <b>{assigned_number}</b>.\nParticipantes: {current_participants_count}/10.", assigned_number, current_participants_count
        else:
             # Si falla la actualización de paid_real (muy improbable si add_participant_to_round fue True)
             logger.error(f"Falló la actualización de paid_real para participante {telegram_id} en ronda {round_id} después de añadirlo.")
             # Considera si deberías borrar el participante insertado o dejarlo. Por ahora, retornamos error.
             return False, f"❌ Error interno al marcar tu pago para ronda {round_id}. Contacta al administrador.", None, current_participants_count


    else:
        # Esto ocurre si db_add_participant_to_round devuelve False (usuario ya en ronda - UNIQUE constraint)
        logger.warning(f"Participante {telegram_id} ya estaba unido a ronda {round_id}.")
        # Obtener el número asignado y el estado de pago actual para el mensaje
        participants_in_round = db_get_participants_in_round(round_id) # Llama a db.py
        existing_participant_data = next((p for p in participants_in_round if str(p[0]) == str(telegram_id)), None)
        if existing_participant_data:
             assigned_num = existing_participant_data[2]
             is_paid = existing_participant_data[4] # p[4] es paid_real
             status_msg = "y tu boleto está comprado." if is_paid else "pero tu pago aún no está registrado." # Aunque ahora siempre es true
             return False, f"⚠️ Ya estás unido a la ronda ID <code>{round_id}</code> con el número <b>{assigned_num}</b>, {status_msg}", assigned_num, current_participants_count
        else:
             # Esto no debería pasar si ya estaba en la base de datos, pero por seguridad
             return False, f"⚠️ Ya estás unido a la ronda ID <code>{round_id}</code>.", None, current_participants_count


def count_round_participants(round_id: int) -> int:
    """
    Cuenta el número de participantes en una ronda específica llamando a la función de base de datos.
    """
    logger.debug(f"Contando participantes para ronda {round_id}.")
    return db_count_participants_in_round(round_id)

def get_round_participants_data(round_id: int) -> list[tuple]:
    """
    Obtiene los datos completos de los participantes en una ronda llamando a la función de base de datos.
    Retorna una lista de tuplas (telegram_id, username, assigned_number, paid_simulated, paid_real).
    """
    logger.debug(f"Obteniendo datos de participantes para ronda {round_id}.")
    return db_get_participants_in_round(round_id)


def update_round_status_manager(round_id: int, new_status: str) -> bool:
    """
    Actualiza el estado de una ronda llamando a la función de base de datos.
    Retorna True/False.
    """
    logger.info(f"Actualizando estado de ronda {round_id} a '{new_status}'.")
    return db_update_round_status(round_id, new_status)

def mark_round_for_deletion(round_id: int) -> bool:
    """
    Marca una ronda para su eliminación lógica llamando a la función de base de datos.
    Retorna True/False.
    """
    logger.info(f"Marcando ronda {round_id} para eliminación.")
    return db_mark_round_as_deleted(round_id)