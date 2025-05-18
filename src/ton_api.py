# botloteria/src/ton_api.py

import requests
import json
import logging
import os
# Importamos nuestro módulo db para interactuar con la base de datos local
# Asegúrate de que db.py esté en la misma carpeta src y contenga las funciones necesarias
from src import db # Importación absoluta corregida

logger = logging.getLogger(__name__)

# --- Configuración de la API y Wallet ---

# Rutas base para las APIs de TON Center
MAINNET_API_BASE = "https://toncenter.com/api/v2/"
TESTNET_API_BASE = "https://testnet.toncenter.com/api/v2/"

# Cargar configuración desde config.json
# Asegúrate de que config.json está en la raíz de tu proyecto botloteria
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
try:
    with open(config_path, 'r') as f:
        config_json = json.load(f)
        BOT_TOKEN = config_json.get('BOT_TOKEN', 'YOUR_BOT_TOKEN') # No usado directamente aquí, pero buena práctica cargarlo
        MAINNET_API_TOKEN = config_json.get('MAINNET_API_TOKEN', 'YOUR_MAINNET_API_TOKEN')
        TESTNET_API_TOKEN = config_json.get('TESTNET_API_TOKEN', 'YOUR_TESTNET_API_TOKEN')
        MAINNET_WALLET = config_json.get('MAINNET_WALLET', 'YOUR_MAINNET_WALLET')
        TESTNET_WALLET = config_json.get('TESTNET_WALLET', 'YOUR_TESTNET_WALLET')
        WORK_MODE = config_json.get('WORK_MODE', 'testnet') # 'testnet' o 'mainnet'

except FileNotFoundError:
    logger.error(f"Error: No se encontró el archivo de configuración en {config_path}")
    # Usar valores por defecto o lanzar una excepción si la configuración es crítica
    MAINNET_API_TOKEN = 'YOUR_MAINNET_API_TOKEN'
    TESTNET_API_TOKEN = 'YOUR_TESTNET_API_TOKEN'
    MAINNET_WALLET = 'YOUR_MAINNET_WALLET'
    TESTNET_WALLET = 'YOUR_TESTNET_WALLET'
    WORK_MODE = 'testnet'
except json.JSONDecodeError:
    logger.error(f"Error: Error al parsear el archivo config.json en {config_path}. Asegúrate de que sea JSON válido.")
    # Usar valores por defecto o lanzar una excepción
    MAINNET_API_TOKEN = 'YOUR_MAINNET_API_TOKEN'
    TESTNET_API_TOKEN = 'YOUR_TESTNET_API_TOKEN'
    MAINNET_WALLET = 'YOUR_MAINNET_WALLET'
    TESTNET_WALLET = 'YOUR_TESTNET_WALLET'
    WORK_MODE = 'testnet'


# Seleccionar la base URL, token y wallet según el modo de trabajo
if WORK_MODE == "mainnet":
    API_BASE = MAINNET_API_BASE
    API_TOKEN = MAINNET_API_TOKEN
    WALLET = MAINNET_WALLET
    logger.info("Modo de trabajo: mainnet")
else:
    API_BASE = TESTNET_API_BASE
    API_TOKEN = TESTNET_API_TOKEN
    WALLET = TESTNET_WALLET
    logger.info("Modo de trabajo: testnet")

logger.info(f"Usando API Token: {API_TOKEN[:5]}...{API_TOKEN[-5:]}")
logger.info(f"Wallet de recepción del bot: {WALLET}")


# --- Funciones de Interacción con la API de TON Center ---

def detect_address(address: str) -> str | bool:
    """
    Valida una dirección de TON y retorna su formato b64url bounceable si es válida.
    Retorna False si la dirección es inválida o hay un error.
    """
    url = f"{API_BASE}detectAddress?address={address}&api_key={API_TOKEN}"
    try:
        logger.debug(f"Llamando a detectAddress para '{address}'")
        r = requests.get(url)
        r.raise_for_status() # Lanza una excepción para códigos de estado de error (4xx o 5xx)
        response = json.loads(r.text)

        if response.get('ok', False) and response.get('result'):
            # Retorna la dirección en formato b64url bounceable
            return response['result'].get('bounceable', {}).get('b64url', False)
        else:
            logger.warning(f"detectAddress para '{address}' retornó no OK o sin resultado: {response}")
            return False # No es una dirección válida o la API no la detectó

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de red en detect_address para '{address}': {e}")
        return False # Error de conexión o HTTP
    except json.JSONDecodeError:
        logger.error(f"Error al decodificar JSON en detect_address para '{address}'.")
        return False # Respuesta no es JSON válido
    except Exception as e:
        logger.error(f"Error inesperado en detect_address para '{address}': {e}")
        return False


def get_address_transactions(address: str = WALLET, limit: int = 30) -> list | None:
    """
    Obtiene las últimas transacciones entrantes para una dirección de wallet.
    Por defecto, usa la wallet de recepción del bot y un límite de 30 transacciones.
    Retorna una lista de transacciones o None si hay un error.
    """
    # Nota: archival=true asegura que se busquen en el historial completo,
    # pero puede ser más lento. Para monitoreo en tiempo real, a veces se omite
    # o se usan otros métodos (websockets, etc.).
    url = f"{API_BASE}getTransactions?address={address}&limit={limit}&archival=true&api_key={API_TOKEN}"
    try:
        logger.debug(f"Llamando a getTransactions para '{address}' con limit={limit}")
        r = requests.get(url)
        r.raise_for_status() # Lanza una excepción para códigos de estado de error
        response = json.loads(r.text)

        if response.get('ok', False) and response.get('result') is not None:
             # Filtrar solo mensajes entrantes si es necesario, aunque getTransactions
             # suele devolver tanto in_msg como out_msgs dentro de la transacción.
             # La lógica de find_transaction ya filtra por 'in_msg'.
            return response['result']
        else:
            logger.warning(f"getTransactions para '{address}' retornó no OK o sin resultado: {response}")
            return [] # Retorna lista vacía si no hay resultado o no OK

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de red en get_address_transactions para '{address}': {e}")
        return None # Error de conexión o HTTP
    except json.JSONDecodeError:
        logger.error(f"Error al decodificar JSON en get_address_transactions para '{address}'.")
        return None # Respuesta no es JSON válido
    except Exception as e:
        logger.error(f"Error inesperado en get_address_transactions para '{address}': {e}")
        return None


def find_transaction(user_wallet: str, value_nano: str, comment: str, telegram_id: str | None = None) -> bool:
    """
    Busca una transacción entrante específica (por origen, valor y comentario)
    en las últimas transacciones de la wallet del bot.
    Verifica si la transacción ya fue procesada usando db.check_transaction.
    Si la encuentra y no ha sido procesada, la registra en db.add_ton_transaction
    y retorna True. Retorna False si no la encuentra o ya fue procesada.
    """
    # Obtener las últimas transacciones para la wallet del bot
    transactions = get_address_transactions(WALLET)

    if transactions is None:
        logger.error("find_transaction no pudo obtener transacciones de la API.")
        return False # No se pudieron obtener transacciones

    # Iterar sobre las transacciones encontradas
    for transaction in transactions:
        # Asegurarse de que es un mensaje entrante y tiene los campos necesarios
        if 'in_msg' in transaction and transaction['in_msg'] and \
           'source' in transaction['in_msg'] and 'value' in transaction['in_msg'] and 'message' in transaction['in_msg'] and \
           'body_hash' in transaction['in_msg']:

            msg = transaction['in_msg']

            # Comparar los datos de la transacción con los esperados
            # Convertimos value_nano a string para la comparación si es necesario,
            # ya que el JSON de la API lo retorna como string.
            if msg['source'] == user_wallet and msg['value'] == str(value_nano) and msg['message'] == comment:

                # Si los datos coinciden, verificar si esta transacción ya fue verificada en la DB
                tx_hash = msg['body_hash']
                if not db.check_transaction(tx_hash):
                    # Si no ha sido verificada, registrarla en la DB usando add_ton_transaction
                    try:
                        # add_ton_transaction necesita telegram_id y bot_ton_wallet.
                        # bot_ton_wallet es la wallet del bot (WALLET).
                        # telegram_id debería obtenerse en el handler o pasarse aquí.
                        # Si no se pasa, intentamos obtenerlo de la DB por la wallet de origen,
                        # o lo guardamos como NULL temporalmente.
                        
                        # Intentamos obtener el telegram_id asociado a esta wallet de origen
                        # Esto requiere que el usuario haya registrado su wallet previamente
                        # (ej. al iniciar el bot o al intentar unirse/pagar por primera vez)
                        # Si el handler no pasa el telegram_id, lo buscamos.
                        assoc_telegram_id = telegram_id
                        # Necesitas implementar get_user_telegram_id_by_ton_wallet en db.py si quieres buscar por wallet
                        # if assoc_telegram_id is None:
                        #      assoc_telegram_id = db.get_user_telegram_id_by_ton_wallet(user_wallet)

                        added_successfully = db.add_ton_transaction(
                            telegram_id=assoc_telegram_id, # Usar el ID asociado o None
                            user_ton_wallet=msg['source'],
                            bot_ton_wallet=WALLET, # La wallet del bot
                            transaction_hash=tx_hash,
                            value_nano=int(msg['value']), # Guardar valor como INT en DB
                            comment=msg['message'],
                            lottery_round_id_assoc=None # Puedes asociar a una ronda lógica si la tienes
                        )

                        if added_successfully is not None: # add_ton_transaction retorna ID o None
                            logger.info(f"find_transaction: Transacción encontrada y verificada.")
                            logger.info(f"  Origen: {msg['source']}")
                            logger.info(f"  Valor: {msg['value']} nanoTON")
                            logger.info(f"  Comentario: '{msg['message']}'")
                            logger.info(f"  Hash: {tx_hash}")
                            return True # Transacción encontrada y verificada exitosamente
                        else:
                            # Falló add_ton_transaction (ej. error de DB, aunque check_transaction dijo que no existía)
                            logger.error(f"find_transaction: Falló el registro de la transacción {tx_hash} en DB.")
                            return False # Error al registrar

                    except Exception as e:
                        logger.error(f"Error inesperado al registrar transacción verificada en DB: {e}", exc_info=True)
                        return False # Error al registrar
                else:
                    # La transacción fue encontrada pero ya estaba verificada
                    logger.info(f"find_transaction: Transacción encontrada pero ya verificada (Hash: {tx_hash[:10]}...).")
                    # Continuar buscando, por si el usuario envió la misma cantidad/comentario varias veces
                    # (aunque con hash único, esto solo ocurriría si el hash no se registró correctamente antes)
                    pass # No retornamos False aquí, seguimos buscando

    # Si terminamos de iterar y no encontramos la transacción no verificada
    logger.info("find_transaction: No se encontró la transacción requerida en las últimas transacciones o ya estaba verificada.")
    return False


# --- Sección para pruebas directas del script ---
# Puedes ejecutar este archivo directamente para probar las funciones de API
# python3 src/ton_api.py
if __name__ == '__main__':
    # Configuración básica de logging si se ejecuta directamente
    logging.basicConfig(
        level=logging.DEBUG, # Nivel DEBUG para ver todos los detalles en pruebas
        format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    )
    # Re-obtener loggers después de reconfigurar
    logger = logging.getLogger(__name__)
    logging.getLogger('db').setLevel(logging.DEBUG) # Mostrar logs de db también
    logging.getLogger('api').setLevel(logging.DEBUG) # Mostrar logs de api también
    logging.getLogger('aioschedule').setLevel(logging.INFO) # Nivel para aioschedule

    print("Ejecutando pruebas directas de ton_api.py...")

    # Asegúrate de que tu db.py esté inicializado para que check_transaction y add_ton_transaction funcionen
    try:
        db.init_db() # Llama a la función init_db en tu db.py
        logger.info("Base de datos inicializada para pruebas.")
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos para pruebas: {e}", exc_info=True)
        # Si la DB no inicializa, las pruebas de find_transaction fallarán en la parte de DB.


    # --- Pruebas de detect_address ---
    print("\n--- Pruebas de detect_address ---")
    # Asegurarse de que WALLET se cargó correctamente de config.json
    if WALLET == 'YOUR_MAINNET_WALLET' or WALLET == 'YOUR_TESTNET_WALLET':
         logger.warning("La wallet de recepción no está configurada en config.json. Saltando pruebas de detect_address y getTransactions.")
         test_address_valid = None # Saltar pruebas si no hay wallet configurada
    else:
        test_address_valid = WALLET # Usamos la wallet del bot como dirección válida de prueba
        test_address_invalid = "esto_no_es_una_wallet_valida"

        result_valid = detect_address(test_address_valid)
        if result_valid:
            logger.info(f"detect_address para '{test_address_valid}': OK -> {result_valid}")
        else:
            logger.info(f"detect_address para '{test_address_valid}': Falló o es inválida.")

        result_invalid = detect_address(test_address_invalid)
        if not result_invalid:
            logger.info(f"detect_address para '{test_no_es_una_wallet_valida}': OK -> Retornó None/False como esperado.")
        else:
            logger.error(f"detect_address para '{test_no_es_una_wallet_valida}': Falló. Retornó {result_invalid}")


    # --- Prueba de getTransactions ---
    if test_address_valid: # Solo si la wallet está configurada
        print("\n--- Prueba de getTransactions ---")
        transactions_list = get_address_transactions(WALLET, limit=5) # Obtener solo 5 para no saturar el log

        if transactions_list is not None:
            logger.info(f"Se obtuvieron {len(transactions_list)} transacciones.")
            # Imprimir detalles básicos de las primeras transacciones encontradas
            for i, tx in enumerate(transactions_list[:5]): # Limitar la impresión a 5
                if 'in_msg' in tx and tx['in_msg']:
                     msg = tx['in_msg']
                     tx_id = tx.get('transaction_id', {}).get('hash', 'N/A')
                     logger.info(f"  TX {i+1}: Hash: {tx_id[:10]}..., Origen: {msg.get('source', 'N/A')}, Valor: {msg.get('value', 'N/A')} nano, Msg: '{msg.get('message', 'N/A')}'")
                else:
                     # Puede haber transacciones salientes o con formato diferente
                     logger.info(f"  TX {i+1}: Formato inesperado o mensaje saliente.")

        else:
            logger.error("get_address_transactions retornó None (error).")


    # --- Prueba de find_transaction ---
    print("\n--- Prueba de find_transaction ---")
    # *** IMPORTANTE ***
    # Reemplaza 'DIRECCION_ORIGEN_FAUCET', VALOR_NANO_FAUCET, 'COMENTARIO_FAUCET'
    # con los datos EXACTOS de la transacción del faucet que viste en la salida anterior.
    # El valor debe ser un STRING en nanoTONs.
    # Si no enviaste una transacción con un comentario específico, puedes usar '' para comentario vacío.
    source_to_find = 'EQCSES0TZYqcVkgoguhIb8iMEo4cvaEwmIrU5qbQgnN8fmvP' # <-- REEMPLAZA CON EL ORIGEN REAL DE TU TX DE FAUCET
    value_to_find_nano = '2000000000' # <-- REEMPLAZA CON EL VALOR REAL EN STRING NANO DE TU TX DE FAUCET
    comment_to_find = 'https://t.me/testgiver_ton_bot' # <-- REEMPLAZA CON EL COMENTARIO REAL DE TU TX DE FAUCET (o '')

    print(f"Buscando transacción con Origen: {source_to_find}, Valor: {value_to_find_nano}, Comentario: '{comment_to_find}'")

    # Para esta prueba, podemos simular que el usuario que envió la transacción es el telegram_id "test_user_faucet".
    # En un flujo real del bot, este telegram_id se obtendría del usuario que hizo clic en el botón "Verificar Pago".
    test_telegram_id_assoc = "test_user_faucet"
    
    # Asegurarnos de que el usuario de prueba exista en la DB para que la asociación funcione
    try:
        db.get_or_create_user(test_telegram_id_assoc, "FaucetUser", "Faucet")
        db.update_user_ton_wallet(test_telegram_id_assoc, source_to_find) # Asociar la wallet de origen al usuario de prueba
        logger.info(f"Usuario de prueba '{test_telegram_id_assoc}' con wallet '{source_to_find}' asegurado en DB para pruebas.")
    except Exception as e:
        logger.error(f"Error asegurando usuario de prueba en DB: {e}", exc_info=True)


    # Primera búsqueda: debería encontrarla y verificarla (si no está ya en DB)
    # Pasamos el telegram_id asociado a find_transaction
    transaction_found_1 = find_transaction(source_to_find, value_to_find_nano, comment_to_find, telegram_id=test_telegram_id_assoc)

    if transaction_found_1:
        print(f"Primera búsqueda: find_transaction encontró y verificó la transacción.")
    else:
        print(f"Primera búsqueda: find_transaction NO encontró la transacción o ya estaba verificada.")

    # Segunda búsqueda: debería encontrarla pero reportar que ya está verificada (si la primera la registró)
    print("\nRealizando segunda búsqueda (debería estar verificada)...")
    # No necesitamos pasar el telegram_id en la segunda búsqueda si add_ton_transaction ya lo registró
    transaction_found_2 = find_transaction(source_to_find, value_to_find_nano, comment_to_find)

    if transaction_found_2:
        print(f"Segunda búsqueda: find_transaction encontró y verificó la transacción (inesperado si la primera funcionó).")
    else:
        print(f"Segunda búsqueda: find_transaction NO encontró la transacción o ya estaba verificada (esperado).")


    print("\nPruebas directas de ton_api.py finalizadas.")

