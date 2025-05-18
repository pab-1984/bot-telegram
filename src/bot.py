# src/bot.py (Versión Aiogram con Jobs y Simulation Engine - Adaptada a Aiogram v3.x)
import asyncio
import logging # Importamos logging al inicio
import json
import os # Para leer variables de entorno para intervalos de jobs
import random # Para el sorteo en la lógica adaptada
from datetime import datetime, timedelta, timezone # Para la lógica de tiempos en jobs
import functools # Para pasar argumentos a los jobs de aioschedule
from aiogram.client.default import DefaultBotProperties

# --- Configuración de Logging (Movida al inicio) ---
# La configuración básica se hace aquí, pero la sección if __name__ == '__main__':
# puede sobreescribirla para pruebas directas.
logging.basicConfig(
    level=logging.INFO, # Nivel por defecto: INFO
    format='%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s', # Añadido filename y lineno
)
logger = logging.getLogger(__name__) # Definimos logger aquí
logging.getLogger("aioschedule").setLevel(logging.INFO) # Nivel específico para aioschedule


# --- Importaciones de aiogram (adaptadas para v3.x) ---
from aiogram import Bot, Dispatcher, types # Eliminamos executor de aquí
from aiogram.fsm.storage.memory import MemoryStorage # Importación de MemoryStorage en v3.x
from aiogram.enums import ParseMode # <-- Importación correcta de ParseMode en v3.x

# --- Importaciones de tu proyecto (Corregidas a absolutas) ---
# Asegúrate de que estas funciones existan en tu src/db.py fusionado y actualizado

# --- IMPORTACIÓN CORREGIDA PARA EL MÓDULO DB ---
# En lugar de importar funciones específicas, importamos el módulo completo.
# Luego accederemos a las funciones usando src.db.function_name()
import src.db
# Si deseas importar algunas funciones comunes directamente para usarlas sin src.db.,
# puedes mantener un subconjunto de la siguiente forma, pero es mejor la consistencia.
# from src.db import init_db, get_active_round # Ejemplo: si solo usas estas 2 directamente

from src.payment_manager import PaymentManager # Corregido a importación absoluta
from src.handlers import register_all_handlers    # Corregido a importación absoluta

# Funciones y constantes de round_manager
# Si round_manager.py está en src/, también necesita importación absoluta
try:
    from src.round_manager import ( # Corregido a importación absoluta
        create_round as rm_create_round,
        get_available_rounds as rm_get_available_rounds,
        update_round_status_manager as rm_update_round_status_manager,
        count_round_participants as rm_count_round_participants,
        MIN_PARTICIPANTS_FOR_TIMED_DRAW,
        MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW, # Aunque el sorteo simulado ahora se basa en MIN_PARTICIPANTS_FOR_TIMED_DRAW
        ROUND_STATUS_WAITING_TO_START,
        ROUND_STATUS_WAITING_FOR_PAYMENTS,
        ROUND_STATUS_DRAWING,
        ROUND_STATUS_FINISHED,
        ROUND_STATUS_CANCELLED,
        ROUND_TYPE_SCHEDULED,
    )
except ImportError:
     logger.warning("No se pudo importar round_manager. La lógica de gestión de rondas simuladas no estará disponible.")
     # Define placeholders o maneja la ausencia de round_manager si es opcional
     # Definimos placeholders para las funciones de round_manager si la importación falla
     def rm_create_round(*args, **kwargs): logger.error("round_manager.create_round no disponible."); return None
     def rm_get_available_rounds(): logger.error("round_manager.get_available_rounds no disponible."); return []
     def rm_update_round_status_manager(*args, **kwargs): logger.error("round_manager.update_round_status_manager no disponible."); return False
     def rm_count_round_participants(*args, **kwargs): logger.error("round_manager.count_round_participants no disponible."); return 0
     # Definir constantes si no se importaron
     MIN_PARTICIPANTS_FOR_TIMED_DRAW = 2
     MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW = 10
     ROUND_STATUS_WAITING_TO_START = 'waiting_to_start'
     ROUND_STATUS_WAITING_FOR_PAYMENTS = 'waiting_for_payments'
     ROUND_STATUS_DRAWING = 'drawing'
     ROUND_STATUS_FINISHED = 'finished'
     ROUND_STATUS_CANCELLED = 'cancelled'
     ROUND_TYPE_SCHEDULED = 'scheduled'


# Importar el motor de simulación
# Asegúrate de que este archivo y función existan si los usas
try:
    from src.simulation_engine import calculate_and_save_simulated_payouts # Corregido a importación absoluta
except ImportError:
    logger.warning("No se pudo importar simulation_engine.calculate_and_save_simulated_payouts. La lógica de sorteo simulado no estará disponible.")
    async def calculate_and_save_simulated_payouts(*args, **kwargs):
        logger.error("simulation_engine.calculate_and_save_simulated_payouts no está implementada o no se pudo importar.")
        return [], [] # Retorna listas vacías si la función no existe


# Necesitarás `aioschedule`. Instálalo con: pip install aioschedule
import aioschedule


# --- LÓGICA DE CIERRE DE RONDA SIMULADA (llamada por el job) ---
async def execute_simulated_round_closure(round_id: int, bot_instance: Bot):
    """
    Coordina el sorteo simulado, cálculo de premios/comisiones (simulados) y notificaciones.
    """
    logger.info(f"JOB: Iniciando cierre simulado para ronda {round_id}.")

    # Asegúrate de que las funciones de db y round_manager se llamen con el prefijo del módulo si es necesario
    target_round_data = src.db.get_round_by_id(round_id) # Ejemplo de llamada con prefijo
    if not target_round_data:
        logger.error(f"JOB: No se encontraron datos para ronda {round_id}. No se puede cerrar.")
        return
        
    # Asegurarse de que target_round_data es un diccionario o acceder por índice si es tupla
    # Asumimos dict basado en db.py actualizado, pero comprobamos por seguridad
    if isinstance(target_round_data, tuple): # Si es una tupla, adaptamos el acceso
         if len(target_round_data) < 8:
             logger.error(f"JOB: Datos de ronda incompletos para ronda {round_id}. No se puede cerrar.")
             return
         r_id, _, _, r_status, r_type, r_creator_id, _, _ = target_round_data
    else: # Si es un diccionario (esperado)
         r_id = target_round_data.get('id')
         r_status = target_round_data.get('status')
         r_type = target_round_data.get('round_type')
         r_creator_id = target_round_data.get('creator_telegram_id')
         if r_id is None or r_status is None or r_type is None:
              logger.error(f"JOB: Datos esenciales faltantes para ronda: {target_round_data}. Saltando.")
              return


    if r_status != ROUND_STATUS_DRAWING:
        logger.warning(f"JOB: Ronda {round_id} no está en estado '{ROUND_STATUS_DRAWING}' (actual: '{r_status}'). Saltando cierre para evitar doble procesamiento.")
        return

    all_participants_data = src.db.get_participants_in_round(round_id) # Ejemplo de llamada con prefijo
    
    # Validar si hay suficientes participantes para un sorteo significativo
    if not all_participants_data or len(all_participants_data) < MIN_PARTICIPANTS_FOR_TIMED_DRAW:
        logger.warning(f"JOB: Ronda {round_id} con < {MIN_PARTICIPANTS_FOR_TIMED_DRAW} participantes ({len(all_participants_data)}). Cancelando ronda.")
        src.round_manager.update_round_status_manager(round_id, ROUND_STATUS_CANCELLED) # Ejemplo de llamada con prefijo
        # Notificar cancelación a los pocos que haya
        for p_data in all_participants_data:
            try:
                # p_data es un diccionario si db.py usa row_factory = sqlite3.Row
                p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0]
                if p_telegram_id:
                     await bot_instance.send_message(p_telegram_id, f"⚠️ La ronda ID <code>{round_id}</code> ha sido cancelada (participantes insuficientes al momento del sorteo).", parse_mode=ParseMode.HTML) # Usar ParseMode
            except Exception as e: logger.error(f"JOB: Error enviando msg cancelación a {p_telegram_id} para ronda {round_id}: {e}")
        return

    # Realizar el sorteo
    available_numbers = [p.get('assigned_number') if isinstance(p, dict) else p[2] for p in all_participants_data if (p.get('assigned_number') if isinstance(p, dict) else p[2]) is not None] # p[2] es assigned_number
    if not available_numbers:
        logger.error(f"JOB: No hay números asignados para sortear en ronda {round_id}. Cancelando.")
        src.round_manager.update_round_status_manager(round_id, ROUND_STATUS_CANCELLED) # Ejemplo de llamada con prefijo
        return

    drawn_winner_number = random.choice(available_numbers)
    logger.info(f"JOB: Número sorteado para ronda {round_id}: {drawn_winner_number}.")

    msg_numero_sorteado = f"🎉 ¡Sorteo de la Ronda ID <code>{round_id}</code> realizado!\nEl Número Ganador (simulado) es: <b>{drawn_winner_number}</b>"
    for p_data in all_participants_data:
        try:
            p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
            if p_telegram_id:
                 await bot_instance.send_message(p_telegram_id, msg_numero_sorteado, parse_mode=ParseMode.HTML) # Usar ParseMode
        except Exception as e: logger.error(f"JOB: Error enviando msg # sorteado a {p_telegram_id} para ronda {round_id}: {e}")

    # Llamar al motor de simulación para calcular premios y comisiones
    # Esta función debe estar definida en src/simulation_engine.py y ser async
    try:
        # Asegúrate de que calculate_and_save_simulated_payouts también se llame con prefijo si es necesario
        # Comprobamos si calculate_and_save_simulated_payouts fue importada correctamente
        if 'calculate_and_save_simulated_payouts' in globals() and asyncio.iscoroutinefunction(calculate_and_save_simulated_payouts):
             winners_messages, commissions_messages = await calculate_and_save_simulated_payouts(
                 round_id, [drawn_winner_number], all_participants_data, r_type, str(r_creator_id) if r_creator_id else None
             )
        else:
             logger.error("JOB: simulation_engine.calculate_and_save_simulated_payouts no está disponible o no es una función async.")
             winners_messages, commissions_messages = [], ["Error: La lógica de cálculo de pagos simulados no está disponible."]

    except Exception as e:
         logger.error(f"JOB: Error ejecutando calculate_and_save_simulated_payouts para ronda {round_id}: {e}", exc_info=True)
         winners_messages, commissions_messages = [], ["Error ejecutando cálculo de pagos simulados."]


    # Enviar mensajes de ganadores
    if winners_messages:
        full_winners_message = f"🏆 <b>Resultados del Sorteo Simulado (Ronda ID <code>{round_id}</code>):</b>\n\n" + "\n".join(winners_messages)
        for p_data in all_participants_data:
            try:
                 p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
                 if p_telegram_id:
                      await bot_instance.send_message(p_telegram_id, full_winners_message, parse_mode=ParseMode.HTML) # Usar ParseMode
            except Exception as e: logger.error(f"JOB: Error enviando msg ganadores a {p_telegram_id} para ronda {round_id}: {e}")
    # No enviar mensaje "No ganador" si hubo messages de ganadores
    # else:
    #     no_winner_msg = f"🥺 El número sorteado <b>{drawn_winner_number}</b> no tuvo un ganador asignado en la ronda {round_id}."
    #     for p_data in all_participants_data:
    #         try:
    #              p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
    #              if p_telegram_id:
    #                  await bot_instance.send_message(p_telegram_id, no_winner_msg, parse_mode=ParseMode.HTML) # Usar ParseMode
    #         except Exception as e: logger.error(f"JOB: Error enviando msg no ganador a {p_telegram_id} para ronda {round_id}: {e}")


    # Enviar mensajes de comisiones
    if commissions_messages:
        full_commissions_message = f"💸 <b>Comisiones Simuladas (Ronda ID <code>{round_id}</code>):</b>\n" + "\n".join(commissions_messages)
        # Se envían a todos los participantes, quizás solo deberían ir al creador o admin?
        # Dejamos como estaba el código original para enviar a todos los participantes.
        for p_data in all_participants_data:
            try:
                 p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
                 if p_telegram_id:
                     await bot_instance.send_message(p_telegram_id, full_commissions_message, parse_mode=ParseMode.HTML) # Usar ParseMode
            except Exception as e: logger.error(f"JOB: Error enviando msg comisiones a {p_telegram_id} para ronda {round_id}: {e}")


    # Marcar la ronda como finalizada
    # Comprobamos si rm_update_round_status_manager fue importada correctamente
    if 'rm_update_round_status_manager' in globals() and callable(rm_update_round_status_manager):
        if rm_update_round_status_manager(round_id, ROUND_STATUS_FINISHED): # Llamada directa si se importó, o placeholder si no
            logger.info(f"JOB: Ronda {round_id} marcada como '{ROUND_STATUS_FINISHED}'.")
            final_msg = f"✅ Ronda de simulación ID <code>{round_id}</code> ha finalizado."
            for p_data in all_participants_data:
                try:
                     p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
                     if p_telegram_id:
                         await bot_instance.send_message(p_telegram_id, final_msg, parse_mode=ParseMode.HTML) # Usar ParseMode
                except Exception as e: logger.error(f"JOB: Error enviando msg final a {p_data[0]} para ronda {round_id}: {e}")
        else:
             logger.error(f"JOB: Falló la actualización final del estado de ronda {round_id} a '{ROUND_STATUS_FINISHED}'.")
    else:
         logger.error(f"JOB: round_manager.update_round_status_manager no está disponible.")


# --- Definición de los Jobs para Aiogram ---
async def job_check_expired_rounds(bot_instance_for_job: Bot):
    logger.info("JOB: Iniciando `job_check_expired_rounds`...")
    
    # Ajusta estos tiempos según tu lógica de negocio. Para pruebas pueden ser más cortos.
    # Estos timedelta definen "hace cuánto tiempo" debe haber empezado una ronda para considerarla.
    # Leer de variables de entorno o config.json
    try:
        # Leer de config.json en lugar de os.getenv si es la fuente principal
        # Debes cargar config.json aquí también o pasar los valores desde main
        # Por ahora, mantenemos os.getenv para no añadir otra carga de config.
        TIME_LIMIT_FOR_DRAW_MINUTES = int(os.getenv('JOB_DRAW_LIMIT_MINUTES', 1)) # Reducido a 1 minuto para pruebas
        TIME_LIMIT_FOR_CANCELLATION_HOURS = int(os.getenv('JOB_CANCEL_LIMIT_HOURS', 1))
    except ValueError:
         logger.error("JOB: Variables de entorno de tiempo de job no son números válidos. Usando valores por defecto.")
         TIME_LIMIT_FOR_DRAW_MINUTES = 1
         TIME_LIMIT_FOR_CANCELLATION_HOURS = 1
    except TypeError: # os.getenv podría retornar None si no está seteada y el default no es int
         logger.error("JOB: Variables de entorno de tiempo de job no son números válidos. Usando valores por defecto.")
         TIME_LIMIT_FOR_DRAW_MINUTES = 1
         TIME_LIMIT_FOR_CANCELLATION_HOURS = 1


    time_limit_for_draw_utc = datetime.now(timezone.utc) - timedelta(minutes=TIME_LIMIT_FOR_DRAW_MINUTES)
    time_limit_for_cancellation_utc = datetime.now(timezone.utc) - timedelta(hours=TIME_LIMIT_FOR_CANCELLATION_HOURS)
    
    logger.debug(f"JOB: Tiempo límite para sorteo: {time_limit_for_draw_utc.isoformat()}")
    logger.debug(f"JOB: Tiempo límite para cancelación: {time_limit_for_cancellation_utc.isoformat()}")


    # Obtener rondas que están esperando inicio o pagos, y no están marcadas como eliminadas
    # Usar src.db.get_rounds_by_status
    rounds_to_check = src.db.get_rounds_by_status( # Ejemplo de llamada con prefijo
        [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS], 
        check_deleted=True # Checkea si deleted == 0
    )
    logger.debug(f"JOB: Se encontraron {len(rounds_to_check)} rondas para verificar.")


    for ronda_data in rounds_to_check:
        # Asegurarse de que ronda_data es un diccionario o una tupla con suficientes elementos
        # db.py ahora usa row_factory = sqlite3.Row, por lo que debería ser un diccionario.
        # Mantenemos la comprobación de seguridad.
        if isinstance(ronda_data, dict):
             round_id = ronda_data.get('id')
             start_time_str = ronda_data.get('start_time')
             current_status = ronda_data.get('status')
             is_deleted = ronda_data.get('deleted', 0)
        elif isinstance(ronda_data, tuple) and len(ronda_data) >= 7: # Verificar la longitud de la tupla según la tabla rounds
             round_id, start_time_str, _, current_status, _, _, is_deleted, _ = ronda_data # Desempaquetar índices relevantes
        else:
             logger.warning(f"JOB: Datos de ronda incompletos o inesperados: {ronda_data}. Saltando.")
             continue # Saltar esta ronda si los datos no tienen el formato esperado


        if round_id is None or start_time_str is None or current_status is None:
             logger.error(f"JOB: Datos esenciales faltantes para ronda: {ronda_data}. Saltando.")
             continue

        # En tu db.py, la columna 'deleted' es un BOOLEAN DEFAULT 0. SQLite almacena booleanos como 0 (False) y 1 (True).
        # Tu consulta get_rounds_by_status ya filtra por deleted = 0 si check_deleted=True.
        # Esta comprobación extra de is_deleted dentro del loop es redundante si check_deleted es True en la query.
        # Si check_deleted fuera False, esta comprobación sería necesaria.
        # Asumimos que check_deleted=True es correcto y esta línea puede ser eliminada o logueada como debug.
        # if is_deleted:
        #      logger.debug(f"JOB: Ronda {round_id} marcada como eliminada. Saltando.")
        #      continue

        logger.debug(f"JOB: Procesando ronda {round_id} (estado: {current_status}, inicio: {start_time_str}, deleted: {is_deleted}).")

        try:
            start_time_dt = datetime.fromisoformat(start_time_str)
            if start_time_dt.tzinfo is None: # Si es naive, asumimos UTC para comparación
                start_time_dt = start_time_dt.replace(tzinfo=timezone.utc)
            
            # Comprobamos si rm_count_round_participants fue importada correctamente
            if 'rm_count_round_participants' in globals() and callable(rm_count_round_participants):
                 current_participants_count = rm_count_round_participants(round_id) # Llamada directa si se importó, o placeholder si no
            else:
                 logger.error("JOB: round_manager.count_round_participants no está disponible.")
                 current_participants_count = 0 # Asumir 0 if the function is not available

            logger.debug(f"JOB: Ronda {round_id} tiene {current_participants_count} participantes.")


            # Lógica de Sorteo por Tiempo
            # Solo si está en estado de espera y ha pasado el tiempo mínimo para sorteo
            if current_status in [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS] and start_time_dt < time_limit_for_draw_utc:
                # Comprobamos si MIN_PARTICIPANTS_FOR_TIMED_DRAW está definido globalmente (viene de la importación o placeholder)
                if 'MIN_PARTICIPANTS_FOR_TIMED_DRAW' in globals() and current_participants_count >= MIN_PARTICIPANTS_FOR_TIMED_DRAW:
                    logger.info(f"JOB: Ronda {round_id} ({current_participants_count} part.) elegible para sorteo por tiempo. Actualizando estado a '{ROUND_STATUS_DRAWING}'.")
                    # Actualizar estado a DRAWING ANTES de ejecutar el cierre para evitar re-procesamiento
                    # Comprobamos si rm_update_round_status_manager fue importada correctamente
                    if 'rm_update_round_status_manager' in globals() and callable(rm_update_round_status_manager):
                         if rm_update_round_status_manager(round_id, ROUND_STATUS_DRAWING): # Llamada directa si se importó, o placeholder si no
                             logger.info(f"JOB: Estado de ronda {round_id} cambiado a '{ROUND_STATUS_DRAWING}'. Procediendo a cierre.")
                             # Ejecutar el cierre de ronda (sorteo simulado, payouts, notificaciones)
                             # Usamos create_task para no bloquear el job si el cierre es largo
                             asyncio.create_task(execute_simulated_round_closure(round_id, bot_instance_for_job))
                         else:
                             logger.error(f"JOB: No se pudo actualizar estado de ronda {round_id} a drawing para sorteo por tiempo.")
                    else:
                         logger.error(f"JOB: round_manager.update_round_status_manager no está disponible para actualizar a drawing.")
                # Lógica de Cancelación por Tiempo y Pocos Participantes
                # Solo si está en estado de espera y ha pasado el tiempo máximo para cancelación
                # Comprobamos si MIN_PARTICIPANTS_FOR_TIMED_DRAW está definido globalmente
                elif 'MIN_PARTICIPANTS_FOR_TIMED_DRAW' in globals() and current_participants_count < MIN_PARTICIPANTS_FOR_TIMED_DRAW and current_status in [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS] and start_time_dt < time_limit_for_cancellation_utc:
                    logger.info(f"JOB: Ronda {round_id} ({current_participants_count} part.) elegible para cancelación por tiempo.")
                    # Comprobamos si rm_update_round_status_manager fue importada correctamente
                    if 'rm_update_round_status_manager' in globals() and callable(rm_update_round_status_manager):
                         if rm_update_round_status_manager(round_id, ROUND_STATUS_CANCELLED): # Llamada directa si se importó, o placeholder si no
                             logger.info(f"JOB: Estado de ronda {round_id} cambiado a '{ROUND_STATUS_CANCELLED}'. Notificando participantes.")
                             # Usar src.db.get_participants_in_round
                             participants_to_notify = src.db.get_participants_in_round(round_id) # Ejemplo de llamada con prefijo
                             cancel_msg = f"⚠️ La ronda ID <code>{round_id}</code> ha sido cancelada (pocos participantes / tiempo excedido)."
                             for p_data in participants_to_notify:
                                 try:
                                     # p_data es un diccionario if db.py uses row_factory = sqlite3.Row
                                     p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0]
                                     if p_telegram_id:
                                         await bot_instance_for_job.send_message(p_telegram_id, cancel_msg, parse_mode=ParseMode.HTML)
                                 except Exception as e: logger.error(f"JOB: Error enviando msg cancelación a {p_telegram_id} para ronda {round_id}: {e}")
                         else:
                             logger.error(f"JOB: No se pudo actualizar estado de ronda {round_id} a cancelled.")
                    else:
                         logger.error(f"JOB: round_manager.update_round_status_manager no está disponible para actualizar a cancelled.")
                # If not eligible for draw or cancellation by time
                # else:
                     # logger.debug(f"JOB: Ronda {round_id} not eligible for draw/cancellation by time yet.")


        except ValueError as ve:
            logger.error(f"JOB: Error converting start_time '{start_time_str}' for ronda {round_id}: {ve}")
        except Exception as e:
            logger.error(f"JOB: Unexpected error processing ronda {round_id} in job_check_expired_rounds: {e}", exc_info=True)
            
    logger.info("JOB: `job_check_expired_rounds` finished.")


async def job_create_scheduled_round(bot_instance_for_job: Bot):
    logger.info("JOB: Iniciando `job_create_scheduled_round`...")
    
    # Check if rm_get_available_rounds was imported correctly
    if 'rm_get_available_rounds' in globals() and callable(rm_get_available_rounds):
         open_rounds = rm_get_available_rounds() # Direct call if imported, or placeholder if not
    else:
         logger.error("JOB: round_manager.get_available_rounds not available.")
         open_rounds = []

    logger.debug(f"JOB: Found {len(open_rounds)} open rounds to check for auto creation.")
    
    # Check if a scheduled round ('scheduled') already exists that is open
    # Iterate over open rounds and check their type
    scheduled_round_exists = False
    # Check if ROUND_TYPE_SCHEDULED is defined globally
    if 'ROUND_TYPE_SCHEDULED' not in globals():
        logger.error("JOB: Constant ROUND_TYPE_SCHEDULED not available. Cannot check/create scheduled round.")
    else:
        for r_data in open_rounds:
            # Ensure r_data is a dict or tuple with enough elements
            if isinstance(r_data, dict) and r_data.get('round_type') == ROUND_TYPE_SCHEDULED:
                 scheduled_round_exists = True
                 break
            elif isinstance(r_data, tuple) and len(r_data) > 4 and r_data[4] == ROUND_TYPE_SCHEDULED: # Assuming round_type is at index 4
                 scheduled_round_exists = True
                 break


    if 'ROUND_TYPE_SCHEDULED' in globals() and not scheduled_round_exists:
        logger.info("JOB: No open scheduled round. Creating a new one...")
        # You can define the ticket price for scheduled rounds here or in config.json
        # Read from config.json instead of os.getenv if it's the primary source
        # You should load config.json here as well or pass the values from main
        # For now, keep os.getenv to avoid another config load.
        try:
             # Assuming config.json is already loaded in main and can be accessed or reloaded here.
             # Reload config to ensure access to DEFAULT_SCHEDULED_TICKET_PRICE if not passed.
             CONFIG_FILE_PATH = 'config.json'
             try:
                 with open(CONFIG_FILE_PATH, 'r') as f:
                     config = json.load(f)
                     DEFAULT_SCHEDULED_TICKET_PRICE = float(config.get('TICKET_PRICE_TON', 1.0)) # Use TICKET_PRICE_TON from config
             except (FileNotFoundError, json.JSONDecodeError, ValueError):
                 logger.warning(f"JOB: Could not load/read '{CONFIG_FILE_PATH}' or 'TICKET_PRICE_TON'. Using default price 1.0.")
                 DEFAULT_SCHEDULED_TICKET_PRICE = 1.0
        except Exception as e:
             logger.error(f"JOB: Unexpected error trying to read price from config: {e}")
             DEFAULT_SCHEDULED_TICKET_PRICE = 1.0


        # Check if rm_create_round was imported correctly
        if 'rm_create_round' in globals() and callable(rm_create_round):
             new_round_id = rm_create_round(round_type=ROUND_TYPE_SCHEDULED, creator_telegram_id=None, ticket_price=DEFAULT_SCHEDULED_TICKET_PRICE)
             if new_round_id:
                 logger.info(f"JOB: Automatic scheduled round created with ID: {new_round_id}.")
                 # Optional: Notify an admin if configured
                 # ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID") # Or read from config
                 # if ADMIN_ID:
                 #     try: await bot_instance_for_job.send_message(ADMIN_ID, f"🤖 New scheduled round {new_round_id} created automatically.")
                 #     except Exception as e: logger.error(f"JOB: Error notifying admin about new round {new_round_id}: {e}")
             else:
                 logger.error("JOB: Failed to create automatic scheduled round.")
        else:
             logger.error("JOB: round_manager.create_round not available.")

    elif 'ROUND_TYPE_SCHEDULED' in globals(): # If ROUND_TYPE_SCHEDULED is defined but scheduled_round_exists is True
        logger.info("JOB: Open scheduled round already exists. Not creating new one.")

    # If ROUND_TYPE_SCHEDULED is not defined, the first if is not met and we reach here without attempting creation.
    # An error was already logged above if it wasn't defined.
    
    logger.info("JOB: `job_create_scheduled_round` finished.")


# --- Funciones de Arranque y Apagado ---
# Corrected type annotation for bot_instance
async def on_startup(dispatcher: Dispatcher, bot_instance: Bot, pm_instance: PaymentManager):
    logger.info("Iniciando bot (Aiogram)...")
    
    logger.debug("Inicializando base de datos...")
    try:
        # --- LLAMADA CORREGIDA ---
        # Now that we import the `src.db` module, we access the function with the full prefix.
        src.db.init_db() 
        logger.info("Base de datos inicializada.")
    except Exception as e:
        logger.critical(f"Fatal error initializing the database: {e}", exc_info=True)
        # Consider if you want the bot to stop here if the DB is critical
        # exit() # Uncomment if you want to stop the bot if the DB fails
        return # Do not proceed if the DB fails

    logger.debug("Registrando handlers...")
    # Register all Aiogram handlers
    # pm_instance (PaymentManager for TON) is passed to register_all_handlers
    # Check if register_all_handlers was imported correctly
    if 'register_all_handlers' in globals() and callable(register_all_handlers):
         try:
             # pm_instance is already created in main and passed here
             register_all_handlers(dispatcher, bot_instance, pm_instance) # Direct call if imported
             logger.info("Handlers from src.handlers (Aiogram version) registered.")
         except Exception as e:
              logger.critical(f"Fatal error registering handlers: {e}", exc_info=True)
              # exit() # Uncomment if you want to stop the bot if handlers fail
              return
    else:
         logger.critical("Fatal error: Handlers not available (import failed).")
         # exit() # Consider exiting if handlers cannot be registered
         return


    logger.debug("Estableciendo comandos del bot...")
    try:
        await bot_instance.set_my_commands([ # Use bot_instance
            # --- CORRECCIÓN AQUÍ: Usar argumentos de palabra clave ---
            types.BotCommand(command="start", description="🚀 Iniciar el bot"),
            types.BotCommand(command="comprar_boleto", description="🎟️ Comprar Boleto (con TON)"),
            types.BotCommand(command="mis_pagos_ton", description="📜 Mis Pagos (Pagos TON)"),
            types.BotCommand(command="cancelar", description="❌ Cancelar acción actual"),
            # --- Make sure to also correct this command if round_manager is available ---
             *(
                 [types.BotCommand(command="rondas_abiertas", description="🎮 Ver Rondas Abiertas (Simuladas)")]
                 if 'rm_get_available_rounds' in globals() and callable(rm_get_available_rounds) else []
             )
            # --- End of correction ---
        ])
        logger.info("Comandos del bot establecidos.")
    except Exception as e:
         logger.error(f"Error al establecer comandos del bot: {e}", exc_info=True)


    # --- Configuration of Scheduled Tasks with aioschedule ---
    logger.debug("Configurando tareas programadas con aioschedule...")
    # Intervals can be read from environment variables or defined here.
    # For production, longer intervals. For testing, shorter ones.
    try:
        # Read from config.json if it is the primary source
        CONFIG_FILE_PATH = 'config.json'
        try:
            with open(CONFIG_FILE_PATH, 'r') as f:
                config = json.load(f)
                CHECK_EXPIRED_INTERVAL_SECONDS = int(config.get('JOB_CHECK_EXPIRED_INTERVAL_SECONDS', 60))
                CREATE_SCHEDULED_INTERVAL_SECONDS = int(config.get('JOB_CREATE_SCHEDULED_INTERVAL_SECONDS', 300))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            logger.warning(f"Could not load/read '{CONFIG_FILE_PATH}' or job intervals. Using default values.")
            CHECK_EXPIRED_INTERVAL_SECONDS = 60
            CREATE_SCHEDULED_INTERVAL_SECONDS = 300
    except Exception as e:
         logger.error(f"Unexpected error trying to read job intervals from config: {e}")
         CHECK_EXPIRED_INTERVAL_SECONDS = 60
         CREATE_SCHEDULED_INTERVAL_SECONDS = 300


    logger.info(f"Configurando job 'check_expired_rounds' cada {CHECK_EXPIRED_INTERVAL_SECONDS} segundos.")
    # Pass bot_instance_for_job to functools.partial
    aioschedule.every(CHECK_EXPIRED_INTERVAL_SECONDS).seconds.do(functools.partial(job_check_expired_rounds, bot_instance_for_job=bot_instance))
    
    logger.info(f"Configurando job 'create_scheduled_round' cada {CREATE_SCHEDULED_INTERVAL_SECONDS} segundos.")
    # Pass bot_instance_for_job to functools.partial
    aioschedule.every(CREATE_SCHEDULED_INTERVAL_SECONDS).seconds.do(functools.partial(job_create_scheduled_round, bot_instance_for_job=bot_instance))
    
    # Create and launch the scheduler task
    async def scheduler():
        logger.info("Scheduler (aioschedule) started. Executing initial jobs after a short wait...")
        # Execute jobs once at startup with a small delay
        await asyncio.sleep(5) # Wait 5 seconds before the first execution
        
        # Execute job_check_expired_rounds only if the function is available
        if 'job_check_expired_rounds' in globals() and asyncio.iscoroutinefunction(job_check_expired_rounds):
             logger.info("Executing job_check_expired_rounds for the first time...")
             asyncio.create_task(job_check_expired_rounds(bot_instance_for_job=bot_instance)) # Pass bot_instance
        else:
             logger.warning("Skipping initial job_check_expired_rounds execution: function not available.")

        await asyncio.sleep(5) # Small delay

        # Execute job_create_scheduled_round only if the function is available
        if 'job_create_scheduled_round' in globals() and asyncio.iscoroutinefunction(job_create_scheduled_round):
             logger.info("Executing job_create_scheduled_round for the first time...")
             asyncio.create_task(job_create_scheduled_round(bot_instance_for_job=bot_instance)) # Pass bot_instance
        else:
             logger.warning("Skipping initial job_create_scheduled_round execution: function not available.")


        while True:
            await aioschedule.run_pending()
            await asyncio.sleep(1) # Wait 1 second between scheduler checks

    asyncio.create_task(scheduler()) # Launch the scheduler as a background task
    logger.info("Scheduled tasks planner (aioschedule) configured and background task started.")
    logger.info("Bot (Aiogram) started and ready.")


async def on_shutdown(dispatcher: Dispatcher):
    logger.info("Apagando bot (Aiogram)...")
    
    # Stop aioschedule tasks
    if hasattr(aioschedule, 'clear') and callable(getattr(aioschedule, 'clear')):
        aioschedule.clear() 
        logger.info("aioschedule tasks stopped.")
    else:
        logger.warning("Could not call aioschedule.clear().")

    # Close FSM storage
    if dispatcher.storage: # Use dispatcher.storage
        await dispatcher.storage.close()
        # await dispatcher.storage.wait_closed() # Commented out/Removed in the previous correction
        logger.info("FSM storage closed.")
    
    # Close bot session
    # In Aiogram 3.x, this is handled slightly differently.
    # `bot.session` may not be the correct way, `await bot.close()` is used or it's handled by the lifecycle.
    # If you are using Aiogram 2.x:
    # if bot.session:
    #    await bot.session.close()
    # For Aiogram 3.x, `await bot.close()` is more common if explicit closure is needed.
    # Or often nothing explicit is needed here for the bot session.
    # We will omit explicit bot session closing for broader compatibility,
    # as Aiogram's executor usually handles it.

    logger.info("Bot (Aiogram) shut down.")


async def main():
    # This is the new main function for Aiogram v3.x
    # Logging configuration was already done in if __name__ == '__main__':
    
    # --- Load Bot Configuration (Moved inside main) ---
    CONFIG_FILE_PATH = 'config.json' # Path relative to the project root directory
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            config = json.load(f)
            BOT_TOKEN = config.get('BOT_TOKEN')
            # BOT_USERNAME = config.get('BOT_USERNAME') # If you need it
    except FileNotFoundError:
        logger.critical(f"FATAL ERROR: {CONFIG_FILE_PATH} not found.")
        return # Do not proceed if config fails
    except json.JSONDecodeError:
        logger.critical(f"FATAL ERROR: {CONFIG_FILE_PATH} is not valid JSON.")
        return # Do not proceed if config fails
    except Exception as e:
        logger.critical(f"FATAL ERROR loading {CONFIG_FILE_PATH}: {e}")
        return # Do not proceed if config fails

    if not BOT_TOKEN:
        logger.critical("FATAL ERROR: BOT_TOKEN is empty in config.json.")
        return # Do not proceed if token is empty


    # --- Initialize bot and dispatcher (CREATE INSTANCES HERE) ---
    storage = MemoryStorage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)

    # --- Instantiate PaymentManager ---
    # PaymentManager no longer needs db_instance if db.py manages its connection
    try:
        pm_instance = PaymentManager()
    except ValueError as e:
         logger.critical(f"Fatal error initializing PaymentManager: {e}")
         # exit() # Consider exiting if PaymentManager fails
         return # Do not proceed if PaymentManager fails


    # Call the startup function, passing dp, bot, and pm_instance
    await on_startup(dp, bot, pm_instance)

    # Initiate polling
    # In Aiogram v3.x, dp.start_polling() is used
    try:
        # --- Add webhook deletion here for clean polling start ---
        try:
            await bot.delete_webhook()
            logger.info("Residual webhook deleted (if it existed).")
        except Exception as e:
            logger.warning(f"Could not delete residual webhook: {e}")

        logger.info("Initiating bot polling (Aiogram v3.x)...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Error during bot polling: {e}", exc_info=True)
    finally:
        # Call the shutdown function
        await on_shutdown(dp)


if __name__ == '__main__':
    # This is the main entry point for running the script
    # Specific logging configuration for direct script execution
    logging.basicConfig(
        level=logging.DEBUG, # DEBUG level to see all details during tests
        format='%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s',
    )
    # Re-get loggers after reconfiguring
    logger = logging.getLogger(__name__)
    logging.getLogger('db').setLevel(logging.DEBUG) # Show db logs as well
    # Logging for src modules
    logging.getLogger('src.db').setLevel(logging.DEBUG)
    logging.getLogger('src.ton_api').setLevel(logging.DEBUG) # Changed from api to src.ton_api
    logging.getLogger('src.payment_manager').setLevel(logging.DEBUG)
    logging.getLogger('src.round_manager').setLevel(logging.DEBUG)
    logging.getLogger('src.simulation_engine').setLevel(logging.DEBUG)
    logging.getLogger('src.handlers').setLevel(logging.DEBUG)


    logging.getLogger('aioschedule').setLevel(logging.INFO) # Level for aioschedule

    logger.info("Preparing to run the bot (Aiogram v3.x) with asyncio.run...")
    try:
        asyncio.run(main()) # Execute the main asynchronous function
    except (KeyboardInterrupt, SystemExit):
        logger.info("Manual shutdown requested (KeyboardInterrupt/SystemExit).")
        # asyncio.run() should handle cleanup and call on_shutdown
    except Exception as e:
        logger.critical(f"Unexpected error running the bot with asyncio.run: {e}", exc_info=True)