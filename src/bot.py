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
from src.db import ( # Corregido a importación absoluta
    init_db,
    get_rounds_by_status,
    get_round_by_id,
    get_participants_in_round,
    save_draw_results, # Usado por simulation_engine
    get_active_round, # <-- Corregido: Importamos get_active_round en lugar de get_open_rounds
    # Otras funciones de db.py que puedas necesitar directamente
)
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
              logger.error(f"JOB: Datos esenciales faltantes para ronda: {ronda_data}. Saltando.")
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
            p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p[0] # Acceso por clave o índice
            if p_telegram_id:
                 await bot_instance.send_message(p_telegram_id, msg_numero_sorteado, parse_mode=ParseMode.HTML) # Usar ParseMode
        except Exception as e: logger.error(f"JOB: Error enviando msg # sorteado a {p_telegram_id} para ronda {round_id}: {e}")

    # Llamar al motor de simulación para calcular premios y comisiones
    # Esta función debe estar definida en src/simulation_engine.py y ser async
    try:
        # Asegúrate de que calculate_and_save_simulated_payouts también se llame con prefijo si es necesario
        winners_messages, commissions_messages = await src.simulation_engine.calculate_and_save_simulated_payouts( 
            round_id, [drawn_winner_number], all_participants_data, r_type, str(r_creator_id) if r_creator_id else None
        )
    except Exception as e:
         logger.error(f"JOB: Error ejecutando calculate_and_save_simulated_payouts para ronda {round_id}: {e}", exc_info=True)
         winners_messages, commissions_messages = [], [] # Asegurar que sean listas vacías en caso de error


    # Enviar mensajes de ganadores
    if winners_messages:
        full_winners_message = f"🏆 <b>Resultados del Sorteo Simulado (Ronda ID <code>{round_id}</code>):</b>\n\n" + "\n".join(winners_messages)
        for p_data in all_participants_data:
            try:
                 p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
                 if p_telegram_id:
                      await bot_instance.send_message(p_telegram_id, full_winners_message, parse_mode=ParseMode.HTML) # Usar ParseMode
            except Exception as e: logger.error(f"JOB: Error enviando msg ganadores a {p_telegram_id} para ronda {round_id}: {e}")
    else:
        no_winner_msg = f"🥺 El número sorteado <b>{drawn_winner_number}</b> no tuvo un ganador asignado en la ronda {round_id}."
        for p_data in all_participants_data:
            try:
                 p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
                 if p_telegram_id:
                     await bot_instance.send_message(p_telegram_id, no_winner_msg, parse_mode=ParseMode.HTML) # Usar ParseMode
            except Exception as e: logger.error(f"JOB: Error enviando msg no ganador a {p_telegram_id} para ronda {round_id}: {e}")

    # Enviar mensajes de comisiones
    if commissions_messages:
        full_commissions_message = f"💸 <b>Comisiones Simuladas (Ronda ID <code>{round_id}</code>):</b>\n" + "\n".join(commissions_messages)
        for p_data in all_participants_data:
            try:
                 p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0] # Acceso por clave o índice
                 if p_telegram_id:
                     await bot_instance.send_message(p_telegram_id, full_commissions_message, parse_mode=ParseMode.HTML) # Usar ParseMode
            except Exception as e: logger.error(f"JOB: Error enviando msg comisiones a {p_telegram_id} para ronda {round_id}: {e}")

    # Marcar la ronda como finalizada
    if src.round_manager.update_round_status_manager(round_id, ROUND_STATUS_FINISHED): # Ejemplo de llamada con prefijo
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


# --- Definición de los Jobs para Aiogram ---
async def job_check_expired_rounds(bot_instance_for_job: Bot):
    logger.info("JOB: Iniciando `job_check_expired_rounds`...")
    
    # Ajusta estos tiempos según tu lógica de negocio. Para pruebas pueden ser más cortos.
    # Estos timedelta definen "hace cuánto tiempo" debe haber empezado una ronda para considerarla.
    # Leer de variables de entorno o config.json
    try:
        TIME_LIMIT_FOR_DRAW_MINUTES = int(os.getenv('JOB_DRAW_LIMIT_MINUTES', 1)) # Reducido a 60s para pruebas
        TIME_LIMIT_FOR_CANCELLATION_HOURS = int(os.getenv('JOB_CANCEL_LIMIT_HOURS', 1))
    except ValueError:
         logger.error("JOB: Variables de entorno de tiempo de job no son números válidos. Usando valores por defecto.")
         TIME_LIMIT_FOR_DRAW_MINUTES = 1
         TIME_LIMIT_FOR_CANCELLATION_HOURS = 1


    time_limit_for_draw_utc = datetime.now(timezone.utc) - timedelta(minutes=TIME_LIMIT_FOR_DRAW_MINUTES)
    time_limit_for_cancellation_utc = datetime.now(timezone.utc) - timedelta(hours=TIME_LIMIT_FOR_CANCELLATION_HOURS)
    
    logger.debug(f"JOB: Tiempo límite para sorteo: {time_limit_for_draw_utc.isoformat()}")
    logger.debug(f"JOB: Tiempo límite para cancelación: {time_limit_for_cancellation_utc.isoformat()}")


    # Obtener rondas que están esperando inicio o pagos, y no están marcadas como eliminadas
    rounds_to_check = src.db.get_rounds_by_status( # Ejemplo de llamada con prefijo
        [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS], 
        check_deleted=True 
    )
    logger.debug(f"JOB: Se encontraron {len(rounds_to_check)} rondas para verificar.")


    for ronda_data in rounds_to_check:
        if len(ronda_data) < 7:
            logger.warning(f"JOB: Datos de ronda incompletos: {ronda_data}. Saltando.")
            continue
            
        # Asumimos dict basado en db.py actualizado
        round_id = ronda_data.get('id')
        start_time_str = ronda_data.get('start_time')
        current_status = ronda_data.get('status')
        is_deleted = ronda_data.get('deleted', 0) # Default a 0 si la columna no existe o es NULL

        if round_id is None or start_time_str is None or current_status is None:
             logger.error(f"JOB: Datos esenciales faltantes para ronda: {ronda_data}. Saltando.")
             continue

        if is_deleted:
             logger.debug(f"JOB: Ronda {round_id} marcada como eliminada. Saltando.")
             continue

        logger.debug(f"JOB: Procesando ronda {round_id} (estado: {current_status}, inicio: {start_time_str}).")

        try:
            start_time_dt = datetime.fromisoformat(start_time_str)
            if start_time_dt.tzinfo is None: # Si es naive, asumimos UTC para comparación
                start_time_dt = start_time_dt.replace(tzinfo=timezone.utc)
            
            current_participants_count = src.round_manager.count_round_participants(round_id) # Ejemplo de llamada con prefijo
            logger.debug(f"JOB: Ronda {round_id} tiene {current_participants_count} participantes.")


            # Lógica de Sorteo por Tiempo
            # Solo si está en estado de espera y ha pasado el tiempo mínimo para sorteo
            if current_status in [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS] and start_time_dt < time_limit_for_draw_utc:
                if current_participants_count >= MIN_PARTICIPANTS_FOR_TIMED_DRAW:
                    logger.info(f"JOB: Ronda {round_id} ({current_participants_count} part.) elegible para sorteo por tiempo. Actualizando estado a '{ROUND_STATUS_DRAWING}'.")
                    # Actualizar estado a DRAWING ANTES de ejecutar el cierre para evitar re-procesamiento
                    if src.round_manager.update_round_status_manager(round_id, ROUND_STATUS_DRAWING): # Ejemplo de llamada con prefijo
                        logger.info(f"JOB: Estado de ronda {round_id} cambiado a '{ROUND_STATUS_DRAWING}'. Procediendo a cierre.")
                        # Ejecutar el cierre de ronda (sorteo simulado, payouts, notificaciones)
                        # Usamos create_task para no bloquear el job si el cierre es largo
                        asyncio.create_task(execute_simulated_round_closure(round_id, bot_instance_for_job))
                    else:
                        logger.error(f"JOB: No se pudo actualizar estado de ronda {round_id} a drawing para sorteo por tiempo.")
                # Lógica de Cancelación por Tiempo y Pocos Participantes
                # Solo si está en estado de espera y ha pasado el tiempo máximo para cancelación
                elif current_status in [ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS] and start_time_dt < time_limit_for_cancellation_utc:
                    logger.info(f"JOB: Ronda {round_id} ({current_participants_count} part.) elegible para cancelación por tiempo.")
                    if src.round_manager.update_round_status_manager(round_id, ROUND_STATUS_CANCELLED): # Ejemplo de llamada con prefijo
                        logger.info(f"JOB: Estado de ronda {round_id} cambiado a '{ROUND_STATUS_CANCELLED}'. Notificando participantes.")
                        participants_to_notify = src.db.get_participants_in_round(round_id) # Ejemplo de llamada con prefijo
                        cancel_msg = f"⚠️ La ronda ID <code>{round_id}</code> ha sido cancelada (pocos participantes / tiempo excedido)."
                        for p_data in participants_to_notify:
                            try:
                                p_telegram_id = p_data.get('telegram_id') if isinstance(p_data, dict) else p_data[0]
                                if p_telegram_id:
                                    await bot_instance_for_job.send_message(p_telegram_id, cancel_msg, parse_mode=ParseMode.HTML)
                            except Exception as e: logger.error(f"JOB: Error enviando msg cancelación a {p_telegram_id} para ronda {round_id}: {e}")
                    else:
                        logger.error(f"JOB: No se pudo actualizar estado de ronda {round_id} a cancelled.")
            
        except ValueError as ve:
            logger.error(f"JOB: Error convirtiendo start_time '{start_time_str}' para ronda {round_id}: {ve}")
        except Exception as e:
            logger.error(f"JOB: Error inesperado procesando ronda {round_id} en job_check_expired_rounds: {e}", exc_info=True)
            
    logger.info("JOB: `job_check_expired_rounds` finalizado.")


async def job_create_scheduled_round(bot_instance_for_job: Bot):
    logger.info("JOB: Iniciando `job_create_scheduled_round`...")
    
    open_rounds = src.round_manager.get_available_rounds() # Ejemplo de llamada con prefijo
    
    # Verificar si ya hay una ronda programada ('scheduled') que esté abierta
    # Recorremos las rondas abiertas y comprobamos su tipo
    scheduled_round_exists = False
    for r_data in open_rounds:
        # Aseguramos que r_data es un diccionario o tupla con suficientes elementos
        if isinstance(r_data, dict) and r_data.get('round_type') == ROUND_TYPE_SCHEDULED: # Corregido typo en variable
             scheduled_round_exists = True
             break
        elif isinstance(r_data, tuple) and len(r_data) > 4 and r_data[4] == ROUND_TYPE_SCHEDULED: # Asumiendo que round_type está en índice 4
             scheduled_round_exists = True
             break


    if not scheduled_round_exists:
        logger.info("JOB: No hay ronda programada abierta. Creando una nueva...")
        # Puedes definir el precio del boleto para rondas programadas aquí o en config.json
        DEFAULT_SCHEDULED_TICKET_PRICE = float(os.getenv('DEFAULT_SCHEDULED_TICKET_PRICE', 1.0))
        new_round_id = src.round_manager.create_round(round_type=ROUND_TYPE_SCHEDULED, creator_telegram_id=None, ticket_price=DEFAULT_SCHEDULED_TICKET_PRICE) # Corregido typo en variable
        if new_round_id:
            logger.info(f"JOB: Ronda programada automática creada con ID: {new_round_id}.")
            # Opcional: Notificar a un administrador si está configurado
            # ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID")
            # if ADMIN_ID:
            #     try: await bot_instance_for_job.send_message(ADMIN_ID, f"🤖 Nueva ronda programada {new_round_id} creada automáticamente.")
            #     except Exception as e: logger.error(f"JOB: Error notificando admin sobre nueva ronda {new_round_id}: {e}")
        else:
            logger.error("JOB: Falló la creación de la ronda programada automática.")
    else:
        logger.info("JOB: Ya existe una ronda programada abierta. No se crea nueva.")
    logger.info("JOB: `job_create_scheduled_round` finalizado.")


# --- Funciones de Arranque y Apagado ---
# Corregida la anotación de tipo para bot_instance
async def on_startup(dispatcher: Dispatcher, bot_instance: Bot, pm_instance: PaymentManager):
    logger.info("Iniciando bot (Aiogram)...")
    
    logger.debug("Inicializando base de datos...")
    try:
        db.init_db() # Llamada con prefijo
        logger.info("Base de datos inicializada.")
    except Exception as e:
        logger.critical(f"Error fatal al inicializar la base de datos: {e}", exc_info=True)
        # Considera si quieres que el bot se detenga aquí si la DB es crítica
        # exit() # Descomenta si quieres detener el bot si la DB falla
        return # No continuar si la DB falla

    logger.debug("Registrando handlers...")
    # Registrar todos los handlers de Aiogram
    # pm_instance (PaymentManager para TON) se pasa a register_all_handlers
    try:
        # pm_instance ya se crea en main y se pasa aquí
        src.handlers.register_all_handlers(dispatcher, bot_instance, pm_instance) # Llamada con prefijo, pasar bot_instance
        logger.info("Handlers de src.handlers (versión Aiogram) registrados.")
    except Exception as e:
         logger.critical(f"Error fatal al registrar handlers: {e}", exc_info=True)
         # exit() # Descomenta si quieres detener el bot si los handlers fallan
         return


    logger.debug("Estableciendo comandos del bot...")
    try:
        await bot_instance.set_my_commands([ # Usar bot_instance
            types.BotCommand("start", "🚀 Iniciar el bot"),
            types.BotCommand("comprar_boleto", "🎟️ Comprar Boleto (con TON)"),
            types.BotCommand("mis_pagos_ton", "📜 Mis Pagos (Pagos TON)"),
            types.BotCommand("cancelar", "❌ Cancelar acción actual"),
            # Puedes añadir aquí comandos para reglas de simulación o listar rondas simuladas si los mantienes
        ])
        logger.info("Comandos del bot establecidos.")
    except Exception as e:
         logger.error(f"Error al establecer comandos del bot: {e}", exc_info=True)


    # --- Configuración de Tareas Programadas con aioschedule ---
    logger.debug("Configurando tareas programadas con aioschedule...")
    # Los intervalos se pueden leer de variables de entorno o definirse aquí.
    # Para producción, intervalos más largos. Para pruebas, más cortos.
    try:
        CHECK_EXPIRED_INTERVAL_SECONDS = int(os.getenv('JOB_CHECK_EXPIRED_INTERVAL', 60)) # Reducido a 60s para pruebas
        CREATE_SCHEDULED_INTERVAL_SECONDS = int(os.getenv('JOB_CREATE_SCHEDULED_INTERVAL', 300)) # Cada 5 minutos
    except ValueError:
         logger.error("Variables de entorno de tiempo de job no son números válidos. Usando valores por defecto.")
         CHECK_EXPIRED_INTERVAL_SECONDS = 60
         CREATE_SCHEDULED_INTERVAL_SECONDS = 300


    logger.info(f"Configurando job 'check_expired_rounds' cada {CHECK_EXPIRED_INTERVAL_SECONDS} segundos.")
    # Pasar bot_instance_for_job a functools.partial
    aioschedule.every(CHECK_EXPIRED_INTERVAL_SECONDS).seconds.do(functools.partial(job_check_expired_rounds, bot_instance_for_job=bot_instance))
    
    logger.info(f"Configurando job 'create_scheduled_round' cada {CREATE_SCHEDULED_INTERVAL_SECONDS} segundos.") # Corregido typo
    # Pasar bot_instance_for_job a functools.partial
    aioschedule.every(CREATE_SCHEDULED_INTERVAL_SECONDS).seconds.do(functools.partial(job_create_scheduled_round, bot_instance_for_job=bot_instance))
    
    # Crear y lanzar la tarea del planificador
    async def scheduler():
        logger.info("Scheduler (aioschedule) iniciado. Ejecutando jobs iniciales tras breve espera...")
        # Ejecutar jobs una vez al inicio con un pequeño retraso
        await asyncio.sleep(5) # Espera 5 segundos antes de la primera ejecución
        logger.info("Ejecutando job_check_expired_rounds por primera vez...")
        asyncio.create_task(job_check_expired_rounds(bot_instance_for_job=bot_instance)) # Pasar bot_instance
        await asyncio.sleep(5) # Pequeño desfase
        logger.info("Ejecutando job_create_scheduled_round por primera vez...")
        asyncio.create_task(job_create_scheduled_round(bot_instance_for_job=bot_instance)) # Pasar bot_instance

        while True:
            await aioschedule.run_pending()
            await asyncio.sleep(1) # Espera 1 segundo entre verificaciones del planificador

    asyncio.create_task(scheduler()) # Lanza el planificador como una tarea de fondo
    logger.info("Planificador de tareas (aioschedule) configurado y tarea de fondo iniciada.")
    logger.info("Bot (Aiogram) iniciado y listo.")


async def on_shutdown(dispatcher: Dispatcher):
    logger.info("Apagando bot (Aiogram)...")
    
    # Detener tareas de aioschedule
    if hasattr(aioschedule, 'clear') and callable(getattr(aioschedule, 'clear')):
        aioschedule.clear() 
        logger.info("Tareas de aioschedule detenidas.")
    else:
        logger.warning("No se pudo llamar a aioschedule.clear().")

    # Cerrar almacenamiento FSM
    if dispatcher.storage: # Usar dispatcher.storage
        await dispatcher.storage.close()
        # await dispatcher.storage.wait_closed()
        logger.info("Almacenamiento FSM cerrado.")
    
    # Cerrar sesión del bot
    # En Aiogram 3.x, esto se maneja de forma un poco diferente.
    # `bot.session` puede no ser la forma correcta, se usa `await bot.close()` o se maneja por el ciclo de vida.
    # Si usas Aiogram 2.x:
    # if bot.session:
    #    await bot.session.close()
    # Para Aiogram 3.x, `await bot.close()` es más común si se necesita un cierre explícito.
    # O a menudo no se necesita nada explícito aquí para la sesión del bot.
    # Vamos a omitir el cierre explícito de sesión del bot para mayor compatibilidad,
    # ya que el executor de Aiogram suele manejarlo.

    logger.info("Bot (Aiogram) apagado.")


async def main():
    # Esta es la nueva función principal para Aiogram v3.x
    # La configuración de logging ya se hizo en if __name__ == '__main__':
    
    # --- Carga de Configuración del Bot (Movida dentro de main) ---
    CONFIG_FILE_PATH = 'config.json' # Ruta relativa al directorio raíz del proyecto
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            config = json.load(f)
            BOT_TOKEN = config.get('BOT_TOKEN')
            # BOT_USERNAME = config.get('BOT_USERNAME') # Si lo necesitas
    except FileNotFoundError:
        logger.critical(f"ERROR FATAL: {CONFIG_FILE_PATH} no encontrado.")
        return # No continuar si la configuración falla
    except json.JSONDecodeError:
        logger.critical(f"ERROR FATAL: {CONFIG_FILE_PATH} no es un JSON válido.")
        return # No continuar si la configuración falla
    except Exception as e:
        logger.critical(f"ERROR FATAL al cargar {CONFIG_FILE_PATH}: {e}")
        return # No continuar si la configuración falla

    if not BOT_TOKEN:
        logger.critical("ERROR FATAL: BOT_TOKEN está vacío en config.json.")
        return # No continuar si el token está vacío


    # --- Inicializar bot y dispatcher (CREAR INSTANCIAS AQUÍ) ---
    storage = MemoryStorage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)

    # --- Instanciar PaymentManager ---
    # PaymentManager ya no necesita db_instance si db.py gestiona su conexión
    try:
        pm_instance = PaymentManager()
    except ValueError as e:
         logger.critical(f"Error fatal al inicializar PaymentManager: {e}")
         # exit() # Considera salir si PaymentManager no inicializa
         return # No continuar si PaymentManager falla


    # Llamar a la función de arranque, pasando dp, bot y pm_instance
    await on_startup(dp, bot, pm_instance)

    # Iniciar el polling
    # En Aiogram v3.x, se usa dp.start_polling()
    try:
        logger.info("Iniciando polling del bot (Aiogram v3.x)...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Error durante el polling del bot: {e}", exc_info=True)
    finally:
        # Llamar a la función de apagado
        await on_shutdown(dp)


if __name__ == '__main__':
    # Este es el punto de entrada principal para ejecutar el script
    # Configuración de logging específica para la ejecución directa del script
    logging.basicConfig(
        level=logging.DEBUG, # Nivel DEBUG para ver todos los detalles en pruebas
        format='%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s',
    )
    # Re-obtener loggers después de reconfigurar
    logger = logging.getLogger(__name__)
    logging.getLogger('db').setLevel(logging.DEBUG) # Mostrar logs de db también
    logging.getLogger('api').setLevel(logging.DEBUG) # Mostrar logs de api también
    logging.getLogger('aioschedule').setLevel(logging.INFO) # Nivel para aioschedule

    logger.info("Preparando para ejecutar el bot (Aiogram v3.x) con asyncio.run...")
    try:
        asyncio.run(main()) # Ejecutar la función principal asíncrona
    except (KeyboardInterrupt, SystemExit):
        logger.info("Detención manual solicitada (KeyboardInterrupt/SystemExit).")
        # asyncio.run() debería manejar la limpieza y llamar a on_shutdown
    except Exception as e:
        logger.critical(f"Error inesperado al ejecutar el bot con asyncio.run: {e}", exc_info=True)

