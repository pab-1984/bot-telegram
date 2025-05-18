# botloteria/src/payment_manager.py

import requests
import json
import logging
import os
# Importamos los módulos ton_api y db
# Asegúrate de que ton_api.py y db.py estén en la misma carpeta src
from src import ton_api # Importación absoluta corregida a ton_api
from src import db # Importación absoluta corregida

logger = logging.getLogger(__name__)

# Carga de la configuración de la wallet del bot
# Esta configuración ya se carga en ton_api.py, podemos acceder a ella directamente desde ton_api.
# Mantenemos la carga aquí para asegurar que WALLET_CONFIG tenga un valor si este módulo
# se usa de forma independiente, pero la lógica principal usará ton_api.WALLET
WALLET_CONFIG = None
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, '..', 'config.json')

    with open(config_path, 'r') as f:
        config_json = json.load(f)
        WORK_MODE = config_json.get('WORK_MODE', 'testnet')
        if WORK_MODE == "mainnet":
            WALLET_CONFIG = {"PAYMENT_WALLET": config_json.get('MAINNET_WALLET'), "MODE": "mainnet"}
        else: # testnet por defecto
            WALLET_CONFIG = {"PAYMENT_WALLET": config_json.get('TESTNET_WALLET'), "MODE": "testnet"}

except FileNotFoundError:
    logger.error(f"Error en payment_manager.py: No se encontró config.json en la ruta esperada: {config_path}")
    # El bot no funcionará sin la wallet de recepción
except KeyError as e:
    logger.error(f"ERROR en payment_manager.py: Falta la clave {e} en config.json.")


class PaymentManager:
    # La instancia de DB no es estrictamente necesaria aquí si las funciones de db.py
    # gestionan su propia conexión, pero la mantenemos si otras partes de PaymentManager
    # la necesitan o si prefieres este patrón. La lógica de verificación de pagos
    # llamará a las funciones de módulo de db.py.
    def __init__(self):
        # La wallet de recepción se obtiene de ton_api.py que ya la carga de config.json
        self.bot_receiving_wallet = ton_api.WALLET
        if not self.bot_receiving_wallet or self.bot_receiving_wallet.startswith('YOUR_'):
             raise ValueError("La wallet de recepción de pagos del bot no está configurada correctamente en config.json.")
        logger.info(f"PaymentManager inicializado con wallet de recepción: {self.bot_receiving_wallet}")


    def get_payment_details(self, user_id: int, ticket_price_nano: int, lottery_round_id: str) -> dict | None:
        """
        Genera los detalles para que el usuario realice el pago.
        Devuelve un diccionario con bot_wallet, amount_nano, y comment.
        """
        # La wallet de recepción ya está disponible en self.bot_receiving_wallet
        # La lógica de generación de comentario único se mantiene aquí.

        # Crear un comentario único y relativamente corto.
        user_id_str = str(user_id)
        timestamp_nano = int(datetime.now().timestamp()) # Timestamp en segundos (entero)
        # Ejemplo: "L<round_id>U<user_id>T<timestamp>"
        payment_comment = f"L{lottery_round_id}U{user_id_str}T{timestamp_nano}"
        # Asegúrate de que este formato de comentario sea compatible con el tamaño máximo permitido por TON (aprox 100 bytes)

        return {
            "bot_wallet": self.bot_receiving_wallet,
            "amount_nano": str(ticket_price_nano), # La API TON y los deep links esperan strings
            "comment": payment_comment
        }

    def verify_payment(self, user_telegram_id: int, user_sending_wallet_address_raw: str, expected_amount_nano: str, expected_comment: str) -> bool:
        """
        Verifica si un pago fue realizado y registrado usando ton_api.find_transaction.
        user_telegram_id: El ID de Telegram del usuario que solicita la verificación.
        user_sending_wallet_address_raw: La dirección de wallet que el usuario dice haber usado.
        expected_amount_nano: El precio del boleto en nanoTONs (como string).
        expected_comment: El comentario único para la transacción.
        """
        # Validar y estandarizar la dirección de la wallet del usuario que envía
        user_sending_wallet_standardized = ton_api.detect_address(user_sending_wallet_address_raw)
        if not user_sending_wallet_standardized:
            logger.warning(f"verify_payment: Formato de wallet de envío inválido proporcionado por user {user_telegram_id}: {user_sending_wallet_address_raw}")
            return False

        # Asegurar que el usuario de Telegram existe y registrar/actualizar su wallet TON
        # Esto es importante para asociar la transacción encontrada al usuario correcto en la DB.
        # Asumimos que el nombre de usuario y primer nombre se obtienen en el handler antes de llamar a verify_payment
        # y que get_or_create_user ya se llamó.
        # Aquí solo actualizamos la wallet si es necesario.
        db.update_user_ton_wallet(str(user_telegram_id), user_sending_wallet_standardized)


        # Llamar a ton_api.find_transaction para buscar y verificar la transacción.
        # ton_api.find_transaction ya maneja la interacción con db.check_transaction
        # y db.add_ton_transaction. Le pasamos el telegram_id para que pueda
        # asociar la transacción al usuario si la encuentra y la registra.
        transaction_found_and_verified = ton_api.find_transaction(
            user_wallet=user_sending_wallet_standardized, # La wallet desde donde el usuario pagó (estandarizada)
            value_nano=str(expected_amount_nano), # Monto esperado en nanoTONs (como string)
            comment=expected_comment, # El comentario único que esperamos
            telegram_id=str(user_telegram_id) # Pasamos el Telegram ID para la asociación en DB
        )

        if transaction_found_and_verified:
            logger.info(f"Pago verificado para usuario {user_telegram_id} desde {user_sending_wallet_standardized} con comentario '{expected_comment}'.")
            # La asociación de la wallet y el registro de la transacción ya se hicieron en ton_api.find_transaction
            return True
        else:
            logger.info(f"Pago NO verificado para usuario {user_telegram_id}. Detalles esperados: "
                        f"desde='{user_sending_wallet_standardized}', monto='{expected_amount_nano}', comentario='{expected_comment}'.")
            return False

    def get_standardized_wallet_address(self, address_to_check: str) -> str | None:
        """
        Usa ton_api.detect_address para obtener la versión estandarizada (bounceable b64url) de una dirección de wallet.
        """
        return ton_api.detect_address(address_to_check)

# --- No necesitamos una sección if __name__ == '__main__': aquí ---
# porque este módulo es una librería que será importada por bot.py y handlers.py.
# Las pruebas directas de la API se hacen en ton_api.py.
