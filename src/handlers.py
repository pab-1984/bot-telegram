# botloteria/src/handlers.py

# Añadimos este print temporal para verificar si el archivo se carga
print("--> Cargando handlers.py - Versión Final Integrada y sin Confirmación de Pago <--")

import os
# Importaciones necesarias
# Importamos todas las clases relevantes de telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, WebAppInfo
# Importamos todos los handlers y filtros necesarios de telegram.ext
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import logging
import random # Necesario para el sorteo
from datetime import datetime, timedelta # Importar datetime y timedelta

# Importar funciones de base de datos que se usan directamente en handlers
from .db import (
    get_or_create_user, # Gestión de usuario básica
    # count_paid_participants_in_round, # <-- Ya no necesitamos contar pagos aquí
    # update_participant_paid_status # <-- Ya no necesitamos actualizar pago aquí, lo hace round_manager
)

# Importar las funciones y constantes de gestión de rondas desde round_manager.py
from .round_manager import (
    create_round,
    get_round,
    get_available_rounds,
    add_participant, # <-- La lógica de pago está dentro de esta función ahora
    count_round_participants,
    update_round_status_manager,
    get_round_participants_data, # Necesitamos esta para obtener la lista de participantes para mensajes
    # Importamos constantes (ahora incluyendo las nuevas de límites de participantes)
    MIN_PARTICIPANTS, # Límite máximo (10)
    MIN_PARTICIPANTS_FOR_TIMED_DRAW, # Mínimo para sorteo por tiempo (2)
    MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW, # Máximo para sorteo inmediato (10)
    # DRAW_NUMBERS_COUNT, # Ya no usamos esta constante directamente aquí, la lógica del sorteo en payment_manager determina cuántos números sortear (1) y cuántos ganadores hay
    ROUND_STATUS_WAITING_TO_START,
    ROUND_STATUS_WAITING_FOR_PAYMENTS, # Este estado cambia su significado/uso
    ROUND_STATUS_DRAWING,
    ROUND_STATUS_FINISHED,
    ROUND_STATUS_CANCELLED,
    ROUND_TYPE_SCHEDULED,
    ROUND_TYPE_USER_CREATED
)


# Importar funciones de gestión de pagos desde payment_manager.py
from .payment_manager import (
    # handle_simulated_payment_confirmation, # <-- ELIMINADA: Ya no necesitamos importar este handler de confirmación aquí
    perform_payout_calculation_and_save, # Función para calcular y guardar premios/comisiones
    # generate_simulated_smart_contract_address # No es necesario importarla aquí, se llama desde db.py
)

# Importar constantes de porcentaje de payment_manager para usarlas en reglas
from .payment_manager import (
    COMMISSION_PERCENT_GAS_SIMULATED,
    COMMISSION_PERCENT_BOT,
    COMMISSION_PERCENT_USER_CREATOR
)
BOT_USERNAME='TONLottoMasterBot'

logger = logging.getLogger(__name__)

# --- Constantes de Juego (Las mínimas necesarias en handlers) ---


# --- Handlers de Comandos ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /start y deep links."""
    user = update.effective_user # Obtiene el usuario que ejecutó el comando
    user_id_str = str(user.id)
    username = user.username or f"user_{user.id}" # Usa el username si existe, si no, un placeholder

    # Registrar o obtener usuario en la DB
    get_or_create_user(user_id_str, username) # Llama a la función de db.py

    # --- Manejo de Deep Link para unirse a rondas ---
    # Verifica si el comando /start vino con un argumento (payload de deep link)
    if context.args and len(context.args) > 0:
        deep_link_payload = context.args[0] # Obtiene el argumento (ej: 'join_round_21')
        logger.info(f"Usuario {user_id_str} inició el bot con deep link payload: {deep_link_payload}")

        # Si el payload indica que se quiere unir a una ronda
        if deep_link_payload.startswith('join_round_'):
            try:
                # Extraer el ID de la ronda del payload (ej: 'join_round_21' -> '21')
                round_id_str = deep_link_payload.split('join_round_')[1]
                round_id = int(round_id_str) # Convertir el ID a entero
                logger.info(f"Intentando unirse a ronda {round_id} vía deep link.")

                # Llama a la lógica de unión de participante. El pago es automático al unirse.
                # Pasa update y context para que process_join_logic pueda enviar mensajes.
                await process_join_logic(update, context, round_id, user_id_str, username)


                return # Termina el manejo del start command si se procesó un deep link válido

            except ValueError:
                logger.warning(f"Deep link payload 'join_round_' con ID no numérico: {deep_link_payload}")
                await update.message.reply_html(f"⚠️ Enlace de ronda inválido: El ID debe ser un número.")
                # Si el deep link es inválido, continuamos mostrando el mensaje de inicio normal

        # Puedes añadir manejo para otros tipos de deep links aquí si los necesitas
        # elif deep_link_payload == 'some_other_action':
        #    ... procesar otro tipo de deep link ...


    # Si no hay deep link válido o no se reconoció, muestra el mensaje de inicio normal


    # --- Define la URL de tu Web App aquí ---
    # Esta URL debe ser la dirección HTTPS pública donde has desplegado tu aplicación Flask.
    # Durante el desarrollo, usa ngrok o similar. ¡Debe ser HTTPS!
    web_app_url = "https://c649-2802-8011-210f-5a01-6917-2aa9-684b-a009.ngrok-free.app" # <-- ¡¡¡DEBES REEMPLAZAR ESTA CADENA CON LA URL REAL!!!
    # Asegúrate de que esta URL sea accesible desde Internet y use HTTPS.


    # Define los botones para el Reply Keyboard (menú principal)
    keyboard = [
        [KeyboardButton("🏆 Rondas Abiertas"), KeyboardButton("➕ Crear Ronda")], # Primera fila
        [
            KeyboardButton("📚 Reglas del Juego"), # Segunda fila
            KeyboardButton("🎮 Abrir Interfaz Gráfica", web_app=WebAppInfo(url=web_app_url)) # <-- BOTÓN DE LA WEB APP
        ] # Segunda fila
    ]
    # Crea el ReplyKeyboardMarkup con los botones definidos
    # resize_keyboard=True: hace que el teclado sea más pequeño en la interfaz de Telegram
    # one_time_keyboard=False: hace que el teclado permanezca visible después de usar un botón
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


    # Envía el mensaje de bienvenida con el Reply Keyboard adjunto
    await update.message.reply_html(
        f"👋 ¡Hola, {user.mention_html()}! 👋\n\n" # Emoji y mención HTML del usuario
        "🤖 Soy el bot del TON Ten Challenge.\n" # Emoji
        "¡Usa los botones de abajo o escribe los comandos (/list_rounds, /create_round, /rules_mvp) para interactuar! ✨\n\n" # Emoji
        "También puedes usar el botón '🎮 Abrir Interfaz Gráfica' para una experiencia visual más completa en la Web App." # Menciona el botón de la Web App
        ,
        reply_markup=reply_markup # Adjuntar el Reply Keyboard al mensaje
    )
    logger.info(f"Usuario {user_id_str} ({username}) inició el bot con Reply Keyboard y opción de Web App.")


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /rules_mvp."""
    rules_text = (
        f"📚 <b>Reglas Generales (Simulación):</b>\n\n"
        f"1️⃣ Entrada por ronda: <b>1 Unidad</b> (simulado). La entrada se 'paga' automáticamente al unirse a una ronda abierta.\n"
        f"2️⃣ Una ronda cierra y sortea si se cumplen las condiciones:\n"
        f"   - Si llega a <b>{MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW}</b> participantes: Sorteo Inmediato.\n"
        f"   - Si tiene entre <b>{MIN_PARTICIPANTS_FOR_TIMED_DRAW} y {MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW-1}</b> participantes y pasan <b>30 minutos</b> desde su creación: Sorteo por Tiempo.\n"
        f"   - Si tiene menos de <b>{MIN_PARTICIPANTS_FOR_TIMED_DRAW}</b> participantes y pasa <b>1 hora</b>: Ronda Cancelada.\n"
        f"3️⃣ Los números asignados van del 1 al N, donde N es el número total de participantes que se unieron (y pagaron).\n"
        f"4️⃣ Se sortea **1** número ganador entre los números asignados a los participantes que pagaron.\n\n"

        f"➡️ Usa el botón '🏆 Rondas Abiertas' o /list_rounds para ver rondas abiertas y unirte directamente.\n"
        f"➡️ Usa el botón '➕ Crear Ronda' o /create_round para crear tu ronda personal.\n\n"

        f"⏱️ El sorteo inicia automáticamente cuando se cumplen las condiciones de cierre (10 participantes o tiempo/participantes).\n\n"
    )
    # Distribución de Ganancias (Simulación - Porcentajes)
    rules_text += (
        f"\n💰 <b>Distribución de Ganancias (Simulación - Basado en Porcentajes del Total Recaudado):</b>\n\n"

        f"➡️ Comisiones Fijas (del Total Recaudado):\n"
        # --- CORREGIDO: Usar nombres de constantes directamente ---
        f"   - Fondo para Gas Simulado: <b>{int(COMMISSION_PERCENT_GAS_SIMULATED*100)}%</b>\n"
        f"   - Comisión Bot (Tú): <b>{int(COMMISSION_PERCENT_BOT*100)}%</b>\n"
        f"   - Comisión Creador (solo Ronda Usuario): <b>{int(COMMISSION_PERCENT_USER_CREATOR*100)}%</b>\n\n"

        f"➡️ Pozo para Premios (restante): <b>{int(100 - COMMISSION_PERCENT_GAS_SIMULATED*100 - COMMISSION_PERCENT_BOT*100)}%</b> (Ronda Bot) o <b>{int(100 - COMMISSION_PERCENT_GAS_SIMULATED*100 - COMMISSION_PERCENT_BOT*100 - COMMISSION_PERCENT_USER_CREATOR*100)}%</b> (Ronda Usuario)\n\n"

        f"➡️ Distribución del Pozo de Premios entre Ganadores:\n"
        f"   - El único ganador del número sorteado recibe el <b>100%</b> del Pozo para Premios restante.\n\n"

        f"<i>(¡Esto es una simulación, no se usan TON reales!)</i>"
    )

    await update.message.reply_html(rules_text)


async def list_rounds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /list_rounds y muestra botones para unirse."""
    user = update.effective_user
    open_rounds = get_available_rounds()

    if not open_rounds:
        await update.message.reply_text("❌ Actualmente no hay rondas abiertas a las que unirse. Usa el botón '➕ Crear Ronda' o /create_round para iniciar una.")
        logger.info(f"Usuario {user.id} solicitó lista de rondas abiertas. No hay rondas.")
        return

    message_text = "🏆 <b>Rondas Abiertas:</b>\n\n"
    inline_keyboard_buttons = []

    for ronda in open_rounds:
        if len(ronda) >= 5:
            ronda_id, start_time_str, status, round_type, simulated_contract_address = ronda
            participants_count = count_round_participants(ronda_id) # Total de participantes unidos

            try:
                start_time = datetime.fromisoformat(start_time_str)
                time_elapsed = datetime.now() - start_time
                minutes, seconds = divmod(time_elapsed.total_seconds(), 60)
                hours, minutes = divmod(minutes, 60)
                time_elapsed_str = ""
                if hours > 0:
                     time_elapsed_str += f"{int(hours)}h "
                time_elapsed_str += f"{int(minutes)}m"
                time_elapsed_str = f" ({time_elapsed_str} ago)" if time_elapsed.total_seconds() > 0 else ""
            except ValueError:
                time_elapsed_str = " (Error tiempo)"
                logger.warning(f"Error al calcular tiempo transcurrido para ronda {ronda_id}, start_time: {start_time_str}")
            except Exception as e:
                 time_elapsed_str = " (Error tiempo)"
                 logger.error(f"Error inesperado al calcular tiempo transcurrido para ronda {ronda_id}: {e}")


            message_text += (
                f"--- Ronda ID: <code>{ronda_id}</code> ---\n"
                f" Tipo: {round_type.replace('_', ' ').title()}\n"
                f" Estado: {status.replace('_', ' ').title()}\n"
                f" Participantes: {participants_count}/10\n" # Mostrar vs el límite de 10
                f" Iniciada: {datetime.fromisoformat(start_time_str).strftime('%Y-%m-%d %H:%M')}{time_elapsed_str}\n"
                f" Contrato Sim.: <code>{simulated_contract_address}</code>\n"
            )

            # Crear botón "Unirse"
            callback_data = f"join_{ronda_id}"
            button = InlineKeyboardButton(f"➡️ Unirse a esta Ronda ({ronda_id})", callback_data=callback_data)
            inline_keyboard_buttons.append([button])

        else:
             logger.error(f"get_available_rounds devolvió tupla inesperada para ronda: {ronda}")
             message_text += f"⚠️ Error al mostrar detalles de ronda (ID {ronda[0] if len(ronda)>0 else '?'}).\n---\n"

    message_text += "\n👆 Usa los botones de 'Unirse' arriba para participar directamente."

    reply_markup = InlineKeyboardMarkup(inline_keyboard_buttons)

    await update.message.reply_html(
        message_text,
        reply_markup=reply_markup
    )
    logger.info(f"Usuario {user.id} solicitó lista de rondas abiertas. Mostrando {len(open_rounds)} rondas con botones de unión.")


async def create_round_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /create_round."""
    user = update.effective_user
    user_id_str = str(user.id)
    username = user.username or f"user_{user.id}"

    get_or_create_user(user_id_str, username)

    round_id = create_round(round_type=ROUND_TYPE_USER_CREATED, creator_telegram_id=user_id_str)

    if round_id is None:
        await update.message.reply_text("❌ Ocurrió un error al crear tu ronda personal. Intenta de nuevo más tarde.")
        logger.error(f"Falló la creación de ronda de usuario para {user_id_str}.")
        return

    created_round_data = get_round(round_id)
    simulated_contract_address = "Dirección no disponible"
    if created_round_data and len(created_round_data) >= 8:
         simulated_contract_address = created_round_data[7]

    # --- AÑADE ESTE LOG DE DEPURACIÓN AQUÍ ---
    logger.debug(f"Valor de BOT_USERNAME al generar Deep Link: '{BOT_USERNAME}'") # <-- Nuevo log

    # --- Generar y enviar el Deep Link de la ronda creada ---
    if BOT_USERNAME: # Verificar si el username del bot está configurado y no es None/vacío
         # ... (código para construir el deep link y enviar el mensaje con el enlace) ...
         # Asegúrate que aquí dentro se usa el logger.info correcto "Deep Link generado: ..."
         deep_link_payload = f"join_round_{round_id}"
         round_share_url = f"https://t.me/{BOT_USERNAME}?start={deep_link_payload}"

         await update.message.reply_html(
             f"✨ ¡Has creado una ronda personal! 🎉\n\n"
             f"Su ID es <code>{round_id}</code>.\n"
             f"La dirección simulada del Smart Contract es: <code>{simulated_contract_address}</code>\n\n"
             f"Comparte este enlace con tus amigos para que se unan directamente:\n" # Texto actualizado
             f"🔗 <a href='{round_share_url}'>Unirse a Ronda {round_id}</a>\n\n" # El enlace real como un Deep Link HTML
             f"La ronda sorteará al llegar a <b>{MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW}</b> participantes o si tiene entre <b>{MIN_PARTICIPANTS_FOR_TIMED_DRAW} y {MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW-1}</b> participantes y pasan <b>30 minutos</b>. ¡Invita a tus amigos! 👍" # Explica la lógica de cierre
         )
         logger.info(f"Usuario {user_id_str} ({username}) creó ronda personal con ID {round_id}, Dir Sim: {simulated_contract_address}. Deep Link generado: {round_share_url}")


    else: # Si BOT_USERNAME es None, una cadena vacía o evaluated como False
         logger.warning("Username del bot (BOT_USERNAME) no configurado o es inválido. No se puede generar Deep Link para compartir.") # <-- Este log
         await update.message.reply_html(
             f"✨ ¡Has creado una ronda personal con ID <code>{round_id}</code>! 🎉\n\n"
             f"La dirección simulada del Smart Contract es: <code>{simulated_contract_address}</code>\n\n"
             f"<b>⚠️ No se pudo generar el enlace directo para compartir.</b> Asegúrate de que el username del bot esté configurado correctamente en el archivo .env.\n\n"
             f"Pide a tus amigos que se unan usando el comando: <code>/join_round {round_id}</code>\n\n"
             f"La ronda sorteará al llegar a <b>{MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW}</b> participantes o si tiene entre <b>{MIN_PARTICIPANTS_FOR_TIMED_DRAW} y {MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW-1}</b> participantes y pasan <b>30 minutos</b>. ¡Invita a tus amigos! 👍"
         )


# --- Refactorizamos la lógica de unión común en una función para reutilizarla ---
# Esta función ahora procesa la unión, marca el pago automático y verifica si gatilla sorteo por 10 participantes.
async def process_join_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, round_id: int, user_id_str: str, username: str) -> None:
    """
    Contiene la lógica común para añadir un participante a una ronda,
    marcar el pago automático al unirse y verificar si gatilla sorteo por 10 participantes.
    Es llamada por join_round_command y handle_callback_query.
    """
    # Llama a la función en round_manager para añadir al participante.
    # add_participant ahora marca el pago como real simulado automáticamente si la unión es exitosa.
    # Retorna (éxito: bool, mensaje: str, assigned_number: int | None, current_participants_count: int)
    success_join, message_reply, assigned_number, current_participants_count = add_participant(round_id, user_id_str, username) # Llama a round_manager


    # --- Enviar mensaje de respuesta al usuario usando context.bot.send_message ---
    # Este mensaje indica si se unió con éxito o si hubo un error (ronda llena, ya unido, etc.)
    # El mensaje ya incluye confirmación de que el boleto está "comprado" si la unión fue exitosa.
    try:
        # Usamos context.bot.send_message con el chat_id del usuario
        await context.bot.send_message(chat_id=user_id_str, text=message_reply, parse_mode='HTML')
    except Exception as e:
         logger.error(f"Error al enviar mensaje de respuesta (unión) a usuario {user_id_str}: {e}")


    if not success_join:
         logger.warning(f"Usuario {user_id_str} falló al unirse a ronda {round_id}. Mensaje: {message_reply}")
         return # Salir si la unión falló


    # Si la unión fue exitosa (y el pago marcado automáticamente), continuamos.

    # --- Verificamos si la ronda AHORA alcanzó 10 participantes ---
    # current_participants_count fue retornado por add_participant y ya está actualizado si la unión tuvo éxito.
    if current_participants_count == MAX_PARTICIPANTS_FOR_IMMEDIATE_DRAW: # Verificar si el total de participantes unidos llega a 10
        logger.info(f"Ronda {round_id} alcanzó 10 participantes. Estado cambia a '{ROUND_STATUS_WAITING_FOR_PAYMENTS}'.") # Cambiamos a waiting_for_payments temporalmente
        update_round_status_manager(round_id, ROUND_STATUS_WAITING_FOR_PAYMENTS) # Llama a round_manager

        # Obtenemos los datos completos de la ronda para el mensaje a todos.
        target_round_data_full = get_round(round_id)
        round_smart_contract_address_full_msg = "ERROR_AL_OBTENER_DIRECCION"
        if target_round_data_full and len(target_round_data_full) >= 8:
            round_smart_contract_address_full_msg = target_round_data_full[7]
        else:
           logger.error(f"Datos incompletos al obtener ronda {round_id} para enviar mensaje de ronda llena a todos.")

        # Obtener todos los participantes en la ronda para notificarles
        all_participants_data = get_round_participants_data(round_id) # Llama a round_manager

        round_full_message = (
             f"🎉 ¡La ronda ID <code>{round_id}</code> alcanzó 10 participantes! 🎉\n\n"
             f"Los <b>10</b> participantes están listos.\n"
             f"El sorteo simulado se gatillará en breve.\n\n" # Texto actualizado: sorteo gatillado
             f"Contrato Sim.: <code>{round_smart_contract_address_full_msg}</code>" # Información del contrato
        )
        # Enviar el mensaje a cada participante en la ronda
        for participant in all_participants_data:
             try:
                 await context.bot.send_message(chat_id=participant[0], text=round_full_message, parse_mode='HTML')
             except Exception as e:
                  logger.error(f"Error al enviar mensaje de ronda llena (10 part.) a usuario {participant[0]}: {e}")

        logger.info(f"Ronda {round_id} alcanzó 10 participantes. Mensaje de ronda llena enviado.")

        # --- Gatillar sorteo inmediato si llega a 10 participantes ---
        # Como todos están pagados al unirse, podemos pasar al estado de sorteo y gatillarlo.
        # Cambiar estado a drawing inmediatamente después de waiting_for_payments simulado.
        logger.info(f"Gatillando cambio de estado a '{ROUND_STATUS_DRAWING}' y sorteo inmediato para ronda {round_id}.")
        update_round_status_manager(round_id, ROUND_STATUS_DRAWING) # Llama a round_manager
        # Llamar a la función que coordina el sorteo. Pasa update y context.
        await perform_simulated_draw_and_payout(update, context, round_id)


    # Nota: La lógica de gatillar sorteo por tiempo (30min, 2-9 part.) se maneja en el Job de check_expired_rounds.


async def join_round_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /join_round. Llama a la lógica común de unión."""
    user = update.effective_user
    user_id_str = str(user.id)
    username = user.username or f"user_{user.id}"
    get_or_create_user(user_id_str, username)

    round_id_to_join = None

    if context.args:
        try:
            round_id_to_join = int(context.args[0])
            logger.info(f"Usuario {user_id_str} intentó unirse a ronda con ID (via command arg): {round_id_to_join}")

        except ValueError:
            await update.message.reply_html("⚠️ Uso incorrecto. Para unirte a una ronda específica, usa <code>/join_round [ID_de_ronda]</code>. Usa el botón '🏆 Rondas Abiertas' o /list_rounds para ver las IDs.")
            logger.warning(f"Usuario {user_id_str} usó /join_round con argumento no numérico: {context.args[0]}")
            return

    else:
        logger.info(f"Usuario {user_id_str} usó /join_round sin argumento. Buscando ronda programada abierta.")
        open_rounds = get_available_rounds()
        scheduled_rounds = [r for r in open_rounds if r[3] == ROUND_TYPE_SCHEDULED]

        if not scheduled_rounds:
             await update.message.reply_text("❌ No hay rondas 'programadas' abiertas a las que unirse. Usa el botón '🏆 Rondas Abiertas' para ver todas las rondas abiertas o '➕ Crear Ronda' para crear la tuya.")
             logger.info(f"Usuario {user_id_str} usó /join_round sin ID y no encontró ronda programada abierta.")
             return

        if len(scheduled_rounds[0]) >= 5:
             round_id_to_join = scheduled_rounds[0][0]
             logger.info(f"Usuario {user_id_str} usó /join_round sin ID. Seleccionando ronda programada {round_id_to_join}.")

        else:
             logger.error(f"get_available_rounds devolvió tupla incompleta para ronda programada: {scheduled_rounds[0]}")
             await update.message.reply_text("❌ Ocurrió un error interno al obtener los detalles de la ronda programada. Intenta de nuevo más tarde.")
             return

    # Llama a la lógica de unión común. El pago es automático al unirse.
    # Pasa update y context.
    await process_join_logic(update, context, round_id_to_join, user_id_str, username)


# --- ELIMINAMOS EL HANDLER confirm_payment_command ---
# Este handler ya no es necesario para la confirmación de pago inicial.
# Puedes borrar completamente la función confirm_payment_command.
# Si decides darle un nuevo propósito (ej: verificar estado de pago), deberías re-implementarla.
# Por ahora, la eliminamos para reflejar el flujo simplificado.

# async def confirm_payment_command(...) -> None:
#     """Maneja el comando /confirm_payment (AHORA OBSOLETO para confirmación inicial)."""
#     pass # Eliminar contenido o toda la función


# --- Handler para manejar las pulsaciones de botones en línea (Callback Queries) ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja las pulsaciones de botones en línea.
    Procesa el callback_data para realizar acciones como unirse a una ronda.
    """
    query = update.callback_query # Obtiene el objeto CallbackQuery

    await query.answer() # Responde a la callback query para quitar el estado de carga del botón.

    user = query.from_user # Obtiene la información del usuario que pulsó el botón
    user_id_str = str(user.id)
    username = user.username or f"user_{user.id}"

    data = query.data # Obtiene el callback_data (ej: 'join_21')

    logger.info(f"Callback query recibida de usuario {user_id_str} ({username}): {data}")

    # --- Procesar el dato de la callback query ---
    if data.startswith('join_'):
        try:
            round_id = int(data.split('_')[1]) # Extraer el ID de la ronda

            # Llama a la lógica de unión común (definida arriba). El pago es automático al unirse.
            # Pasa update y context desde la callback query.
            await process_join_logic(update, context, round_id, user_id_str, username)


        except ValueError:
            logger.warning(f"Callback data 'join_' con ID no numérico: {data} de usuario {user_id_str}.")
            # Enviamos mensaje de error al usuario que pulsó el botón
            try:
                # Usamos context.bot.send_message con el chat_id del usuario
                await context.bot.send_message(chat_id=user.id, text="⚠️ Error al procesar la solicitud. ID de ronda inválido.", parse_mode='HTML')
            except Exception as e:
                 logger.error(f"Error al enviar mensaje de error de valor a usuario {user.id}: {e}")
        except Exception as e:
            logger.error(f"Error inesperado en handle_callback_query (join) para usuario {user_id_str}: {e}")
            # Enviamos mensaje de error al usuario que pulsó el botón
            try:
                # Usamos context.bot.send_message con el chat_id del usuario
                await context.bot.send_message(chat_id=user.id, text="❌ Ocurrió un error inesperado al procesar tu solicitud. Intenta de nuevo más tarde.", parse_mode='HTML')
            except Exception as e:
                 logger.error(f"Error al enviar mensaje de error inesperado a usuario {user.id}: {e}")


    # ... (Puedes añadir más 'elif' para manejar otros tipos de botones en línea) ...


# --- Handler para el Texto de los Botones del Reply Keyboard ---
# Este handler es responsable de procesar el texto enviado por los botones del ReplyKeyboardMarkup.
async def handle_reply_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los mensajes de texto que coinciden con los botones del Reply Keyboard."""
    text = update.message.text
    user = update.effective_user

    logger.info(f"Usuario {user.id} ({user.username}) envió texto: '{text}' (posible botón de Reply Keyboard)")

    # Compara el texto del mensaje con el texto de tus botones del Reply Keyboard
    # Si coincide, llama al handler de comando correspondiente.
    if text == "🏆 Rondas Abiertas":
        logger.info(f"Texto '{text}' coincide con '🏆 Rondas Abiertas'. Llamando a list_rounds_command.")
        await list_rounds_command(update, context)

    elif text == "➕ Crear Ronda":
        logger.info(f"Texto '{text}' coincide con '➕ Crear Ronda'. Llamando a create_round_command.")
        await create_round_command(update, context)

    elif text == "📚 Reglas del Juego":
        logger.info(f"Texto '{text}' coincide con '📚 Reglas del Juego'. Llamando a rules_command.")
        await rules_command(update, context)

    # Nota: El botón "🎮 Abrir Interfaz Gráfica" con WebAppInfo NO envía su texto
    # como mensaje normal al bot. Telegram abre la Web App directamente.
    # Por lo tanto, ese botón no necesita ser manejado aquí.


# --- Función que coordina el Sorteo y el Cálculo/Guardado de Pagos ---
# Esta función es llamada por process_join_logic (si se alcanzan 10 part.)
# y por el job check_expired_rounds (cuando se cumple el tiempo para 2-9 part.).
# Está en handlers.py porque necesita enviar mensajes a los usuarios, lo cual requiere update/context.
async def perform_simulated_draw_and_payout(update: Update | None, context: ContextTypes.DEFAULT_TYPE, round_id: int) -> None:
    """
    Coordina la ejecución del sorteo simulado y llama a la lógica de cálculo y guardado de pagos en payment_manager.
    Envía mensajes de resultados y comisiones a todos los participantes.
    Finalmente, marca la ronda como finalizada. Puede ser llamada desde un handler (con update) o un job (sin update).
    """
    logger.info(f"Coordinando sorteo y pago simulado para ronda {round_id}. Llamada desde {'handler' if update else 'job'}.")


    # Obtener la ronda para verificar su estado y tipo.
    target_round = get_round(round_id) # Llama a round_manager

    # Verificar que el estado sea 'drawing' antes de proceder.
    if not target_round or len(target_round) < 8 or target_round[3] != ROUND_STATUS_DRAWING: # target_round[3] es el estado
         logger.warning(f"Intento de sortear ronda {round_id} con estado inesperado o datos incompletos: {target_round}. Cancelando sorteo.")
         error_msg = f"❌ Error interno: No se cumplen las condiciones para sortear la ronda ID <code>{round_id}</code>. La ronda no está en estado de sorteo o hay un problema de datos."

         # Enviar el mensaje de error a todos los participantes si es posible
         participants_data_if_available = get_round_participants_data(round_id) # Llama a round_manager
         if participants_data_if_available:
             for participant in participants_data_if_available:
                 try:
                     await context.bot.send_message(chat_id=participant[0], text=error_msg, parse_mode='HTML')
                 except Exception as e:
                     logger.error(f"Error al enviar mensaje de error de sorteo a usuario {participant[0]}: {e}")
         # Si la llamada vino de un handler y hay un usuario efectivo, también se lo enviamos
         elif update and update.effective_user: # Solo si update es válido y hay un usuario efectivo
             try:
                 await update.message.reply_html(error_msg)
             except Exception as e:
                  logger.error(f"Error al enviar mensaje de error de sorteo al usuario efectivo {update.effective_user.id}: {e}")
         else:
              logger.error(f"No se pudieron enviar mensajes de error de sorteo para ronda {round_id}.")


         update_round_status_manager(round_id, ROUND_STATUS_CANCELLED) # Llama a round_manager
         return


    # Desempaquetar datos de la ronda para pasarlos a la lógica de cálculo de pago/comisión
    ronda_id_actual = target_round[0] # ID de la ronda
    round_type = target_round[4] # Tipo de ronda ('scheduled' o 'user_created')
    creator_id = target_round[5]


    # Obtener la lista de TODOS los participantes en la ronda de la DB.
    # Ya que todos se consideran pagados al unirse, esta es la lista relevante para el sorteo y cálculo.
    all_participants_data = get_round_participants_data(ronda_id_actual) # Llama a round_manager

    # En la nueva lógica, el sorteo se gatilla si hay entre 2 y 10 participantes unidos (y pagados automáticamente).
    current_participants_count = len(all_participants_data)
    if current_participants_count < MIN_PARTICIPANTS_FOR_TIMED_DRAW: # Mínimo 2 para sorteo
         logger.error(f"Intento de sorteo en ronda {ronda_id_actual} con menos de {MIN_PARTICIPANTS_FOR_TIMED_DRAW} participantes ({current_participants_count}). Cancelando sorteo.")
         error_msg = f"❌ Error interno: La ronda ID <code>{ronda_id_actual}</code> no tiene suficientes participantes unidos para realizar el sorteo. Cancelando."
         # Enviar mensaje de error a los participantes si es posible
         if all_participants_data: # Usar la lista de todos los participantes
             for participant in all_participants_data:
                 try:
                     await context.bot.send_message(chat_id=participant[0], text=error_msg, parse_mode='HTML')
                 except Exception as e:
                     logger.error(f"Error al enviar mensaje de error de sorteo a usuario {participant[0]}: {e}")
         elif update and update.effective_user:
              try:
                  await update.message.reply_html(error_msg)
              except Exception as e:
                   logger.error(f"Error al enviar mensaje de error de sorteo al usuario efectivo {update.effective_user.id}: {e}")
         else:
              logger.error(f"No se pudieron enviar mensajes de error de sorteo para ronda {ronda_id_actual}.")

         update_round_status_manager(ronda_id_actual, ROUND_STATUS_CANCELLED)
         return


    # --- Ejecutar el Sorteo ---
    # Crear una lista de números asignados a TODOS los participantes unidos.
    available_numbers = [p[2] for p in all_participants_data] # p[2] es el assigned_number

    # En la nueva lógica, siempre sorteamos 1 número.
    numbers_to_draw = 1

    if len(available_numbers) < numbers_to_draw:
         logger.error(f"No hay suficientes números asignados ({len(available_numbers)}) para sortear {numbers_to_draw} en ronda {ronda_id_actual}. Cancelando sorteo.")
         error_msg = f"❌ Error interno: No hay suficientes números asignados para realizar el sorteo en la ronda ID <code>{ronda_id_actual}</code>. Cancelando."
         # Enviar mensaje de error a los participantes si es posible
         if all_participants_data:
             for participant in all_participants_data:
                 try:
                      await context.bot.send_message(chat_id=participant[0], text=error_msg, parse_mode='HTML')
                 except Exception as e:
                     logger.error(f"Error al enviar mensaje de error de sorteo a usuario {participant[0]}: {e}")
         elif update and update.effective_user:
              try:
                  await update.message.reply_html(error_msg)
              except Exception as e:
                   logger.error(f"Error al enviar mensaje de error de sorteo al usuario efectivo {update.effective_user.id}: {e}")
         else:
              logger.error(f"No se pudieron enviar mensajes de error de sorteo para ronda {ronda_id_actual}.")

         update_round_status_manager(ronda_id_actual, ROUND_STATUS_CANCELLED)
         return


    # Realizar sorteo del número ganador entre los números de los participantes UNIDOS.
    drawn_numbers = random.sample(available_numbers, numbers_to_draw) # numbers_to_draw = 1
    drawn_winner_number = drawn_numbers[0] # El único número sorteado

    logger.info(f"Número sorteado simulado para ronda {ronda_id_actual}: {drawn_winner_number} (sorteado entre {len(available_numbers)} unidos).")

    # Enviar mensaje del número sorteado a todos los participantes si es posible
    draw_result_message = f"🎉 ¡Número sorteado simulado para ronda ID <code>{ronda_id_actual}</code>! 🎉\nEl número ganador es: <b>{drawn_winner_number}</b>"
    if all_participants_data:
        for participant in all_participants_data:
             try:
                  await context.bot.send_message(chat_id=participant[0], text=draw_result_message, parse_mode='HTML')
             except Exception as e:
                  logger.error(f"Error al enviar mensaje de resultados de sorteo a usuario {participant[0]}: {e}")
    elif update and update.effective_user:
         try:
              await update.message.reply_html(draw_result_message)
         except Exception as e:
              logger.error(f"Error al enviar mensaje de resultados de sorteo al usuario efectivo {update.effective_user.id}: {e}")
    else:
         logger.error(f"No se pudieron enviar mensajes de resultados de sorteo para ronda {ronda_id_actual}.")


    # --- Calcular y Guardar Premios/Comisiones ---
    # Llama a la función en payment_manager.
    # Pasa el número sorteado y la lista de TODOS los participantes unidos para el cálculo.
    winners_list_for_message, commissions_list_for_message = perform_payout_calculation_and_save(
        ronda_id_actual, drawn_numbers, all_participants_data, round_type, creator_id # Pasa TODOS los datos de participantes unidos
    )


    # Anunciar ganadores en Telegram a todos los participantes si es posible
    if winners_list_for_message:
        winners_message = (
            f"🏆 <b>¡Resultados del sorteo simulado para ronda ID <code>{ronda_id_actual}</code>!</b> 🏆\n\n"
            "¡Este es el afortunado ganador simulado!\n"
            + "\n".join(winners_list_for_message) +
            "\n\n"
        )
        if all_participants_data: # Enviar a TODOS los participantes unidos
            for participant in all_participants_data:
                 try:
                     await context.bot.send_message(chat_id=participant[0], text=winners_message, parse_mode='HTML')
                 except Exception as e:
                     logger.error(f"Error al enviar mensaje de ganadores a usuario {participant[0]}: {e}")
        elif update and update.effective_user:
             try:
                  await update.message.reply_html(winners_message)
             except Exception as e:
                  logger.error(f"Error al enviar mensaje de ganadores al usuario efectivo {update.effective_user.id}: {e}")
        else:
             logger.error(f"No se pudieron enviar mensajes de ganadores para ronda {ronda_id_actual}.")

        logger.info(f"Ganadores simulados anunciados para ronda {ronda_id_actual}.")
    else:
        no_winners_message = f"🥺 Nadie ganó en esta ronda simulada ID <code>{ronda_id_actual}</code>."
        if all_participants_data:
            for participant in all_participants_data:
                 try:
                      await context.bot.send_message(chat_id=participant[0], text=no_winners_message, parse_mode='HTML')
                 except Exception as e:
                      logger.error(f"Error al enviar mensaje de no ganadores a usuario {participant[0]}: {e}")
        elif update and update.effective_user:
             try:
                  await update.message.reply_html(no_winners_message)
             except Exception as e:
                  logger.error(f"Error al enviar mensaje de no ganadores al usuario efectivo {update.effective_user.id}: {e}")
        else:
             logger.error(f"No se pudieron enviar mensajes de no ganadores para ronda {ronda_id_actual}.")


    #Mensaje final de comisión y aviso de pago por Smart Contract (Usando la lista de mensajes de comisiones)
    if commissions_list_for_message:
         message_comissions_and_payout = (
            f"💸 <b>Comisiones simuladas para ronda ID <code>{ronda_id_actual}</code>:</b>\n"
            + "\n".join(commissions_list_for_message) +
            f"\n\n✨ El Smart Contract de la ronda procesará la distribución de premios y comisiones (simulado)."
         )
         if all_participants_data:
             for participant in all_participants_data:
                  try:
                       await context.bot.send_message(chat_id=participant[0], text=message_comissions_and_payout, parse_mode='HTML')
                  except Exception as e:
                       logger.error(f"Error al enviar mensaje de comisiones a usuario {participant[0]}: {e}")
         elif update and update.effective_user:
              try:
                  await update.message.reply_html(message_comissions_and_payout)
              except Exception as e:
                   logger.error(f"Error al enviar mensaje de comisiones al usuario efectivo {update.effective_user.id}: {e}")
         else:
              logger.error(f"No se pudieron enviar mensajes de comisiones para ronda {ronda_id_actual}.")


         logger.info(f"Mensajes de comisiones y pago por contrato enviados para ronda {ronda_id_actual}.")

    else:
        logger.warning(f"No se generaron mensajes de comisiones para ronda {ronda_id_actual}.")


    #Marcar ronda como finalizada en la base de datos
    update_round_status_manager(ronda_id_actual, ROUND_STATUS_FINISHED)
    final_message = f"✅ Ronda de simulación ID <code>{ronda_id_actual}</code> finalizada y marcada como terminada."
    if all_participants_data:
        for participant in all_participants_data:
             try:
                  await context.bot.send_message(chat_id=participant[0], text=final_message, parse_mode='HTML')
             except Exception as e:
                 logger.error(f"Error al enviar mensaje de finalización a usuario {participant[0]}: {e}")
    elif update and update.effective_user:
         try:
             await update.message.reply_html(final_message)
         except Exception as e:
              logger.error(f"Error al enviar mensaje de finalización al usuario efectivo {update.effective_user.id}: {e}")
    else:
         logger.error(f"No se pudieron enviar mensajes de finalización para ronda {ronda_id_actual}.")


    logger.info(f"Ronda {ronda_id_actual} finalizada y estado actualizado a '{ROUND_STATUS_FINISHED}'.")