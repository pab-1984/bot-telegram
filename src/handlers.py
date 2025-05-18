# src/handlers.py

# --- Importaciones de aiogram ---
from aiogram import Dispatcher, types # types y Dispatcher aquí
from aiogram import Bot # Importamos Bot en una línea separada
# --- Importaciones de Aiogram FSM (Corregidas para v3.x) ---
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# --- Fin Importaciones Aiogram FSM ---

# --- Importaciones de Aiogram Filters (Corregidas para v3.x) ---
from aiogram.filters import CommandStart, Command # Corregido a importación correcta en v3.x
# --- Fin Importaciones Aiogram Filters ---

import logging
import hashlib # Para generar comentario único
from datetime import datetime # Para timestamp en comentario único

# --- Importaciones de tu proyecto (Corregidas a absolutas) ---
# Asegúrate de que estas funciones existan en tu src/db.py fusionado y actualizado
from src.db import ( # Corregido a importación absoluta
    get_or_create_user,
    get_active_round, # Para obtener la ronda lógica activa
    # add_participant_to_round, # Si aún necesitas registrar participantes en la DB simulada
    # count_participants_in_round, # Si aún necesitas contar participantes en la DB simulada
    get_user_ton_payments_history, # Para /mis_pagos_ton
    update_user_ton_wallet, # Para guardar la wallet TON del usuario
    # add_ton_transaction # Ya se llama desde api.find_transaction
    # get_round_by_id # Si lo necesitas directamente en handlers
)

# Importamos el módulo api para interactuar con TON Center y verificar transacciones
from src import ton_api # Corregido a importación absoluta

# Importamos PaymentManager si aún tiene lógica necesaria (ej. generar comentario, validar dirección)
# Si PaymentManager solo envolvía la verificación de pago, esa lógica se mueve aquí.
# Si PaymentManager tiene lógica compleja de precios, etc., lo mantenemos.
# Asumiremos que PaymentManager ahora tiene métodos como get_standardized_wallet_address
# y quizás lógica para generar comentarios únicos o detalles de pago.
from src.payment_manager import PaymentManager # Corregido a importación absoluta

# from src.round_manager import RoundManager # Si tienes lógica compleja de rondas aquí

logger = logging.getLogger(__name__)

# --- Definición de Estados FSM ---
class BuyTicketStates(StatesGroup):
    awaiting_user_wallet_input = State() # Nuevo estado para pedir la wallet del usuario
    awaiting_payment_verification = State()

# --- Funciones de Handlers ---

async def cmd_start(message: types.Message, state: FSMContext):
    """Maneja el comando /start."""
    await state.finish()
    # Tu función get_or_create_user ya maneja la conexión a DB
    # Asegúrate de que get_or_create_user en db.py maneje username y first_name correctamente
    src.db.get_or_create_user(str(message.from_user.id), message.from_user.username, message.from_user.first_name) # Llamada con prefijo

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(types.KeyboardButton("🎟️ Comprar Boleto (/comprar_boleto)"))
    keyboard.add(types.KeyboardButton("📜 Mis Pagos TON (/mis_pagos_ton)")) # Texto del botón actualizado
    
    await message.answer(
        f"¡Bienvenido al Bot de Lotería TON, {message.from_user.first_name}!\n\n"
        "Usa los botones o comandos para interactuar.",
        reply_markup=keyboard
    )

async def cmd_buy_ticket_start(message: types.Message, state: FSMContext, pm_instance: PaymentManager):
    """Inicia el proceso de compra de un boleto."""
    await state.finish() # Asegurarse de que no hay estados previos activos

    # --- 1. Obtener información de la ronda lógica activa (si usas rondas lógicas) ---
    # Si tu lotería es continua o no usa rondas lógicas específicas, puedes omitir esto
    active_round_data = src.db.get_active_round() # Llamada con prefijo (Asume que esta función retorna un dict o None)
    
    if not active_round_data:
        await message.answer("Lo siento, no hay ninguna ronda de lotería activa en este momento. Intenta más tarde.")
        return
        
    # Asume que active_round_data es un diccionario con claves como 'id', 'ticket_price_simulated', etc.
    # Si get_active_round retorna una tupla, ajusta el acceso por índice (ej. active_round_data[0])
    active_round_id = active_round_data.get('id', 'N/A') # Usamos .get para seguridad
    ticket_price_ton = active_round_data.get('ticket_price_simulated', 1.0) # Obtener precio de la ronda o usar default

    ticket_price_nano = int(ticket_price_ton * (10**9))
    
    # --- 2. Generar Comentario Único para la Transacción ---
    # Este comentario asocia el pago a este usuario y esta ronda lógica
    # Puedes usar un hash o una combinación de datos para asegurar unicidad
    user_id_str = str(message.from_user.id)
    timestamp_nano = int(datetime.now().timestamp()) # Timestamp en segundos (entero)
    # Ejemplo simple de comentario único: L<round_id>U<user_id>T<timestamp>
    payment_comment_text = f"L{active_round_id}U{user_id_str}T{timestamp_nano}"
    # Asegúrate de que este formato de comentario sea compatible con el tamaño máximo permitido por TON (aprox 100 bytes)

    # --- 3. Obtener Dirección de la Wallet de Recepción del Bot ---
    bot_wallet_address = api.WALLET # Obtenido de config.json a través de api.py

    # --- 4. Guardar detalles del pago esperado en FSM ---
    await state.update_data(
        payment_comment=payment_comment_text,
        amount_nano=ticket_price_nano,
        bot_wallet_to_pay=bot_wallet_address,
        lottery_round_id=str(active_round_id), # Guardar como string para consistencia
        ticket_price_ton_display=ticket_price_ton,
        user_telegram_id=user_id_str # Guardar Telegram ID para usarlo en la verificación
    )

    # --- 5. Pedir la wallet TON al usuario (la que usará para pagar) ---
    # Esto es necesario para que find_transaction pueda buscar transacciones desde esa wallet.
    await message.answer(
        f"Vas a comprar un boleto para la ronda <b>{active_round_id}</b> por <b>{ticket_price_ton} TON</b>.\n\n"
        "Por favor, envía ahora la <b>dirección de tu wallet TON</b> (la que usarás para hacer el pago)."
        "Esta dirección se guardará para futuras compras y para el envío de premios si ganas.",
        parse_mode=types.ParseMode.HTML
    )
    # Cambiar al estado de espera de la wallet del usuario
    await BuyTicketStates.awaiting_user_wallet_input.set()


async def process_user_wallet_input(message: types.Message, state: FSMContext, pm_instance: PaymentManager):
    """Procesa la dirección de wallet TON enviada por el usuario."""
    user_wallet_raw = message.text.strip()
    user_id_str = str(message.from_user.id)
    
    # Validar y estandarizar la dirección de la wallet del usuario
    user_wallet_standardized = pm_instance.get_standardized_wallet_address(user_wallet_raw)

    if not user_wallet_standardized:
        await message.answer(
            "La dirección de wallet que enviaste no parece válida o no pudimos procesarla.\n"
            "Asegúrate de que sea una dirección de wallet TON correcta.\n"
            "Intenta enviarla de nuevo, o escribe /cancelar."
        )
        return 

    # Guardar la wallet estandarizada del usuario en FSM y en la DB (asociada a su Telegram ID)
    await state.update_data(user_sending_wallet=user_wallet_standardized)
    # Asegurar que el usuario existe y actualizar/registrar su wallet TON en la DB
    src.db.get_or_create_user(user_id_str, message.from_user.username, message.from_user.first_name) # Llamada con prefijo
    src.db.update_user_ton_wallet(user_id_str, user_wallet_standardized) # Llamada con prefijo


    # Recuperar otros datos del pago esperado desde FSM
    user_fsm_data = await state.get_data() 
    bot_wallet_address = user_fsm_data['bot_wallet_to_pay']
    amount_to_pay_nano = user_fsm_data['amount_nano']
    payment_comment_text = user_fsm_data['payment_comment']
    ticket_price_display = user_fsm_data['ticket_price_ton_display']

    # --- 6. Presentar Instrucciones de Pago y Botones Deep Link ---
    keyboard_payment_links = types.InlineKeyboardMarkup(row_width=1)
    # Asegúrate de usar la URL correcta para Testnet/Mainnet si es diferente para las wallets
    # api.WORK_MODE puede usarse para determinar si es testnet o mainnet
    
    # Construir URLs de deep link
    # Es buena práctica URL encode el comentario si contiene caracteres especiales, aunque para este formato simple no es crítico.
    # from urllib.parse import quote_plus
    # encoded_comment = quote_plus(payment_comment_text)
    
    tonkeeper_url = f"https://app.tonkeeper.com/transfer/{bot_wallet_address}?amount={amount_to_pay_nano}&text={payment_comment_text}"
    # Tonhub Testnet URL: test.tonhub.com, Mainnet URL: tonhub.com
    tonhub_url = f"https://{'test.' if api.WORK_MODE == 'testnet' else ''}tonhub.com/transfer/{bot_wallet_address}?amount={amount_to_pay_nano}&text={payment_comment_text}"
    # URL genérica ton://
    generic_ton_url = f"ton://transfer/{bot_wallet_address}?amount={amount_to_pay_nano}&text={payment_comment_text}"

    keyboard_payment_links.add(types.InlineKeyboardButton(text="🔷 Pagar con Tonkeeper", url=tonkeeper_url))
    keyboard_payment_links.add(types.InlineKeyboardButton(text="💎 Pagar con Tonhub", url=tonhub_url))
    keyboard_payment_links.add(types.InlineKeyboardButton(text="🚀 Pagar con otra wallet TON", url=generic_ton_url))

    # Botón para que el usuario confirme que ha pagado
    keyboard_confirm_action = types.InlineKeyboardMarkup(row_width=1)
    # Incluimos el comentario único en el callback_data para identificar la verificación
    keyboard_confirm_action.add(types.InlineKeyboardButton(text="✅ He realizado el pago", callback_data=f"verify_payment_{payment_comment_text}"))
    keyboard_confirm_action.add(types.InlineKeyboardButton(text="❌ Cancelar compra", callback_data="payment_cancel"))


    await message.answer(
        f"Gracias. Ahora, por favor, realiza el pago de <code>{ticket_price_display}</code> TON a la siguiente dirección del bot:\n"
        f"<code>{bot_wallet_address}</code>\n\n"
        f"<b>MUY IMPORTANTE:</b> Debes incluir el siguiente texto EXACTO como comentario/mensaje en tu transacción:\n"
        f"<code>{payment_comment_text}</code>\n\n"
        f"Realizarás el pago desde tu wallet:\n<code>{user_wallet_standardized}</code>\n\n"
        "Puedes usar los botones de abajo para abrir tu wallet con los datos precargados:",
        reply_markup=keyboard_payment_links,
        parse_mode=types.ParseMode.HTML
    )
    await message.answer(
        "Una vez que hayas completado la transacción en tu wallet, presiona el botón '✅ He realizado el pago'.",
        reply_markup=keyboard_confirm_action
    )
    
    # --- 7. Cambiar a Estado de Espera de Verificación ---
    await BuyTicketStates.awaiting_payment_verification.set()


# --- Handler para el botón "He realizado el pago" ---
# Escucha callbacks que empiezan con "verify_payment_"
# Corregida la anotación de tipo para bot_instance
async def callback_verify_payment(callback_query: types.CallbackQuery, state: FSMContext, pm_instance: PaymentManager, bot_instance: Bot):
    """Maneja el callback cuando el usuario confirma que ha pagado y solicita verificación."""
    # Extraer el comentario único del callback_data
    # El callback_data es "verify_payment_<comentario_unico>"
    callback_data_parts = callback_query.data.split('_', 2) # Divide en 3 partes: 'verify', 'payment', '<comentario_unico>'
    if len(callback_data_parts) != 3 or callback_data_parts[0] != 'verify' or callback_data_parts[1] != 'payment':
         logger.error(f"Callback data inesperado para verificación de pago: {callback_query.data}")
         await callback_query.answer("Error interno al procesar la solicitud.", show_alert=True)
         return # Salir si el formato del callback_data es incorrecto

    unique_comment_from_callback = callback_data_parts[2]

    # Responder inmediatamente al callback para quitar el reloj de carga
    await callback_query.answer("Verificando tu pago, esto puede tardar unos segundos...", show_alert=False)
    
    user_id_str = str(callback_query.from_user.id)
    user_fsm_data = await state.get_data()
    
    # Validar que los datos FSM necesarios estén presentes
    required_fsm_keys = ['user_sending_wallet', 'amount_nano', 'bot_wallet_to_pay', 'lottery_round_id']
    if not all(key in user_fsm_data for key in required_fsm_keys):
        logger.error(f"Faltan datos FSM para verificar pago para user {user_id_str}. Datos: {user_fsm_data}")
        await bot_instance.send_message(callback_query.message.chat.id, "Error interno: Faltan datos para verificar el pago. Por favor, intenta /comprar_boleto de nuevo.")
        await state.finish()
        return

    user_sending_wallet = user_fsm_data['user_sending_wallet']
    expected_amount_nano = user_fsm_data['amount_nano']
    # expected_bot_wallet = user_fsm_data['bot_wallet_to_pay'] # No necesario pasarlo a find_transaction
    lottery_round_id_assoc = user_fsm_data['lottery_round_id'] # ID de la ronda lógica

    # --- Llamar a la función de verificación de pago ---
    # api.find_transaction ya llama a db.check_transaction y db.add_ton_transaction
    # y asocia el Telegram ID si se le pasa.
    is_verified = api.find_transaction(
        user_wallet=user_sending_wallet, # La wallet desde donde el usuario pagó (estandarizada)
        value_nano=str(expected_amount_nano), # Monto esperado en nanoTONs (como string para la API)
        comment=unique_comment_from_callback, # El comentario único que esperamos
        telegram_id=user_id_str # Pasamos el Telegram ID para la asociación en DB
    )

    # --- Procesar el resultado de la verificación ---
    if is_verified:
        # Si la verificación fue exitosa, el pago ya está registrado en ton_transactions.
        # Ahora, si tu lógica de sorteo off-chain necesita registrar participantes
        # en una tabla separada (ej. round_participants) o asociar el pago a una ronda lógica
        # de manera más formal, hazlo aquí.
        
        # Ejemplo (si mantienes la tabla round_participants para la lógica de sorteo):
        # try:
        #     # Asignar número de participante y registrar en tabla round_participants
        #     current_participants_count = src.db.count_participants_in_round(int(lottery_round_id_assoc)) # Necesitas esta función
        #     assigned_number = current_participants_count + 1 # Lógica simple de asignación
        #
        #     src.db.add_participant_to_round( # Necesitas esta función en db.py
        #         round_id=int(lottery_round_id_assoc),
        #         telegram_id=user_id_str,
        #         assigned_number=assigned_number # O el número que corresponda
        #     )
        #     # Notificar al usuario con el número asignado (si aplica)
        #     await bot_instance.edit_message_text(...) # Mensaje con número asignado
        #
        # except Exception as e:
        #     logger.error(f"Error al registrar participante en ronda simulada {lottery_round_id_assoc} para user {user_id_str}: {e}")
        #     # Notificar al usuario sobre el problema en el registro del boleto
        #     await bot_instance.send_message(...)

        # Mensaje de éxito general si solo registras en ton_transactions
        await bot_instance.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=f"¡Pago confirmado! 🎉\nTu pago de <code>{expected_amount_nano / (10**9)}</code> TON para la ronda <b>{lottery_round_id_assoc}</b> ha sido verificado y registrado.\n"
                     f"¡Mucha suerte, {callback_query.from_user.first_name}!\n\n"
                     "Puedes ver tus pagos verificados con /mis_pagos_ton o iniciar otra compra con /comprar_boleto.",
            parse_mode=types.ParseMode.HTML,
            reply_markup=None # Eliminar botones inline
        )
        
        await state.finish() # Finalizar el estado FSM
    else:
        # Si find_transaction retornó False
        keyboard_retry_cancel = types.InlineKeyboardMarkup(row_width=1)
        # El callback_data para reintentar debe incluir el comentario único original
        keyboard_retry_cancel.add(types.InlineKeyboardButton(text="🔄 Reintentar Verificación", callback_data=f"verify_payment_{unique_comment_from_callback}"))
        keyboard_retry_cancel.add(types.InlineKeyboardButton(text="❌ Cancelar Compra", callback_data="payment_cancel"))
        
        # Intentar editar el mensaje anterior si es posible, si no, enviar uno nuevo
        try:
            await bot_instance.edit_message_text( 
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                text="No pudimos confirmar tu pago en este momento.\n"
                     "Asegúrate de que:\n"
                     "1. La transacción ya se haya confirmado en la red TON (puede tardar un poco).\n"
                     "2. Hayas enviado el monto exacto.\n"
                     "3. Hayas incluido el comentario correcto.\n"
                     "4. Hayas pagado desde la wallet que nos indicaste.\n\n"
                     "Puedes esperar unos segundos y reintentar la verificación o cancelar la compra.",
                reply_markup=keyboard_retry_cancel,
                parse_mode=types.ParseMode.HTML
            )
        except Exception:
            # Si falla la edición (ej. mensaje muy viejo), enviar un nuevo mensaje
            await bot_instance.send_message( 
                chat_id=callback_query.message.chat.id,
                text="No pudimos confirmar tu pago en este momento.\n"
                     "Asegúrate de que:\n"
                     "1. La transacción ya se haya confirmado en la red TON (puede tardar un poco).\n"
                     "2. Hayas enviado el monto exacto.\n"
                     "3. Hayas incluido el comentario correcto.\n"
                     "4. Hayas pagado desde la wallet que nos indicaste.\n\n"
                     "Puedes esperar unos segundos y reintentar la verificación o cancelar la compra.",
                reply_markup=keyboard_retry_cancel,
                parse_mode=types.ParseMode.HTML
            )


async def callback_payment_cancel(callback_query: types.CallbackQuery, state: FSMContext, bot_instance: Bot): # Corregida la anotación de tipo
    """Maneja la cancelación del proceso de pago."""
    await callback_query.answer("Compra cancelada.", show_alert=False)
    current_state = await state.get_state()
    if current_state is not None:
        await state.finish()
    
    # Intentar editar el mensaje anterior si es posible, si no, enviar uno nuevo
    try:
        await bot_instance.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text="La compra del boleto ha sido cancelada.",
            parse_mode=types.ParseMode.HTML,
            reply_markup=None # Eliminar botones inline
        )
    except Exception: 
        await bot_instance.send_message(callback_query.message.chat.id, "La compra del boleto ha sido cancelada.")
    
    # Opcional: Enviar un mensaje final para guiar al usuario
    # await bot_instance.send_message(callback_query.message.chat.id, "Puedes iniciar una nueva compra con /comprar_boleto o usar /start.")


async def cmd_cancel(message: types.Message, state: FSMContext):
    """Maneja el comando /cancelar para salir de cualquier estado FSM."""
    current_state = await state.get_state()
    if current_state is None or current_state == 'BuyTicketStates:firstState': # Si ya está en un estado inicial o sin estado
        await message.answer("No hay ninguna acción activa para cancelar.")
        return

    logger.info(f"Cancelando estado {current_state} para usuario {message.from_user.id}")
    await state.finish()
    await message.answer("Acción cancelada. Puedes usar /start o /comprar_boleto.")

async def cmd_my_paid_tickets(message: types.Message):
    """Muestra los boletos/pagos verificados del usuario."""
    user_id_str = str(message.from_user.id)
    
    # Asegura que el usuario exista en la DB
    src.db.get_or_create_user(user_id_str, message.from_user.username, message.from_user.first_name) # Llamada con prefijo
    
    # Obtiene el historial de pagos TON verificados desde la tabla ton_transactions
    user_payments = src.db.get_user_ton_payments_history(user_id_str) # Llamada con prefijo

    if not user_payments:
        await message.answer("No hemos encontrado pagos verificados asociados a tu cuenta de Telegram.\n"
                             "Asegúrate de haber completado alguna compra de boleto y que tu pago haya sido verificado por el bot.")
        return

    response_text = "<b>Historial de tus pagos verificados (Transacciones TON):</b>\n\n"
    for payment in user_payments:
        value_ton = payment['value_nano'] / (10**9)
        comment = payment['comment'] if payment['comment'] else "Sin comentario"
        # Puedes intentar extraer información de la ronda lógica del comentario si usas un formato específico
        round_info_display = comment # Por defecto muestra el comentario completo
        if comment and isinstance(comment, str) and comment.startswith('L') and 'U' in comment:
             try:
                 parts = comment.split('U')
                 round_id_part = parts[0][1:]
                 user_id_part = parts[1].split('T')[0] if 'T' in parts[1] else parts[1]
                 round_info_display = f"Ronda {round_id_part} (Usuario {user_id_part})"
             except Exception:
                 # Si falla el parseo, usar el comentario original
                 pass

        # Asegúrate de que 'user_ton_wallet' y 'transaction_hash' existan en el diccionario 'payment'
        user_wallet_display = payment.get('user_ton_wallet', 'Desconocida')
        tx_hash_display = payment.get('transaction_hash', 'Desconocido')
        tx_time_display = payment.get('transaction_time', 'Fecha desconocida')[:10] # Mostrar solo la fecha


        response_text += (f"🔹 Pago de <b>{value_ton:.2f} TON</b>\n"
                          f"   Comentario: <code>{comment}</code>\n"
                          f"   Desde Wallet: <code>{user_wallet_display}</code>\n"
                          f"   Hash TX: <code>{tx_hash_display[:10]}...</code>\n" 
                          f"   Fecha Verificación: {tx_time_display}\n" 
                          f"\n")
    
    await message.answer(response_text, parse_mode=types.ParseMode.HTML)


def register_all_handlers(dp: Dispatcher, bot_instance: Bot, pm_instance: PaymentManager): # Corregida la anotación de tipo
    """Registra todos los handlers en el dispatcher principal."""
    
    # db_instance no se pasa a los handlers individuales porque las funciones de db.py
    # que se llaman directamente ya gestionan su propia conexión.

    # Handlers de comandos y texto
    dp.register_message_handler(
        cmd_start, # No necesita pm_instance
        CommandStart(), state="*")
    
    dp.register_message_handler(
        lambda msg, state: cmd_buy_ticket_start(msg, state, pm_instance),
        Command("comprar_boleto"), state="*")
    dp.register_message_handler(
        lambda msg, state: cmd_buy_ticket_start(msg, state, pm_instance),
        text="🎟️ Comprar Boleto (/comprar_boleto)", state="*")
        
    # Handler para procesar la wallet del usuario
    dp.register_message_handler(
        lambda msg, state: process_user_wallet_input(msg, state, pm_instance),
        state=BuyTicketStates.awaiting_user_wallet_input)
        
    # Handler para el comando /cancelar
    dp.register_message_handler(cmd_cancel, Command("cancelar"), state="*")
    
    # Handler para el comando y botón de Mis Pagos TON
    dp.register_message_handler(cmd_my_paid_tickets, Command("mis_pagos_ton"), state="*")
    dp.register_message_handler(cmd_my_paid_tickets, text="📜 Mis Pagos TON (/mis_pagos_ton)", state="*")


    # Handlers de Callbacks (botones inline)
    # Handler para el botón "He realizado el pago" - Escucha callbacks que empiezan con "verify_payment_"
    dp.register_callback_query_handler(
        lambda cb_query, state: callback_verify_payment(cb_query, state, pm_instance, bot_instance),
        lambda c: c.data and c.data.startswith('verify_payment_'), state=BuyTicketStates.awaiting_payment_verification) # Asegurarse de que c.data no es None
        
    # Handler para el botón "Cancelar compra"
    dp.register_callback_query_handler(
        lambda cb_query, state: callback_payment_cancel(cb_query, state, bot_instance),
        lambda c: c.data == 'payment_cancel', state='*') # Puede cancelar desde cualquier estado


    logger.info("Handlers de src.handlers (versión Aiogram) registrados.")

