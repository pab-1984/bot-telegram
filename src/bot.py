import os
# Importamos todas las clases necesarias aquí
from telegram.ext import Application, CommandHandler, MessageHandler, filters, JobQueue, ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv
import logging
# Necesario para los jobs y el manejo de tiempo, ahora importamos timezone
from datetime import datetime, timedelta, timezone # <-- Importamos timezone


# Importar la función de inicialización de DB
from .db import init_db
from .db import get_rounds_by_status # Asegúrate que esta función esté en db.py
# from .db import count_paid_participants_in_round # <-- Ya no necesitamos contar pagos aquí en el job

# Importar handlers (asegúrate que handle_callback_query, handle_reply_button_text y perform_simulated_draw_and_payout estén importados)
from .handlers import (
    start_command,
    rules_command,
    join_round_command,
    list_rounds_command,
    create_round_command,
    # confirm_payment_command, # <-- Este handler fue eliminado, no lo importamos
    handle_callback_query,
    handle_reply_button_text,
    perform_simulated_draw_and_payout # <-- Importa la función coordinadora del sorteo para llamarla desde el job
)

# Importar funciones necesarias de round_manager para los jobs
from .round_manager import create_round, get_available_rounds, update_round_status_manager, get_round_participants_data, count_round_participants # <-- Importar count_round_participants
# Importa las constantes de estado y tipo de ronda desde round_manager
from .round_manager import (
    # MIN_PARTICIPANTS, # Límite máximo (10)
    MIN_PARTICIPANTS_FOR_TIMED_DRAW, # Mínimo para sorteo por tiempo (2)
    MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW, # Máximo (10)
    ROUND_STATUS_WAITING_TO_START,
    ROUND_STATUS_WAITING_FOR_PAYMENTS, # Estado de espera (temporal antes de drawing)
    ROUND_STATUS_DRAWING,
    ROUND_STATUS_CANCELLED,
    ROUND_TYPE_SCHEDULED,
    # ROUND_TYPE_USER_CREATED # No se usa directamente en este job
)


# Cargar variables de entorno desde .env
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)


logger = logging.getLogger(__name__)

# --- Funciones para los Jobs (JobQueue) ---

async def check_expired_rounds(context: ContextTypes.DEFAULT_TYPE):
    """Job para sortear rondas con >= 2 participantes unidos después de 30 min,
       o cancelar rondas con < 2 participantes unidos después de 1 hora."""
    logger.info("Ejecutando job: check_expired_rounds (Timed Draw/Cancellation)")

    # Define los límites de tiempo en UTC
    # time_limit_for_draw representa el punto en el tiempo 30 minutos atrás en UTC.
    time_limit_for_draw = datetime.now(timezone.utc) - timedelta(minutes=2)
    # time_limit_for_cancellation representa el punto en el tiempo 1 hora atrás en UTC.
    time_limit_for_cancellation = datetime.now(timezone.utc) - timedelta(hours=1)


    # Obtener rondas en estado de espera que NO estén marcadas como eliminadas
    # get_rounds_by_status retorna (id, start_time_str, status, round_type, creator_id, deleted, simulated_address) - 7 elementos
    rounds_to_check = get_rounds_by_status([ROUND_STATUS_WAITING_TO_START, ROUND_STATUS_WAITING_FOR_PAYMENTS], check_deleted=True)

    for ronda_data in rounds_to_check:
         if len(ronda_data) >= 7:
            round_id, start_time_str, status, round_type, creator_id, deleted, simulated_address = ronda_data
            try:
                 # Convertir start_time a datetime y ASIGNARLE la zona horaria UTC para comparación
                 # Esto asume que los timestamps guardados en la DB son UTC o comparables a UTC.
                 start_time = datetime.fromisoformat(start_time_str).replace(tzinfo=timezone.utc) # <-- Asignar UTC

                 # Contar el número total de participantes unidos
                 current_participants_count = count_round_participants(round_id)


                 # --- Lógica de Decisión: Sorteo por Tiempo o Cancelación ---

                 # Si la ronda ha pasado el límite de tiempo para gatillar el sorteo (más de 30 minutos de antigüedad)...
                 if start_time < time_limit_for_draw:

                      # Y si tiene suficientes participantes unidos para realizar un sorteo (2 o más)...
                      if current_participants_count >= MIN_PARTICIPANTS_FOR_TIMED_DRAW:
                           logger.info(f"Ronda {round_id} (estado: {status}, unidos: {current_participants_count}, inicio UTC: {start_time}) es elegible para sorteo por tiempo (>{timedelta(minutes=30)} antigua y >={MIN_PARTICIPANTS_FOR_TIMED_DRAW} unidos). Iniciando sorteo...")

                           # Cambiar estado a drawing
                           update_round_status_manager(round_id, ROUND_STATUS_DRAWING)

                           # Llamar a la función que coordina el sorteo y los pagos. Pasar update=None.
                           await perform_simulated_draw_and_payout(None, context, round_id)


                      # Si no tiene suficientes participantes unidos (< 2)...
                      else:
                           # Y si además ha pasado el tiempo límite para cancelación (más de 1 hora de antigüedad)...
                           if start_time < time_limit_for_cancellation:
                                logger.info(f"Ronda {round_id} (estado: {status}, unidos: {current_participants_count}, inicio UTC: {start_time}) superó 1 hora y tiene menos de {MIN_PARTICIPANTS_FOR_TIMED_DRAW} participantes unidos. Cancelando...")

                                # Marcar la ronda como cancelada
                                update_round_status_manager(round_id, ROUND_STATUS_CANCELLED)

                                # Notificar a los participantes de la ronda cancelada
                                participants_data_for_cancellation = get_round_participants_data(round_id)

                                cancel_message = f"⚠️ La ronda ID <code>{round_id}</code> ha sido cancelada porque no se unieron suficientes participantes a tiempo (límite de 1 hora)."

                                for participant in participants_data_for_cancellation:
                                     try:
                                         await context.bot.send_message(chat_id=participant[0], text=cancel_message, parse_mode='HTML')
                                     except Exception as e:
                                         logger.error(f"Error al enviar mensaje de cancelación a usuario {participant[0]} para ronda {round_id}: {e}")
                           # Si tiene menos de 2 participantes pero aún no ha pasado 1 hora, simplemente se mantiene en espera.


                 # Si la ronda AÚN NO ha pasado el límite de 30 minutos para gatillar el sorteo por tiempo, simplemente la ignoramos en este job.


            except ValueError:
                logger.error(f"Error al convertir start_time '{start_time_str}' a datetime para ronda {round_id}. Skipping.")
            except Exception as e:
                logger.error(f"Error inesperado al procesar ronda {round_id} en check_expired_rounds: {e}", exc_info=True)
         else:
             logger.warning(f"Datos de ronda de get_rounds_by_status con número inesperado de elementos: {ronda_data}")


    logger.info("Job check_expired_rounds (Timed Draw/Cancellation) finalizado.")


async def create_scheduled_round_job(context: ContextTypes.DEFAULT_TYPE):
    """Job para crear automáticamente una ronda programada si no hay una abierta."""
    logger.info("Ejecutando job: create_scheduled_round_job")

    # Verificar si ya existe una ronda programada abierta (waiting_to_start o waiting_for_payments)
    open_rounds = get_available_rounds() # get_available_rounds ya filtra por estos estados y deleted = 0
    scheduled_round_exists = any(r[3] == ROUND_TYPE_SCHEDULED for r in open_rounds) # r[3] es round_type

    if scheduled_round_exists:
        logger.info("Ya existe una ronda programada abierta. No se crea una nueva.")
        return

    # Si no hay ronda programada abierta, crear una nueva
    logger.info("No hay ronda programada abierta. Creando una nueva...")
    # Llama a la función en round_manager para crear la ronda programada.
    round_id = create_round(round_type=ROUND_TYPE_SCHEDULED, creator_telegram_id=None)

    if round_id:
        logger.info(f"Ronda programada automática creada con ID: {round_id}.")
        # Opcional: Notificar al admin o a un canal específico
        # try:
        #     await context.bot.send_message(chat_id=YOUR_ADMIN_CHAT_ID, text=f"🤖 Ronda programada automática creada con ID {round_id}.")
        # except Exception as e:
        #     logger.error(f"Error al enviar mensaje de creación de ronda automática a admin: {e}")
    else:
        logger.error("Falló la creación de la ronda programada automática.")


    logger.info("Job create_scheduled_round_job finalizado.")


def main() -> None:
    """Inicia el bot."""

    # Inicializar la base de datos
    init_db()
    logger.info("Base de datos inicializada.")

    # Verificar que el token del bot esté configurado
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == 'TU_TOKEN_OBTENIDO_DE_BOTFATHER':
        logger.error("TELEGRAM_BOT_TOKEN no encontrado o es el placeholder. Por favor, edita el archivo .env")
        return

    # Crear la Application y pasarle el token de tu bot.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- Obtener y Configurar JobQueue ---
    # Asegúrate de haber instalado "python-telegram-bot[job-queue]"
    job_queue = application.job_queue # <-- Obtienes JobQueue aquí, fuera del if
    if job_queue is None:
        logger.error("JobQueue no está disponible. Asegúrate de haber instalado python-telegram-bot con la opción [job-queue].")
        # Podrías decidir salir aquí si los jobs son críticos, o continuar sin ellos.
        # Por ahora, el código intentará continuar, pero los jobs no se ejecutarán.
    else:
        logger.info("JobQueue inicializado y disponible.")
        # Programar el job de verificación de rondas expiradas (sorteo/cancelación)
        # Se ejecuta cada 5 minutos (interval=300 segundos). Asegúrate que este es el intervalo deseado.
        job_queue.run_repeating(check_expired_rounds, interval=15, first=5) # first=10 para ejecutar 10 segundos después de iniciar

        # Programar el job de creación de rondas programadas
        # Se ejecuta cada 6 horas (interval=6*3600 segundos = 21600 segundos). Ajusta si necesitas.
        job_queue.run_repeating(create_scheduled_round_job, interval=60, first=15) # first=30 para ejecutar 30 segundos después de iniciar


    # Registrar handlers de comandos (primero, para darles prioridad)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("rules_mvp", rules_command))
    application.add_handler(CommandHandler("join_round", join_round_command))
    application.add_handler(CommandHandler("list_rounds", list_rounds_command))
    application.add_handler(CommandHandler("create_round", create_round_command))
    # confirm_payment_command ya no se registra, fue eliminado.

    # Registrar el Handler para Callback Queries (Pulsaciones de botones Inline)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # --- Registrar el Nuevo Handler para Mensajes de Texto (Reply Keyboard) ---
    # Este handler responderá a cualquier mensaje de texto que NO sea un comando.
    # Colocarlo después de los CommandHandlers asegura que los comandos tengan prioridad.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_button_text)) # <-- Registrar el nuevo handler

    # Iniciar el bot
    logger.info("Bot iniciado y escuchando...")
    application.run_polling(poll_interval=3.0)


if __name__ == "__main__":
    main()