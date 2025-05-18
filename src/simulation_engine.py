# src/simulation_engine.py
import logging
import sqlite3 # Para manejar la transacción de comisiones
from datetime import datetime # Si necesitas timestamps aquí

# Importar funciones de base de datos necesarias
from .db import (
    save_draw_results,
    save_creator_commission as db_save_creator_commission,
    get_db_connection # Para manejar la transacción de comisiones
)

# Importar constantes de ronda (si son necesarias para la lógica aquí)
from .round_manager import (
    MIN_PARTICIPANTS_FOR_TIMED_DRAW,
    MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW,
    ROUND_TYPE_USER_CREATED,
)

logger = logging.getLogger(__name__)

# --- Constantes de Porcentajes y Distribución Simuladas (de tu payment_manager.py original) ---
COMMISSION_PERCENT_GAS_SIMULATED = 0.10
COMMISSION_PERCENT_BOT = 0.10
COMMISSION_PERCENT_USER_CREATOR = 0.05

PRIZE_SPLIT_1_WINNER = [1.0]
PRIZE_SPLIT_2_WINNERS = [0.70, 0.30]
PRIZE_SPLIT_3_WINNERS = [0.50, 0.30, 0.20]
PRIZE_SPLIT_4_WINNERS = [0.40, 0.30, 0.20, 0.10]

async def calculate_and_save_simulated_payouts(
    round_id: int, 
    drawn_numbers: list[int], 
    participants_data: list[tuple], 
    round_type: str, 
    creator_id: str | None
) -> tuple[list[str], list[str]]:
    """
    Calcula los premios y comisiones simuladas para una ronda finalizada.
    Adaptado de tu payment_manager.py::perform_payout_calculation_and_save.
    Guarda los resultados y comisiones en la base de datos.
    Retorna listas de strings con la información de ganadores y comisiones para mensajes.
    """
    logger.debug(f"SIM_ENGINE: Iniciando cálculo de pagos simulados para ronda {round_id} (Tipo: {round_type}).")

    current_participants_count = len(participants_data)

    if not (MIN_PARTICIPANTS_FOR_TIMED_DRAW <= current_participants_count <= MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW):
        logger.error(f"SIM_ENGINE: Ronda {round_id} con número inválido de participantes ({current_participants_count}) para cálculo.")
        return [], [f"Error: Número inválido de participantes ({current_participants_count}) para cálculo de pagos."]

    total_collected_simulated = float(current_participants_count)

    commissions_to_save_in_db = []
    commissions_messages = []

    gas_commission_amount = total_collected_simulated * COMMISSION_PERCENT_GAS_SIMULATED
    commissions_to_save_in_db.append({
        'creator_type': 'gas_fee', 'creator_telegram_id': None,
        'amount_simulated': f"{gas_commission_amount:.2f} unidades", 'amount_real': gas_commission_amount
    })
    commissions_messages.append(f"- Fondo Gas Simulado ({int(COMMISSION_PERCENT_GAS_SIMULATED*100)}%): {gas_commission_amount:.2f} unidades")

    bot_commission_amount = total_collected_simulated * COMMISSION_PERCENT_BOT
    commissions_to_save_in_db.append({
        'creator_type': 'bot', 'creator_telegram_id': None,
        'amount_simulated': f"{bot_commission_amount:.2f} unidades", 'amount_real': bot_commission_amount
    })
    commissions_messages.append(f"- Comisión Bot ({int(COMMISSION_PERCENT_BOT*100)}%): {bot_commission_amount:.2f} unidades")

    user_creator_commission_amount = 0.0
    if round_type == ROUND_TYPE_USER_CREATED and creator_id:
        user_creator_commission_amount = total_collected_simulated * COMMISSION_PERCENT_USER_CREATOR
        commissions_to_save_in_db.append({
            'creator_type': 'user', 'creator_telegram_id': creator_id,
            'amount_simulated': f"{user_creator_commission_amount:.2f} unidades", 'amount_real': user_creator_commission_amount
        })
        creator_username = next((p[1] for p in participants_data if str(p[0]) == str(creator_id)), creator_id or 'desconocido')
        commissions_messages.append(f"- Comisión Creador @{creator_username} ({int(COMMISSION_PERCENT_USER_CREATOR*100)}%): {user_creator_commission_amount:.2f} unidades")

    total_fixed_commission_amount = gas_commission_amount + bot_commission_amount + user_creator_commission_amount
    prize_pool_for_winners_amount = max(0.0, total_collected_simulated - total_fixed_commission_amount)
    logger.debug(f"SIM_ENGINE: Ronda {round_id} - Total Recaudado: {total_collected_simulated:.2f}, Comisiones Fijas: {total_fixed_commission_amount:.2f}, Pozo Premios: {prize_pool_for_winners_amount:.2f}")

    prize_split_percentages = []
    if MIN_PARTICIPANTS_FOR_TIMED_DRAW <= current_participants_count <= 3:
        prize_split_percentages = PRIZE_SPLIT_1_WINNER
    elif 4 <= current_participants_count <= 6:
        prize_split_percentages = PRIZE_SPLIT_2_WINNERS
    elif 7 <= current_participants_count <= 9:
        prize_split_percentages = PRIZE_SPLIT_3_WINNERS
    elif current_participants_count == 10:
        prize_split_percentages = PRIZE_SPLIT_4_WINNERS
    
    winners_info_for_db = []
    winners_messages = []

    if not drawn_numbers:
        logger.warning(f"SIM_ENGINE: No se sortearon números para ronda {round_id}.")
    else:
        # En tu lógica original, aunque drawn_numbers es una lista, parece que solo usas el primero para determinar múltiples ganadores
        # si hay múltiples porcentajes en prize_split_percentages.
        # Para simplificar y seguir la idea de "un número sorteado principal", tomaremos el primer número.
        # Si tu intención era tener múltiples números sorteados distintos, esta parte necesitaría ajuste.
        
        # Asumimos que `drawn_numbers` contiene los números en el orden en que deben recibir premios según `prize_split_percentages`.
        # Tu `perform_simulated_draw_and_payout` original seleccionaba un *único* número ganador y luego buscaba si
        # ese número estaba en la lista de participantes. El código aquí se adaptará para buscar CADA número sorteado
        # si `drawn_numbers` pudiera contener más de uno y `prize_split_percentages` tuviera varios elementos.
        # PERO, como ahora indicas que se sortea 1 número, la lógica se simplifica:
        
        if drawn_numbers: # Debería haber al menos un número
            main_drawn_number = drawn_numbers[0] # El único número sorteado que importa para el premio principal

            # Encontrar al participante que tiene ESE número
            winner_participant_data = next((p for p in participants_data if p[2] == main_drawn_number), None) # p[2] is assigned_number

            if winner_participant_data:
                # Aplicar el prize_split_percentages al único ganador
                # (aunque prize_split_percentages podría tener varios elementos, solo el primero se usa si hay un solo ganador)
                prize_percentage = prize_split_percentages[0] if prize_split_percentages else 0
                prize_amount = prize_pool_for_winners_amount * prize_percentage
                prize_amount_simulated_text = f"{prize_amount:.2f} unidades"

                winners_messages.append(
                    f"- @{winner_participant_data[1] or winner_participant_data[0]} (Número {main_drawn_number}): Gana {prize_amount_simulated_text} ({int(prize_percentage*100)}% del Pozo)"
                )
                winners_info_for_db.append({
                    'drawn_number': main_drawn_number, 'draw_order': 0, # 0 para el primer (y único) premio
                    'winner_telegram_id': str(winner_participant_data[0]),
                    'prize_amount_simulated': prize_amount_simulated_text,
                    'prize_amount_real': prize_amount
                })
            else: # El número sorteado no lo tenía nadie (no debería pasar si se sortea de números asignados)
                logger.warning(f"SIM_ENGINE: Número sorteado {main_drawn_number} no encontrado entre participantes de ronda {round_id}.")
                winners_messages.append(f"El número sorteado {main_drawn_number} no fue asignado. ¡El pozo se acumula (simulado)!")
                winners_info_for_db.append({
                    'drawn_number': main_drawn_number, 'draw_order': 0,
                    'winner_telegram_id': None, 
                    'prize_amount_simulated': "Sin Ganador Asignado", 'prize_amount_real': 0.0
                })

    # Guardar resultados del sorteo (ganadores)
    if winners_info_for_db:
        save_draw_results(round_id, winners_info_for_db) # Tu función de db.py
        logger.info(f"SIM_ENGINE: Resultados del sorteo (simulado) guardados en DB para ronda {round_id}.")
    else: # Si no hubo drawn_numbers o no se encontró ganador con el número sorteado
        # Podrías querer guardar un registro de que no hubo ganador
        if drawn_numbers: # Si se sorteó un número pero no hubo ganador
             save_draw_results(round_id, [{
                'drawn_number': drawn_numbers[0], 'draw_order': 0, 'winner_telegram_id': None,
                'prize_amount_simulated': "Sin Ganador", 'prize_amount_real': 0.0
            }])
        logger.warning(f"SIM_ENGINE: No hay información de ganadores para guardar en DB para ronda {round_id}.")

    # Guardar Comisiones Simuladas DENTRO DE UNA TRANSACCIÓN
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        conn.execute("BEGIN TRANSACTION") # Iniciar transacción explícitamente

        for commission_info in commissions_to_save_in_db:
            try:
                # db_save_creator_commission ahora es una función normal que maneja su propia conexión
                # Para una transacción, es mejor pasar el cursor.
                # Re-implementaremos db_save_creator_commission para aceptar cursor.
                # O, aquí, manejamos la transacción explícitamente.
                 cursor.execute(
                    """
                    INSERT INTO creator_commission (
                        round_id, creator_type, creator_telegram_id, amount_simulated, amount_real, transaction_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (round_id, commission_info['creator_type'], commission_info['creator_telegram_id'], 
                     commission_info['amount_simulated'], commission_info['amount_real'], None)
                )
            except sqlite3.IntegrityError:
                logger.warning(f"SIM_ENGINE: Comisión duplicada para ronda {round_id}, tipo '{commission_info['creator_type']}'. Saltando.")
                # No relanzamos para permitir que otras comisiones se guarden si esta falla por duplicado.
                # Pero si cualquier otra cosa falla, la transacción se deshará.
            # Otros sqlite3.Error serán capturados por el except externo y desharán la transacción.

        conn.commit() # Confirmar la transacción si todo fue bien
        logger.info(f"SIM_ENGINE: Comisiones simuladas guardadas en DB para ronda {round_id}.")
    except sqlite3.Error as e:
        logger.error(f"SIM_ENGINE: Error SQLite guardando comisiones para ronda {round_id}. Transacción deshecha: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            
    return winners_messages, commissions_messages