# src/handlers.py

# --- Importaciones de aiogram ---
from aiogram import Dispatcher, types # types y Dispatcher aquí
from aiogram import Bot # Importamos Bot en una línea separada
# --- Importaciones de Aiogram FSM (Corregidas para v3.x) ---
# Ya NO importamos StateFilter aquí porque la importación falla.
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# --- Fin Importaciones Aiogram FSM ---

# --- Importaciones de Aiogram Filters (Corregidas para v3.x) ---
# Ya NO importamos Text aquí porque la importación falla.
from aiogram.filters import CommandStart, Command
# --- Fin Importaciones Aiogram Filters ---

import logging
import hashlib # Para generar comentario único
from datetime import datetime # Para timestamp en comentario único

# --- Importaciones de tu proyecto (Corregidas a absolutas) ---
# Asegúrate de que estas funciones existan en tu src/db.py fusionado y actualizado
import src.db # <-- Importamos el módulo db para usar src.db.function_name

# Importamos el módulo api para interactuar con TON Center y verificar transacciones
import src.ton_api as ton_api # Corregido a importación absoluta y usamos alias

# Importamos PaymentManager si aún tiene lógica necesaria (ej. generar comentario, validar dirección)
import src.payment_manager as payment_manager # Corregido a importación absoluta y usamos alias


logger = logging.getLogger(__name__)

# --- Definición de Estados FSM ---
class BuyTicketStates(StatesGroup):
    awaiting_user_wallet_input = State() # Nuevo estado para pedir la wallet del usuario
    awaiting_payment_verification = State()

# --- Funciones de Handlers ---

async def cmd_start(message: types.Message, state: FSMContext):
    """Maneja el comando /start."""
    # --- VERIFICACIÓN DE ESTADO INTERNA (WORKAROUND) ---
    # Este handler debería ejecutarse solo en el estado por defecto (None)
    current_state = await state.get_state()
    if current_state is not None:
         # Si el usuario está en otro estado, ignoramos el /start aquí
         # O podrías enviar un mensaje como: "Ya estás en medio de una acción. Usa /cancelar si quieres detenerla."
         logger.debug(f"Ignoring /start command from user {message.from_user.id} in state {current_state}")
         return
    # --- FIN VERIFICACIÓN DE ESTADO ---

    # --- CORRECCIÓN AQUÍ ---
    await state.clear() # Usar .clear() en lugar de .finish()
    # --- Fin CORRECCIÓN ---

    # Tu función get_or_create_user ya maneja la conexión a DB
    # Asegúrate de que get_or_create_user en db.py maneje username y first_name correctamente
    src.db.get_or_create_user(str(message.from_user.id), message.from_user.username, message.from_user.first_name) # Llamada con prefijo

    # --- CORRECCIÓN AQUÍ: Crear KeyboardButton y luego ReplyKeyboardMarkup ---
    # Crear los botones
    button1 = types.KeyboardButton(text="🎟️ Comprar Boleto (/comprar_boleto)")
    button2 = types.KeyboardButton(text="📜 Mis Pagos TON (/mis_pagos_ton)")

    # Organizar los botones en filas (lista de listas)
    # Si quieres cada botón en su propia fila, usa [[button1], [button2]]
    # Si quieres ambos botones en la misma fila, usa [[button1, button2]]
    # Siguiendo la idea de row_width=1 que tenías, creamos cada uno en su fila.
    keyboard_layout = [
        [button1],
        [button2]
    ]

    # Crear ReplyKeyboardMarkup pasando el layout a través del argumento 'keyboard'
    # Puedes mantener resize_keyboard=True si quieres que el teclado se ajuste
    # row_width no es necesario si pasas el layout completo.
    keyboard = types.ReplyKeyboardMarkup(keyboard=keyboard_layout, resize_keyboard=True)
    # --- Fin CORRECCIÓN ---

    # Eliminar las llamadas .add() que ahora no son necesarias
    # keyboard.add(types.KeyboardButton("🎟️ Comprar Boleto (/comprar_boleto)")) # Eliminar
    # keyboard.add(types.KeyboardButton("📜 Mis Pagos TON (/mis_pagos_ton)")) # Eliminar

    await message.answer(
        f"¡Bienvenido al Bot de Lotería TON, {message.from_user.first_name}!\n\n"
        "Usa los botones o comandos para interactuar.",
        reply_markup=keyboard
    )

async def cmd_buy_ticket_start(message: types.Message, state: FSMContext, pm_instance: payment_manager.PaymentManager): # Usar alias payment_manager
    """Inicia el proceso de compra de un boleto."""
    # --- VERIFICACIÓN DE ESTADO INTERNA (WORKAROUND) ---
    # Este handler debería ejecutarse solo en el estado por defecto (None)
    current_state = await state.get_state()
    if current_state is not None:
         # Si el usuario está en otro estado, ignoramos el comando o sugerimos cancelar
         logger.debug(f"Ignoring /comprar_boleto command from user {message.from_user.id} in state {current_state}")
         await message.answer(f"Ya estás en medio de una acción ({current_state}). Usa /cancelar si quieres detenerla antes de comprar un boleto.")
         return
    # --- FIN VERIFICACIÓN DE ESTADO ---

    # --- VERIFICACIÓN DE TEXTO INTERNA (WORKAROUND para botón) ---
    # Este handler se registrará para el comando /comprar_boleto Y para el texto del botón.
    # Verificamos si el mensaje es el texto EXACTO del botón O el comando.
    expected_button_text = "🎟️ Comprar Boleto (/comprar_boleto)"
    expected_command_text = "/comprar_boleto"
    
    if message.text and message.text != expected_button_text and message.text.lower() != expected_command_text:
         # Si el texto no coincide con el botón ni con el comando esperado, ignorar
         logger.debug(f"Ignoring message text '{message.text}' from user {message.from_user.id} for cmd_buy_ticket_start.")
         return # Ignorar mensajes que no son el botón o comando /comprar_boleto
    # --- FIN VERIFICACIÓN DE TEXTO ---

    # --- CORRECCIÓN AQUÍ ---
    await state.clear() # Usar .clear() en lugar de .finish()
    # --- Fin CORRECCIÓN ---


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
    bot_wallet_address = ton_api.WALLET # Obtenido de config.json a través de api.py

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


async def process_user_wallet_input(message: types.Message, state: FSMContext, pm_instance: payment_manager.PaymentManager): # Usar alias payment_manager
    """Procesa la dirección de wallet TON enviada por el usuario."""
    # --- VERIFICACIÓN DE ESTADO INTERNA (WORKAROUND) ---
    # Este handler debería ejecutarse solo en el estado awaiting_user_wallet_input
    current_state = await state.get_state()
    if current_state != BuyTicketStates.awaiting_user_wallet_input:
         logger.debug(f"Ignoring message from user {message.from_user.id} in state {current_state}. Expected {BuyTicketStates.awaiting_user_wallet_input}")
         # Opcional: enviar un mensaje de "inesperado"
         # await message.answer("No esperaba ese mensaje ahora. Intenta /comprar_boleto para iniciar una nueva compra.")
         return # Ignorar if not in correct state
    # --- FIN VERIFICACIÓN DE ESTADO ---

    # --- VERIFICACIÓN DE TEXTO INTERNA (WORKAROUND) ---
    # Este handler está registrado para capturar CUALQUIER texto no manejado por otros handlers.
    # Necesitamos verificar que el mensaje *sea* de texto para evitar errores si recibe fotos, etc.
    if not message.text:
         logger.debug(f"Ignoring non-text message from user {message.from_user.id} in state {current_state}.")
         # Opcional: responder "por favor, envía texto"
         return
    # --- FIN VERIFICACIÓN DE TEXTO ---


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
    # Asegúrate de usar la URL correcta para Testnet/Mainnet if different for wallets
    # api.WORK_MODE can be used to determine if it's testnet or mainnet
    
    # Build deep link URLs
    # It's good practice to URL encode the comment if it contains special characters, although for this simple format it's not critical.
    # from urllib.parse import quote_plus
    # encoded_comment = quote_plus(payment_comment_text)
    
    tonkeeper_url = f"https://app.tonkeeper.com/transfer/{bot_wallet_address}?amount={amount_to_pay_nano}&text={payment_comment_text}"
    # Tonhub Testnet URL: test.tonhub.com, Mainnet URL: tonhub.com
    tonhub_url = f"https://{'test.' if ton_api.WORK_MODE == 'testnet' else ''}tonhub.com/transfer/{bot_wallet_address}?amount={amount_to_pay_nano}&text={payment_comment_text}" # Use ton_api.WORK_MODE
    # Generic ton:// URL
    generic_ton_url = f"ton://transfer/{bot_wallet_address}?amount={amount_to_pay_nano}&text={payment_comment_text}"

    keyboard_payment_links.add(types.InlineKeyboardButton(text="🔷 Pagar con Tonkeeper", url=tonkeeper_url))
    keyboard_payment_links.add(types.InlineKeyboardButton(text="💎 Pagar con Tonhub", url=tonhub_url))
    keyboard_payment_links.add(types.InlineKeyboardButton(text="🚀 Pagar con otra wallet TON", url=generic_ton_url))

    # Button for the user to confirm payment
    keyboard_confirm_action = types.InlineKeyboardMarkup(row_width=1)
    # Include the unique comment in callback_data to identify verification
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
    
    # --- 7. Change to Verification Waiting State ---
    await BuyTicketStates.awaiting_payment_verification.set()


async def callback_verify_payment(callback_query: types.CallbackQuery, state: FSMContext, pm_instance: payment_manager.PaymentManager, bot_instance: Bot): # Use alias payment_manager
    """Handles the callback when user confirms they've paid and requests verification."""
    # --- INTERNAL STATE CHECK (WORKAROUND) ---
    # This handler should execute only in the awaiting_payment_verification state
    current_state = await state.get_state()
    if current_state != BuyTicketStates.awaiting_payment_verification:
         logger.debug(f"Ignoring verify payment callback from user {callback_query.from_user.id} in state {current_state}. Expected {BuyTicketStates.awaiting_payment_verification}")
         await callback_query.answer("Unexpected action. Your payment request might have expired. Try /buy_ticket again.")
         return
    # --- END STATE CHECK ---

    # Extract unique comment from callback_data
    # Callback_data is "verify_payment_<unique_comment>"
    callback_data_parts = callback_query.data.split('_', 2) # Split into 3 parts: 'verify', 'payment', '<unique_comment>'
    if len(callback_data_parts) != 3 or callback_data_parts[0] != 'verify' or callback_data_parts[1] != 'payment':
         logger.error(f"Unexpected callback data for payment verification: {callback_query.data}")
         await callback_query.answer("Internal error processing request.", show_alert=True)
         return # Exit if callback_data format is incorrect

    unique_comment_from_callback = callback_data_parts[2]

    # Respond immediately to callback to remove loading clock
    await callback_query.answer("Verifying your payment, this may take a few seconds...", show_alert=False)
    
    user_id_str = str(callback_query.from_user.id)
    user_fsm_data = await state.get_data()
    
    # Validate required FSM data is present
    required_fsm_keys = ['user_sending_wallet', 'amount_nano', 'bot_wallet_to_pay', 'lottery_round_id']
    if not all(key in user_fsm_data for key in required_fsm_keys):
        logger.error(f"Missing FSM data to verify payment for user {user_id_str}. Data: {user_fsm_data}")
        await bot_instance.send_message(callback_query.message.chat.id, "Internal error: Missing data to verify payment. Please try /buy_ticket again.")
        await state.clear() # Corrected from .finish()
        return

    user_sending_wallet = user_fsm_data['user_sending_wallet']
    expected_amount_nano = user_fsm_data['amount_nano']
    # expected_bot_wallet = user_fsm_data['bot_wallet_to_pay'] # Not needed to pass to find_transaction
    lottery_round_id_assoc = user_fsm_data['lottery_round_id'] # ID of the logical round

    # --- Call payment verification function ---
    # ton_api.find_transaction already handles interaction with db.check_transaction and db.add_ton_transaction
    # and associates the Telegram ID if passed.
    # Use ton_api.find_transaction
    is_verified = ton_api.find_transaction(
        user_wallet=user_sending_wallet, # The wallet from which the user paid (standardized)
        value_nano=str(expected_amount_nano), # Expected amount in nanoTONs (as a string for the API)
        comment=unique_comment_from_callback, # The unique comment we expect
        telegram_id=user_id_str # Pass the Telegram ID for DB association
    )

    # --- Process verification result ---
    if is_verified:
        # If verification was successful, the payment is already registered in ton_transactions.
        # Now, if your off-chain draw logic needs to register participants
        # in a separate table (e.g., round_participants) or associate the payment to a logical round
        # in a more formal way, do it here.
        
        # Example (if you keep the round_participants table for simulation logic):
        # try:
        #     # Assign participant number and register in round_participants table
        #     current_participants_count = src.db.count_participants_in_round(int(lottery_round_id_assoc)) # You need this function
        #     assigned_number = current_participants_count + 1 # Simple assignment logic
        #
        #     src.db.add_participant_to_round( # You need this function in db.py
        #         round_id=int(lottery_round_id_assoc),
        #         telegram_id=user_id_str,
        #         assigned_number=assigned_number # Or the corresponding number
        #     )
        #     # Notify the user with the assigned number (if applicable)
        #     await bot_instance.edit_message_text(...) # Message with assigned number
        #
        # except Exception as e:
        #     logger.error(f"Error registering participant in simulation round {lottery_round_id_assoc} for user {user_id_str}: {e}")
        #     # Notify the user about the problem in ticket registration
        #     await bot_instance.send_message(...)

        # General success message if you only register in ton_transactions
        await bot_instance.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=f"¡Pago confirmado! 🎉\nTu pago de <code>{expected_amount_nano / (10**9)}</code> TON para la ronda <b>{lottery_round_id_assoc}</b> ha sido verificado y registrado.\n"
                     f"¡Mucha suerte, {callback_query.from_user.first_name}!\n\n"
                     "Puedes ver tus pagos verificados con /mis_pagos_ton o iniciar otra compra con /comprar_boleto.",
            parse_mode=types.ParseMode.HTML,
            reply_markup=None # Remove inline buttons
        )
        
        await state.clear() # Corrected from .finish()
    else:
        # If find_transaction returned False
        keyboard_retry_cancel = types.InlineKeyboardMarkup(row_width=1)
        # The callback_data for retry must include the original unique comment
        keyboard_retry_cancel.add(types.InlineKeyboardButton(text="🔄 Reintentar Verificación", callback_data=f"verify_payment_{unique_comment_from_callback}"))
        keyboard_retry_cancel.add(types.InlineKeyboardButton(text="❌ Cancelar Compra", callback_data="payment_cancel"))
        
        # Try to edit the previous message if possible, otherwise send a new one
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
            # If editing fails (e.g., very old message), send a new message
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


async def callback_payment_cancel(callback_query: types.CallbackQuery, state: FSMContext, bot_instance: Bot): # Corrected type annotation
    """Handles canceling the payment process."""
    # --- INTERNAL STATE CHECK (WORKAROUND) ---
    # This handler can execute in any state to cancel
    # Cancellation logic already handles state.get_state() and state.finish()
    # We don't need an explicit check here, as it's a global cancellation handler
    logger.debug(f"Handling payment cancel callback from user {callback_query.from_user.id} in state {await state.get_state()}.")
    # --- END STATE CHECK ---

    await callback_query.answer("Purchase canceled.", show_alert=False)
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear() # Corrected from .finish()
    
    # Try to edit the previous message if possible, otherwise send a new one
    try:
        await bot_instance.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text="The ticket purchase has been canceled.",
            parse_mode=types.ParseMode.HTML,
            reply_markup=None # Remove inline buttons
        )
    except Exception: 
        await bot_instance.send_message(callback_query.message.chat.id, "The ticket purchase has been canceled.")
    
    # Optional: Send a final message to guide the user
    # await bot_instance.send_message(callback_query.message.chat.id, "You can start a new purchase with /buy_ticket or use /start.")


async def cmd_cancel(message: types.Message, state: FSMContext):
    """Handles the /cancel command to exit any FSM state."""
    # --- INTERNAL STATE CHECK (WORKAROUND) ---
    # This handler can execute in any state to cancel
    # Cancellation logic already handles state.get_state() and state.finish()
    # We don't need an explicit check here, as it's a global cancellation handler
    logger.debug(f"Handling /cancel command from user {message.from_user.id} in state {await state.get_state()}.")
    # --- END STATE CHECK ---

    current_state = await state.get_state()
    if current_state is None or current_state == 'BuyTicketStates:firstState': # If already in an initial state or no state
        await message.answer("No active action to cancel.")
        return

    logger.info(f"Cancelling state {current_state} for user {message.from_user.id}")
    await state.clear() # Corrected from .finish()
    await message.answer("Action canceled. You can use /start or /buy_ticket.")

async def cmd_my_paid_tickets(message: types.Message, state: FSMContext): # <-- Add state here for internal check
    """Shows the user's verified tickets/payments."""
    # --- INTERNAL STATE CHECK (WORKAROUND) ---
    # This handler should execute only in the default state (None)
    current_state = await state.get_state() # You need the state object here
    if current_state is not None:
         logger.debug(f"Ignoring /my_ton_payments command from user {message.from_user.id} in state {current_state}")
         await message.answer(f"You are already in the middle of an action ({current_state}). Use /cancel if you want to stop it.")
         return
    # --- END STATE CHECK ---

    # --- VERIFICACIÓN DE TEXTO INTERNA (WORKAROUND para botón) ---
    # This handler will be registered for the /my_ton_payments command AND for the button text.
    # We check if the message is the EXACT button text OR the command.
    expected_button_text = "📜 Mis Pagos TON (/mis_pagos_ton)"
    expected_command_text = "/mis_pagos_ton"

    if message.text and message.text != expected_button_text and message.text.lower() != expected_command_text:
         # If the text doesn't match the button or expected command, ignore
         logger.debug(f"Ignoring message text '{message.text}' from user {message.from_user.id} for cmd_my_paid_tickets.")
         return # Ignore messages that are not the button or /my_my_ton_payments command
    # --- END TEXT CHECK ---

    user_id_str = str(message.from_user.id)
    
    # Ensure user exists in DB
    src.db.get_or_create_user(str(message.from_user.id), message.from_user.username, message.from_user.first_name) # Call with prefix
    
    # Get verified TON payments history from ton_transactions table
    user_payments = src.db.get_user_ton_payments_history(user_id_str) # Call with prefix

    if not user_payments:
        await message.answer("No verified payments found associated with your Telegram account.\n"
                             "Ensure you have completed a ticket purchase and your payment was verified by the bot.")
        return

    response_text = "<b>History of your verified payments (TON Transactions):</b>\n\n"
    for payment in user_payments:
        # Ensure keys exist in the `payment` dictionary
        value_nano = payment.get('value_nano')
        comment = payment.get('comment')
        user_wallet_display = payment.get('user_ton_wallet', 'Unknown')
        tx_hash_display = payment.get('transaction_hash', 'Unknown')
        tx_time_display = payment.get('transaction_time', 'Unknown date')
        lottery_round_id_assoc = payment.get('lottery_round_id_assoc', 'N/A') # Get associated round if exists


        value_ton = value_nano / (10**9) if value_nano is not None else "N/A"
        comment_display = comment if comment else "No comment"

        # Show associated round if it exists, or the comment otherwise
        round_info_line = f"   Associated Round: {lottery_round_id_assoc}\n" if lottery_round_id_assoc != 'N/A' else f"   Original Comment: <code>{comment_display}</code>\n"


        tx_hash_short = tx_hash_display[:10] + '...' if tx_hash_display != 'Unknown' else 'Unknown'
        tx_time_short = tx_time_display[:10] if tx_time_display != 'Unknown date' else 'Unknown date'


        response_text += (f"🔹 Payment of <b>{value_ton} TON</b>\n"
                          f"{round_info_line}" # Use the round/comment info line
                          f"   From Wallet: <code>{user_wallet_display}</code>\n"
                          f"   TX Hash: <code>{tx_hash_short}</code>\n" 
                          f"   Verification Date: {tx_time_short}\n" 
                          f"\n")
    
    await message.answer(response_text, parse_mode=types.ParseMode.HTML)


# NOTE: cmd_my_paid_tickets now needs the `state` argument for the internal check.
# If registered with `dp.message.register(cmd_my_paid_tickets, ...)` without lambda,
# the dispatcher will NOT pass `state`. It must be registered with a lambda if it needs `state`.
# We will update the registration to pass `state`.


def register_all_handlers(dp: Dispatcher, bot_instance: Bot, pm_instance: payment_manager.PaymentManager): # Use alias payment_manager
    """Registers all handlers with the main dispatcher."""
    
    # db_instance is not passed to individual handlers because functions from db.py
    # called directly already manage their own connection.

    # Command and Text Handlers
    # --- V3 REGISTRATION SYNTAX (WITHOUT STATEFILTER OR TEXT FILTER - COMPLETE WORKAROUND) ---
    # State and text filters are handled INSIDE the handlers now.
    # We only use CommandStart and Command filters in register(), and lambda filters for text.

    # Register handlers for commands
    dp.message.register(cmd_start, CommandStart()) # Registers /start command
    dp.message.register(cmd_cancel, Command("cancelar")) # Registers /cancelar command
    # These handlers need lambda to pass `state` and `pm_instance`
    # --- CORRECCIÓN: Añadir await en las lambdas que llaman handlers async ---
    dp.message.register(lambda msg, state: await cmd_buy_ticket_start(msg, state, pm_instance), Command("comprar_boleto")) # Registers /comprar_boleto command
    dp.message.register(lambda msg, state: await cmd_my_paid_tickets(msg, state), Command("mis_pagos_ton")) # Registers /mis_pagos_ton command

    # Register handlers for button text (using lambda filters)
    # These handlers check text AND state internally.
    # We register the same handlers for the button text.
    dp.message.register(lambda msg, state: await cmd_buy_ticket_start(msg, state, pm_instance), lambda message: isinstance(message.text, str) and message.text == "🎟️ Comprar Boleto (/comprar_boleto)")
    dp.message.register(lambda msg, state: await cmd_my_paid_tickets(msg, state), lambda message: isinstance(message.text, str) and message.text == "📜 Mis Pagos TON (/mis_pagos_ton)")

    # Register a handler for ANY other text messages
    # This handler must check the state internally to know if it's expecting a wallet address.
    # It must be registered *after* all command and specific text button handlers.
    dp.message.register(lambda message, state: await process_user_wallet_input(message, state, pm_instance), lambda message: isinstance(message.text, str))
    # --- Fin CORRECCIÓN ---


    # Callback Handlers (inline buttons)
    # These handlers must verify the state INTERNALLY
    dp.callback_query.register(
        lambda cb_query, state: await callback_verify_payment(cb_query, state, pm_instance, bot_instance), # <-- Add await here too
        lambda c: c.data and c.data.startswith('verify_payment_') # Callback data filter (positional)
    )

    dp.callback_query.register(
        lambda cb_query, state: await callback_payment_cancel(cb_query, state, bot_instance), # <-- Add await here too
        lambda c: c.data == 'payment_cancel' # Callback data filter (posicional)
    )


    logger.info("Handlers from src.handlers (Aiogram v3 - COMPLETE WORKAROUND) registered.")

    # NOTE: The logic for registering the /open_rounds handler (if round_manager is available)
    # was in bot.py. It could be moved here or kept in bot.py by registering directly with the dispatcher.
    # Since the availability of round_manager is checked in bot.py, it's easier to register it there.
    # Ensure that the registration logic in bot.py also uses dp.message.register.