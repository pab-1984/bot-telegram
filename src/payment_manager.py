# botloteria/src/payment_manager.py

import logging
from datetime import datetime
import hashlib
import math # Necesario para floor
import sqlite3 # Importar sqlite3 para manejar transacciones aquí

# Importar funciones de base de datos necesarias para la gestión de pagos/resultados
from .db import (
    # update_participant_paid_status, # <-- Ya no la usamos aquí, la usa round_manager
    # count_paid_participants_in_round, # <-- Ya no la usamos aquí, el cálculo se basa en la lista pasada
    save_draw_results,
    save_creator_commission as db_save_creator_commission, # <-- Renombramos para no confundir
    get_db_connection # <-- Importar la función para obtener conexión
    # generate_simulated_smart_contract_address # <-- Ya no la usamos aquí, la usa db.py
)

# Importar constantes de ronda desde round_manager.py
from .round_manager import (
    MIN_PARTICIPANTS_FOR_TIMED_DRAW, # Mínimo 2
    MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW, # Máximo 10
    # ROUND_STATUS_WAITING_FOR_PAYMENTS, # No se usa aquí
    # ROUND_STATUS_DRAWING, # No se usa aquí
    # ROUND_STATUS_CANCELLED, # No se usa aquí
    # ROUND_STATUS_FINISHED, # No se usa aquí
    ROUND_TYPE_BOT_CREATED, # Necesario para lógica de comisión
    ROUND_TYPE_USER_CREATED, # Necesario para lógica de comisión
    # DRAW_NUMBERS_COUNT # No se usa aquí
)


logger = logging.getLogger(__name__)

# --- Constantes de Porcentajes y Distribución Simuladas Dinámicas ---
# Aplicadas al total recaudado (Número de Participantes Unidos * 1 unidad de entrada).

# Porcentajes de Comisión Fija (simulados)
COMMISSION_PERCENT_GAS_SIMULATED = 0.10 # 10% para gas simulado
COMMISSION_PERCENT_BOT = 0.10 # 10% para la comisión del bot (tú)
COMMISSION_PERCENT_USER_CREATOR = 0.05 # 5% para el creador de ronda (solo en rondas de usuario)

# Porcentajes de Distribución del Pozo de Premios entre Ganadores (SUMAN 1.0 = 100% del Pozo de Premios)
# Definimos la distribución entre el 100% del Pozo de Premios disponible.
PRIZE_SPLIT_1_WINNER = [1.0] # [100% para el 1er] (para 2-3 participantes)
PRIZE_SPLIT_2_WINNERS = [0.70, 0.30] # [70% 1er, 30% 2do] (para 4-6 participantes)
PRIZE_SPLIT_3_WINNERS = [0.50, 0.30, 0.20] # [50% 1er, 30% 20%, 20% 3er] (para 7-9 participantes)
PRIZE_SPLIT_4_WINNERS = [0.40, 0.30, 0.20, 0.10] # [40% 1er, 30% 2do, 20% 3er, 10% 4to] (para 10 participantes)


# --- Funciones de Gestión de Pagos de Alto Nivel (Simuladas) ---

# handle_simulated_payment_confirmation ya no es necesario para la confirmación inicial.
# Lo eliminamos para reflejar el flujo simplificado.
# def handle_simulated_payment_confirmation(...): pass


def perform_payout_calculation_and_save(round_id: int, drawn_numbers: list[int], participants_data: list[tuple], round_type: str, creator_id: str | None) -> tuple[list[str], list[str]]:
    """
    Calcula los premios y comisiones simuladas para una ronda finalizada.
    La distribución depende del número de participantes UNIDOS (y pagados automáticamente).
    Guarda los resultados y comisiones en la base de datos DENTRO DE UNA SOLA TRANSACCIÓN PARA COMISIONES.
    Retorna listas de strings con la información de ganadores y comisiones para mensajes.

    Args:
        round_id: ID de la ronda.
        drawn_numbers: Lista de números sorteados (en la nueva lógica, solo 1).
        participants_data: Lista de tuplas (telegram_id, username, assigned_number, paid_simulated, paid_real) de TODOS los participantes UNIDOS.
        round_type: Tipo de ronda ('scheduled' o 'user_created').
        creator_id: ID del creador si es ronda de usuario, None si es programada.

    Retorna:
        Tupla con dos listas de strings: ([mensajes_ganadores], [mensajes_comisiones]).
    """
    logger.debug(f"--> INICIO perform_payout_calculation_and_save para ronda {round_id} (Tipo: {round_type}) <--");

    # Número real de participantes UNIDOS (quienes son considerados pagados al unirse).
    current_participants_count = len(participants_data)

    # Verificar que el número de participantes UNIDOS esté en el rango válido (2-10) para este sorteo.
    # La lógica de gatillar el sorteo en handlers/job ya debería asegurar esto.
    if current_participants_count < MIN_PARTICIPANTS_FOR_TIMED_DRAW or current_participants_count > MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW:
         logger.error(f"Intento de calcular pagos para ronda {round_id} con número inválido de participantes unidos: {current_participants_count}.")
         return [], ["Error: Número inválido de participantes unidos para cálculo de pagos."]


    # El número de entradas es igual al número de participantes UNIDOS (1 unidad por entrada)
    total_collected_simulated = float(current_participants_count) # Usamos float para los cálculos base

    # --- Calcular Montos de Comisiones Fijas (basados en Porcentajes del Total Recaudado) ---
    commissions_to_save = []
    commissions_list_for_message = []

    # Monto de Comisión de Gas Simulada (siempre se extrae)
    gas_commission_amount = total_collected_simulated * COMMISSION_PERCENT_GAS_SIMULATED
    commissions_to_save.append({
        'creator_type': 'gas_fee',
        'creator_telegram_id': None,
        'amount_simulated': f"{gas_commission_amount:.2f} unidades", # Formatear a 2 decimales
        'amount_real': gas_commission_amount
    })
    # Añadir a la lista de mensajes de comisiones para mostrar al usuario
    commissions_list_for_message.append(f"- Fondo para Gas Simulado ({int(COMMISSION_PERCENT_GAS_SIMULATED*100)}% del Total): {gas_commission_amount:.2f} unidades")


    # Monto de Comisión del Bot (siempre se extrae)
    bot_commission_amount = total_collected_simulated * COMMISSION_PERCENT_BOT
    commissions_to_save.append({
        'creator_type': 'bot',
        'creator_telegram_id': None,
        'amount_simulated': f"{bot_commission_amount:.2f} unidades",
        'amount_real': bot_commission_amount
    })
    # Añadir a la lista de mensajes
    commissions_list_for_message.append(f"- Comisión Bot (Tú) ({int(COMMISSION_PERCENT_BOT*100)}% del Total): {bot_commission_amount:.2f} unidades")


    # Monto de Comisión del Usuario Creador (solo en rondas de usuario)
    user_creator_commission_amount = 0.0 # Inicializar a 0
    if round_type == ROUND_TYPE_USER_CREATED and creator_id:
        user_creator_commission_amount = total_collected_simulated * COMMISSION_PERCENT_USER_CREATOR
        commissions_to_save.append({
            'creator_type': 'user',
            'creator_telegram_id': creator_id,
            'amount_simulated': f"{user_creator_commission_amount:.2f} unidades",
            'amount_real': user_creator_commission_amount
        })
        # Obtener el username del creador para el mensaje. Buscar en la lista de participantes UNIDOS.
        creator_username = next((p[1] for p in participants_data if str(p[0]) == str(creator_id)), 'desconocido')
        commissions_list_for_message.append(f"- Comisión Creador (@{creator_username}) ({int(COMMISSION_PERCENT_USER_CREATOR*100)}% del Total): {user_creator_commission_amount:.2f} unidades")


    # --- Calcular Pozo para Premios y Monto Total Disponible para Premios ---
    # Suma total de los montos de comisiones fijas calculados
    total_fixed_commission_amount = gas_commission_amount + bot_commission_amount + user_creator_commission_amount # user_creator_commission_amount es 0 si no aplica

    # Monto total disponible para premios
    prize_pool_for_winners_amount = total_collected_simulated - total_fixed_commission_amount
    # Asegurarse de que el pozo para premios no sea negativo
    prize_pool_for_winners_amount = max(0.0, prize_pool_for_winners_amount)

    logger.debug(f"Total recaudado: {total_collected_simulated:.2f}, Total comisiones fijas: {total_fixed_commission_amount:.2f}, Pozo para Premios: {prize_pool_for_winners_amount:.2f}")


    # --- Determinar Número de Ganadores (N) y Distribución del Pozo entre ellos ---
    # Basado en el número de participantes UNIDOS.
    prize_split_percentages = []
    num_winners_to_announce = 0

    if current_participants_count >= MIN_PARTICIPANTS_FOR_TIMED_DRAW and current_participants_count <= 3: # 2 a 3
        prize_split_percentages = PRIZE_SPLIT_1_WINNER
        num_winners_to_announce = 1
    elif current_participants_count >= 4 and current_participants_count <= 6:
        prize_split_percentages = PRIZE_SPLIT_2_WINNERS
        num_winners_to_announce = 2
    elif current_participants_count >= 7 and current_participants_count <= 9:
        prize_split_percentages = PRIZE_SPLIT_3_WINNERS
        num_winners_to_announce = 3
    elif current_participants_count == 10:
        prize_split_percentages = PRIZE_SPLIT_4_WINNERS
        num_winners_to_announce = 4
    else:
         # Esto no debería pasar si la verificación de gatillar sorteo es correcta
         logger.error(f"Número de participantes unidos ({current_participants_count}) fuera de rango (2-10) para asignar distribución de premios en ronda {round_id}.")
         return [], commissions_list_for_message # Retornamos comisiones pero sin ganadores


    winners_info_for_db = [] # Para guardar resultados en DB
    winners_list_for_message = [] # Para el mensaje de Telegram


    # --- Asignar Premios a los Ganadores Sorteados ---
    # En la nueva lógica, solo se sortea 1 número.
    # El premio se aplica al ÚNICO ganador del número sorteado.

    if not drawn_numbers or len(drawn_numbers) == 0:
         logger.error(f"No se sortearon números para ronda {round_id}. No hay ganador.")
         # winners_list_for_message ya está vacía.
         # winners_info_for_db ya está vacía.
         # No hay premio que guardar si no hay número sorteado.
    else:
        drawn_winner_number = drawn_numbers[0] # El único número sorteado

        # Buscar al participante UNIDO cuyo número asignado coincide con el número sorteado
        participant_data_winner = next((p for p in participants_data if p[2] == drawn_winner_number), None) # p[2] es assigned_number

        if participant_data_winner:
             winner_user_id = participant_data_winner[0] # telegram_id
             winner_username = participant_data_winner[1] # username

             # El premio para el único ganador es el 100% del Pozo de Premios calculado.
             prize_amount = prize_pool_for_winners_amount
             prize_amount_simulated_text = f"{prize_amount:.2f} unidades" # Formatear el monto


             # Preparar info para el mensaje y la base de datos
             # Mensaje para el único ganador
             # Incluimos el porcentaje del pozo que ganó (100% si solo hay 1 ganador real)
             winners_list_for_message.append(f"- @{winner_username} (Número {drawn_winner_number}): Gana {prize_amount_simulated_text} (100% del Pozo de Premios)")

             # Info para guardar en la base de datos (un solo registro para el ganador)
             winners_info_for_db.append({
                'drawn_number': drawn_winner_number,
                'draw_order': 0, # Es el 1er y único ganador real
                'winner_telegram_id': winner_user_id,
                'prize_amount_simulated': prize_amount_simulated_text,
                'prize_amount_real': prize_amount # Guardamos el monto numérico simulado
             })
        else:
             # Si el número sorteado no tiene un participante UNIDO asignado (no debería pasar si el sorteo toma de available_numbers)
             logger.warning(f"Número sorteado {drawn_winner_number} no tiene participante UNIDO en ronda {round_id}. Nadie gana el pozo de premios.")
             # No se añade nada a winners_list_for_message ni winners_info_for_db si no hay ganador.


    # --- Guardar los resultados del sorteo en la base de datos ---
    if winners_info_for_db: # Solo guardar si hay información de ganadores a guardar (al menos 1)
         save_draw_results(round_id, winners_info_for_db)
         logger.info(f"Resultados del sorteo guardados en DB para ronda {round_id}.")
    else:
         logger.warning(f"No hay información de ganadores para guardar para ronda {round_id}.")


    # --- Guardar Comisiones Simuladas DENTRO DE UNA TRANSACCIÓN ---
    logger.debug(f"Comisiones calculadas para guardar para ronda {round_id}: {commissions_to_save}") # Log de depuración

    conn = None # Inicializar conexión a None
    try:
        conn = get_db_connection() # Obtener una conexión para la transacción
        cursor = conn.cursor() # Obtener un cursor de la conexión

        # Iterar sobre la lista de diccionarios de comisiones calculadas y guardarlas.
        # db_save_creator_commission espera un cursor y relanza IntegrityError.
        for commission_info in commissions_to_save:
            # Intentar ejecutar la inserción de cada comisión.
            # Si hay un IntegrityError (duplicado) o cualquier otro error SQLite, la transacción fallará.
            try:
                db_save_creator_commission( # <-- Llamamos a la función db_save_creator_commission con el cursor
                    cursor, # <-- Pasamos el cursor
                    round_id=round_id,
                    creator_type=commission_info['creator_type'],
                    creator_telegram_id=commission_info['creator_telegram_id'],
                    amount_simulated=commission_info['amount_simulated'],
                    amount_real=commission_info['amount_real'],
                    transaction_id=None # Simulado por ahora
                )
                # db_save_creator_commission ya loguea debug y warning por IntegrityError
            except sqlite3.IntegrityError as e:
                 # Si ocurre IntegrityError al guardar una comisión específica, logueamos y relanzamos para deshacer la transacción.
                 logger.warning(f"Integrity Error (duplicado) al guardar comisión {commission_info.get('creator_type', 'desconocido')} para ronda {round_id}: {e}")
                 raise # Relanzamos la excepción para que sea capturada por el bloque except más externo.

            except sqlite3.Error as e:
                 # Capturar cualquier otro error de base de datos en la inserción individual.
                 logger.error(f"Error SQLite al guardar comisión {commission_info.get('creator_type', 'desconocido')} para ronda {round_id}: {e}")
                 raise # Relanzamos la excepción para que sea capturada por el bloque except más externo.


        # Si todas las inserciones se ejecutaron sin lanzar excepciones, confirmar la transacción.
        conn.commit() # Confirmar la transacción si no hubo errores
        logger.debug(f"Transacción de guardado de comisiones para ronda {round_id} completada.")

    except sqlite3.IntegrityError as e:
         # Este bloque captura IntegrityError relanzado por db_save_creator_commission.
         # Si ANY inserción falló por IntegrityError, se llega aquí.
         logger.error(f"Error de integridad al guardar comisiones para ronda {round_id}. Transacción deshecha: {e}")
         if conn: conn.rollback() # Deshacer toda la transacción si hubo un error de integridad
         # No retornamos False, solo logueamos el error.

    except sqlite3.Error as e:
         # Capturar cualquier otro error SQLite durante la transacción (si no fue capturado en el bucle individual).
         logger.error(f"Error SQLite durante la transacción de comisiones para ronda {round_id}. Transacción deshecha: {e}")
         if conn: conn.rollback() # Deshacer toda la transacción
         # No retornamos False, solo logueamos el error.

    finally:
        if conn:
            conn.close() # Asegurarse de cerrar la conexión

    # ... (resto de la función, construye commissions_list_for_message y retorna) ...

    # La lista commissions_list_for_message ya fue construida arriba, basada en los cálculos.
    # Retornamos las listas de mensajes.
    return winners_list_for_message, commissions_list_for_message