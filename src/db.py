# botloteria/src/db.py

import sqlite3
import logging
import hashlib
import os
from datetime import datetime, timezone # Aseguramos timezone para consistencia

logger = logging.getLogger(__name__)

# DATABASE_NAME será idealmente cargado desde config.json en bot.py y pasado aquí,
# o podemos definir un default y permitir que bot.py lo configure.
# Por ahora, lo definimos aquí, pero bot.py se asegurará de usar este nombre.
DATABASE_NAME = 'bot_lotto_data.db' # Asegúrate que coincida con tu config.json

def get_db_connection(db_name: str = DATABASE_NAME):
    """Establece y devuelve una conexión a la base de datos SQLite."""
    # check_same_thread=False es importante para Aiogram si se usa SQLite en un entorno async
    conn = sqlite3.connect(db_name, check_same_thread=False)
    conn.row_factory = sqlite3.Row # Para acceder a las columnas por nombre
    return conn

def generate_simulated_smart_contract_address(round_id: int) -> str:
    """Genera una dirección simulada para el Smart Contract."""
    data_to_hash = f"sim_contract_round_{round_id}-{datetime.now().timestamp()}"
    simulated_hash = hashlib.sha256(data_to_hash.encode()).hexdigest()
    return f"EQsim_{simulated_hash[:16]}" # Un poco más largo y distintivo

def _add_column_if_not_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str, column_type: str):
    """Función de utilidad para añadir una columna si no existe."""
    try:
        cursor.execute(f"SELECT {column_name} FROM {table_name} LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            logger.info(f"Columna '{column_name}' añadida a la tabla '{table_name}'.")
        except sqlite3.OperationalError as e_alter: # Podría fallar si la tabla está bloqueada o por otra razón
            logger.error(f"Error al intentar añadir columna '{column_name}' a '{table_name}': {e_alter}")


def init_db(db_name: str = DATABASE_NAME):
    """Inicializa la base de datos: crea tablas y añade columnas si faltan."""
    conn = None
    try:
        conn = get_db_connection(db_name)
        cursor = conn.cursor()

        # Tabla 'users': Mantiene telegram_id, username, y ahora ton_wallet
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT, 
                ton_wallet VARCHAR(68) DEFAULT NULL
            )
        ''')
        # Migraciones para 'users'
        _add_column_if_not_exists(cursor, "users", "first_name", "TEXT")
        _add_column_if_not_exists(cursor, "users", "ton_wallet", "VARCHAR(68) DEFAULT NULL")


        # Tabla 'rounds': Mantiene información sobre las rondas de lotería (simuladas)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL, -- Guardar como ISO8601 UTC
                end_time TEXT,           -- Guardar como ISO8601 UTC
                status TEXT NOT NULL,    -- e.g., waiting_to_start, waiting_for_payments, drawing, finished, cancelled
                round_type TEXT NOT NULL DEFAULT 'scheduled', -- e.g., scheduled, user_created
                creator_telegram_id TEXT,
                deleted BOOLEAN DEFAULT 0,
                simulated_contract_address TEXT,
                ticket_price_simulated REAL DEFAULT 1.0, -- Precio del boleto para esta ronda simulada
                FOREIGN KEY (creator_telegram_id) REFERENCES users(telegram_id)
            )
        ''')
        # Migraciones para 'rounds'
        cols_rounds = {
            "round_type": "TEXT NOT NULL DEFAULT 'scheduled'", "creator_telegram_id": "TEXT",
            "deleted": "BOOLEAN DEFAULT 0", "simulated_contract_address": "TEXT",
            "ticket_price_simulated": "REAL DEFAULT 1.0"
        }
        for col, col_type in cols_rounds.items():
            _add_column_if_not_exists(cursor, "rounds", col, col_type)
        # Asegurar que start_time y end_time sean TEXT
        # (SQLite es flexible, pero es bueno ser explícito si se cambia de DATETIME a TEXT)


        # Tabla 'round_participants': Quién participa en qué ronda simulada
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS round_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                telegram_id TEXT NOT NULL,
                assigned_number INTEGER,
                paid_real BOOLEAN DEFAULT 0, -- Para el flujo de simulación, esto significa que se unió
                purchase_time TEXT,       -- Hora de "compra" del boleto simulado (ISO8601 UTC)
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
                UNIQUE(round_id, telegram_id)
            )
        ''')
        _add_column_if_not_exists(cursor, "round_participants", "purchase_time", "TEXT")
        # Columna 'paid_simulated' se puede eliminar si ya no se usa, 'paid_real' toma su lugar en el contexto de simulación.


        # Tabla 'draw_results': Resultados de los sorteos simulados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS draw_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                drawn_number INTEGER NOT NULL,
                draw_order INTEGER NOT NULL, -- Para múltiples ganadores en un mismo sorteo
                winner_telegram_id TEXT,
                prize_amount_simulated TEXT, -- "100.00 unidades"
                prize_amount_real REAL,      -- 100.00
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (winner_telegram_id) REFERENCES users(telegram_id),
                UNIQUE(round_id, draw_order)
            )
        ''')

        # Tabla 'creator_commission': Comisiones simuladas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS creator_commission (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                creator_type TEXT NOT NULL, -- 'bot', 'user', 'gas_fee'
                creator_telegram_id TEXT,   -- NULL para bot o gas_fee
                amount_simulated TEXT,
                amount_real REAL,
                transaction_id TEXT,        -- Placeholder para futuro, podría ser un hash interno
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (creator_telegram_id) REFERENCES users(telegram_id),
                UNIQUE(round_id, creator_type, creator_telegram_id) -- Asegurar unicidad
            )
        ''')
        # Migraciones para 'creator_commission'
        # (la estructura UNIQUE cambió, puede ser complejo migrar sin borrar/recrear si hay datos)


        # --- NUEVAS TABLAS PARA PAGOS TON REALES ---
        # Tabla 'ton_transactions': Transacciones TON verificadas para compra de boletos
        # Esta es la tabla principal para el enfoque off-chain del Storefront bot
        cursor.execute('''CREATE TABLE IF NOT EXISTS ton_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT,          -- Quién hizo el pago (Telegram ID) - Puede ser NULL si no se asocia inmediatamente
            user_ton_wallet VARCHAR (68) NOT NULL, -- Wallet TON del usuario desde donde pagó
            bot_ton_wallet VARCHAR (68) NOT NULL,  -- Wallet TON del bot que recibió el pago
            transaction_hash VARCHAR (64) UNIQUE NOT NULL, -- Hash del mensaje/body_hash de la transacción TON
            value_nano INTEGER NOT NULL,        -- Monto en nanoTONs
            comment VARCHAR (100),              -- Comentario de la transacción TON (importante para asociar pago)
            transaction_time TEXT NOT NULL,     -- Hora de la verificación en el bot (ISO8601 UTC)
            lottery_round_id_assoc INTEGER,     -- A qué ronda de lotería (tabla 'rounds') se asocia este pago TON
                                                -- Puede ser NULL si el pago no se pudo asociar o es para otra cosa.
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            -- FOREIGN KEY (lottery_round_id_assoc) REFERENCES rounds(id) -- Deshabilitamos FK aquí si rounds puede ser eliminada lógicamente
        )''')
        _add_column_if_not_exists(cursor, "ton_transactions", "lottery_round_id_assoc", "INTEGER")
        # Aseguramos que telegram_id pueda ser NULL temporalmente si la asociación no es inmediata
        # (Esto puede requerir una migración ALTER TABLE si la columna ya existía como NOT NULL)
        try:
             cursor.execute("INSERT INTO ton_transactions (telegram_id, user_ton_wallet, bot_ton_wallet, transaction_hash, value_nano, transaction_time) VALUES (NULL, 'temp', 'temp', 'temp_hash', 0, 'temp_time')")
             cursor.execute("DELETE FROM ton_transactions WHERE transaction_hash = 'temp_hash'")
             conn.commit()
             logger.info("Columna 'telegram_id' en 'ton_transactions' permite NULL.")
        except sqlite3.IntegrityError: # Si falla porque hash es UNIQUE y 'temp_hash' ya existe
             logger.debug("La tabla ton_transactions ya existe y tiene datos. No se verifica si telegram_id permite NULL con inserción temporal.")
        except sqlite3.OperationalError as e_op: # Si falla porque telegram_id es NOT NULL
             logger.warning(f"Columna 'telegram_id' en 'ton_transactions' es NOT NULL. Considera ALTER TABLE para permitir NULL si la asociación no es inmediata. Error: {e_op}")


        logger.info(f"Base de datos '{db_name}' inicializada y tablas verificadas/actualizadas.")

    except sqlite3.Error as e:
        logger.error(f"Error al inicializar/actualizar la base de datos '{db_name}': {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Funciones de Usuario (Generales y TON) ---
def get_or_create_user(telegram_id: str, username: str | None, first_name: str | None) -> None:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, username, first_name FROM users WHERE telegram_id = ?", (telegram_id,))
        user_row = cursor.fetchone()
        
        db_username = username if username is not None else ""
        db_first_name = first_name if first_name is not None else ""

        if user_row is None:
            cursor.execute("INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
                           (telegram_id, db_username, db_first_name))
            conn.commit()
            logger.info(f"Usuario creado: ID {telegram_id}, @{db_username}, Nombre: {db_first_name}")
        else:
            # Actualizar username o first_name si han cambiado o eran nulos y ahora tienen valor
            needs_update = False
            update_query = "UPDATE users SET "
            params = []
            if db_username and user_row["username"] != db_username:
                update_query += "username = ?, "
                params.append(db_username)
                needs_update = True
            if db_first_name and user_row["first_name"] != db_first_name:
                update_query += "first_name = ?, "
                params.append(db_first_name)
                needs_update = True
            
            if needs_update:
                update_query = update_query.strip(", ") + " WHERE telegram_id = ?"
                params.append(telegram_id)
                cursor.execute(update_query, tuple(params))
                conn.commit()
                logger.info(f"Datos de usuario actualizados para ID {telegram_id}")
                
    except sqlite3.Error as e:
        logger.error(f"Error al obtener o crear usuario {telegram_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def update_user_ton_wallet(telegram_id: str, ton_wallet_address: str | None):
    """Asocia o actualiza la wallet TON de un usuario."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Asegurar que el usuario exista (get_or_create_user debería haberse llamado antes)
        cursor.execute("UPDATE users SET ton_wallet = ? WHERE telegram_id = ?", (ton_wallet_address, telegram_id))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Wallet TON para usuario {telegram_id} actualizada a: {ton_wallet_address}")
        else:
            # Podría ser que el usuario no exista, o la wallet ya era la misma.
            # get_or_create_user debe llamarse en el flujo del bot antes de esto.
            logger.warning(f"No se actualizó wallet TON para {telegram_id} (¿usuario no existe o wallet sin cambios?). Intentando asegurar usuario y reintentar.")
            # Este reintento es una salvaguarda; idealmente, get_or_create_user ya se ejecutó.
            cursor.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (telegram_id,))
            cursor.execute("UPDATE users SET ton_wallet = ? WHERE telegram_id = ?", (ton_wallet_address, telegram_id))
            conn.commit()
            if cursor.rowcount > 0:
                 logger.info(f"Wallet TON establecida finalmente para {telegram_id} a: {ton_wallet_address}")

    except sqlite3.Error as e:
        logger.error(f"Error actualizando wallet TON para {telegram_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def get_user_ton_wallet(telegram_id: str) -> str | None:
    """Obtiene la wallet TON registrada de un usuario."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ton_wallet FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        return result["ton_wallet"] if result and result["ton_wallet"] else None
    except sqlite3.Error as e:
        logger.error(f"Error obteniendo wallet TON para {telegram_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

# --- Funciones para Transacciones TON (Verificación de Pagos Off-chain) ---

def add_ton_transaction(
    telegram_id: str | None, user_ton_wallet: str, bot_ton_wallet: str,
    transaction_hash: str, value_nano: int, comment: str | None, 
    lottery_round_id_assoc: int | None = None
) -> int | None:
    """Guarda una transacción TON verificada y la asocia a un usuario (si se conoce)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        tx_time_utc_iso = datetime.now(timezone.utc).isoformat()
        
        # Asegurar que el usuario exista si se proporciona telegram_id
        if telegram_id:
             # get_or_create_user(telegram_id, None, None) # Esto se haría en el handler antes de llamar a find_transaction
             update_user_ton_wallet(telegram_id, user_ton_wallet) # Asegurar que la wallet del usuario está registrada

        cursor.execute(
            """INSERT INTO ton_transactions 
               (telegram_id, user_ton_wallet, bot_ton_wallet, transaction_hash, value_nano, comment, transaction_time, lottery_round_id_assoc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (telegram_id, user_ton_wallet, bot_ton_wallet, transaction_hash, value_nano, comment, tx_time_utc_iso, lottery_round_id_assoc)
        )
        conn.commit()
        tx_db_id = cursor.lastrowid
        logger.info(f"Transacción TON {transaction_hash[:10]}... guardada con ID {tx_db_id} para usuario {telegram_id}, asociada a ronda {lottery_round_id_assoc}.")
        return tx_db_id
    except sqlite3.IntegrityError:
        logger.warning(f"Transacción TON con hash {transaction_hash[:10]}... ya existe. No se añadió.")
        return None # O podrías buscar el ID existente si es necesario
    except sqlite3.Error as e:
        logger.error(f"Error guardando transacción TON {transaction_hash[:10]}...: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

# --- Funciones check_transaction y add_v_transaction esperadas por ton_api.py ---
# Estas funciones se adaptan para usar la nueva tabla ton_transactions

def check_transaction(transaction_hash: str) -> bool:
    """
    Verifica si una transacción con el dado hash ya existe en la tabla ton_transactions.
    Esta es la función esperada por ton_api.py del Storefront bot.
    Retorna True si existe, False si no.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ton_transactions WHERE transaction_hash = ?", (transaction_hash,))
        result = cursor.fetchone()
        if result:
            logger.debug(f"check_transaction: Hash {transaction_hash[:10]}... encontrado en DB.")
            return True # El hash existe en la base de datos
        else:
            logger.debug(f"check_transaction: Hash {transaction_hash[:10]}... NO encontrado en DB.")
            return False # El hash no existe

    except sqlite3.Error as e:
        logger.error(f"Error al verificar transacción en DB: {e}", exc_info=True)
        # Si hay un error de DB al verificar, asumimos que no está verificada
        # para evitar perder transacciones, pero logueamos el error.
        return False

def add_v_transaction(source: str, tx_hash: str, value: int, comment: str) -> bool:
    """
    Añade una transacción verificada a la tabla ton_transactions.
    Esta es la función esperada por ton_api.py del Storefront bot.
    En este contexto, necesitamos obtener el telegram_id del usuario que se espera
    que haya enviado esta transacción. Esto no es trivial solo con la wallet de origen.
    La forma más limpia es que find_transaction en ton_api.py obtenga el telegram_id
    (quizás buscando en la tabla users por la wallet de origen) y el bot_ton_wallet (de config)
    y llame directamente a add_ton_transaction con todos los datos.

    Sin embargo, para que ton_api.py compile usando esta función, la mantenemos,
    pero su funcionalidad real es limitada sin el telegram_id y bot_ton_wallet.
    Intentaremos llamar a add_ton_transaction con valores conocidos o NULL.
    """
    logger.warning("Llamada a add_v_transaction. Idealmente, find_transaction debería llamar a add_ton_transaction con más datos (telegram_id, bot_wallet).")
    
    # Intentamos obtener el telegram_id asociado a esta wallet de origen
    # Esto requiere que el usuario haya registrado su wallet previamente
    conn = None
    telegram_id_assoc = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id FROM users WHERE ton_wallet = ?", (source,))
        user_row = cursor.fetchone()
        if user_row:
            telegram_id_assoc = user_row["telegram_id"]
            logger.debug(f"add_v_transaction: Wallet {source} asociada a telegram_id {telegram_id_assoc}.")
        else:
             logger.warning(f"add_v_transaction: No se encontró telegram_id asociado a la wallet de origen {source}. La transacción se guardará sin asociación directa a usuario Telegram.")
    except sqlite3.Error as e:
        logger.error(f"Error buscando telegram_id para wallet {source}: {e}", exc_info=True)
        # Continuamos aunque no podamos asociar el telegram_id


    # Necesitamos el bot_ton_wallet. Idealmente, ton_api.py lo pasaría.
    # Como no lo hace, lo obtenemos de config.json aquí, lo cual no es ideal
    # por acoplamiento, pero permite que la función intente guardar.
    bot_wallet_from_config = None
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        with open(config_path, 'r') as f:
            config_json = json.load(f)
            work_mode = config_json.get('WORK_MODE', 'testnet')
            if work_mode == 'mainnet':
                bot_wallet_from_config = config_json.get('MAINNET_WALLET')
            else:
                bot_wallet_from_config = config_json.get('TESTNET_WALLET')
    except Exception as e:
        logger.error(f"Error obteniendo bot_wallet de config para add_v_transaction: {e}", exc_info=True)
        # Continuamos, bot_ton_wallet será None si falla

    # Ahora llamamos a add_ton_transaction con los datos disponibles
    # add_ton_transaction maneja la unicidad por hash
    added_successfully = add_ton_transaction(
        telegram_id=telegram_id_assoc,
        user_ton_wallet=source,
        bot_ton_wallet=bot_wallet_from_config if bot_wallet_from_config else "UNKNOWN_BOT_WALLET", # Usar placeholder si no se obtiene
        transaction_hash=tx_hash,
        value_nano=value,
        comment=comment,
        lottery_round_id_assoc=None # No asociamos a ronda de lotería simulada aquí
    )

    # add_ton_transaction retorna el ID si es exitoso, None si falla o ya existe.
    # Queremos que add_v_transaction retorne True si se registró (nuevo o ya existía), False si hubo un error de DB.
    # check_transaction ya nos dice si existe. Si llegamos aquí, no existía.
    # Entonces, si added_successfully no es None, significa que se añadió.
    return added_successfully is not None


def get_user_ton_payments_history(telegram_id: str) -> list[dict]:
    """Obtiene el historial de pagos TON verificados de un usuario."""
    conn = None
    payments = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT transaction_hash, value_nano, comment, transaction_time, lottery_round_id_assoc, user_ton_wallet "
            "FROM ton_transactions WHERE telegram_id = ? ORDER BY transaction_time DESC",
            (telegram_id,)
        )
        for row in cursor.fetchall():
            payments.append(dict(row))
        return payments
    except sqlite3.Error as e:
        logger.error(f"Error obteniendo historial de pagos TON para {telegram_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


# --- Funciones para Rondas de Lotería (Simuladas, adaptadas de tu original) ---
# Estas funciones son para la lógica de simulación si aún la necesitas.
# Si tu bot solo usará pagos TON reales, puedes eliminar o ignorar estas funciones
# y las tablas 'rounds', 'round_participants', 'draw_results', 'creator_commission'.

def create_new_round(round_type: str, creator_telegram_id: str | None, ticket_price: float = 1.0) -> int | None:
    """Crea una nueva ronda (simulada) y retorna su ID."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_utc_iso = datetime.now(timezone.utc).isoformat()
        
        # Asegurar que el creador (si es un usuario) exista
        if creator_telegram_id:
            # get_or_create_user(creator_telegram_id, None, None) # Esto se haría en el handler
            pass


        cursor.execute(
            "INSERT INTO rounds (start_time, status, round_type, creator_telegram_id, ticket_price_simulated) VALUES (?, ?, ?, ?, ?)",
            (now_utc_iso, 'waiting_to_start', round_type, creator_telegram_id, ticket_price)
        )
        round_id = cursor.lastrowid
        if not round_id:
            logger.error("No se pudo obtener round_id después de la inserción.")
            return None

        sim_addr = generate_simulated_smart_contract_address(round_id)
        cursor.execute("UPDATE rounds SET simulated_contract_address = ? WHERE id = ?", (sim_addr, round_id))
        conn.commit()
        logger.info(f"Nueva ronda simulada '{round_type}' ID:{round_id}, Precio:{ticket_price} (Creador:{creator_telegram_id}) creada.")
        return round_id
    except sqlite3.Error as e:
        logger.error(f"Error creando nueva ronda simulada '{round_type}': {e}", exc_info=True)
        if conn: conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def get_round_by_id(round_id: int) -> dict | None:
    """Obtiene datos de una ronda simulada por su ID."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM rounds WHERE id = ?", (round_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(f"Error obteniendo ronda simulada ID {round_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()
            
def get_active_round() -> dict | None:
    """Obtiene la ronda simulada activa (waiting_to_start o waiting_for_payments, no eliminada)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM rounds WHERE status IN (?, ?) AND deleted = 0 ORDER BY id DESC LIMIT 1",
            ('waiting_to_start', 'waiting_for_payments')
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(f"Error obteniendo ronda simulada activa: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()
            
def get_rounds_by_status(status_list: list[str], check_deleted: bool = False) -> list[dict]:
    """Obtiene rondas simuladas por lista de estados."""
    conn = None
    rounds = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ','.join(['?'] * len(status_list))
        sql = f"SELECT * FROM rounds WHERE status IN ({placeholders})"
        params = list(status_list)
        if check_deleted:
            sql += " AND deleted = 0"
        sql += " ORDER BY id DESC"
        cursor.execute(sql, params)
        for row in cursor.fetchall():
            rounds.append(dict(row))
        return rounds
    except sqlite3.Error as e:
        logger.error(f"Error obteniendo rondas simuladas por status {status_list}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()

def add_participant_to_round(round_id: int, telegram_id: str, assigned_number: int) -> bool:
    """Añade un participante a una ronda simulada (implica "pago simulado" hecho)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_utc_iso = datetime.now(timezone.utc).isoformat()
        # get_or_create_user(telegram_id, None, None) # Asegurar que el usuario existe (se haría en handler)
        cursor.execute(
            "INSERT INTO round_participants (round_id, telegram_id, assigned_number, paid_real, purchase_time) VALUES (?, ?, ?, 1, ?)",
            (round_id, telegram_id, assigned_number, now_utc_iso)
        )
        conn.commit()
        logger.info(f"Participante {telegram_id} añadido a ronda simulada {round_id} con número {assigned_number}.")
        return True
    except sqlite3.IntegrityError: # Usuario ya en la ronda
        logger.warning(f"Participante {telegram_id} ya estaba en ronda simulada {round_id}.")
        return False
    except sqlite3.Error as e:
        logger.error(f"Error añadiendo participante {telegram_id} a ronda simulada {round_id}: {e}", exc_info=True)
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def get_participants_in_round(round_id: int) -> list[dict]:
    """Obtiene participantes de una ronda simulada."""
    conn = None
    participants = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT rp.telegram_id, u.username, u.first_name, rp.assigned_number, rp.paid_real, rp.purchase_time
               FROM round_participants rp
               LEFT JOIN users u ON rp.telegram_id = u.telegram_id
               WHERE rp.round_id = ? ORDER BY rp.assigned_number""",
            (round_id,)
        )
        for row in cursor.fetchall():
            participants.append(dict(row))
        return participants
    except sqlite3.Error as e:
        logger.error(f"Error obteniendo participantes de ronda simulada {round_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()

def count_round_participants(round_id: int) -> int:
    """Cuenta participantes en una ronda simulada (asume que son los que 'pagaron' al unirse)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(id) FROM round_participants WHERE round_id = ? AND paid_real = 1", (round_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    except sqlite3.Error as e:
        logger.error(f"Error contando participantes de ronda simulada {round_id}: {e}", exc_info=True)
        return 0
    finally:
        if conn:
            conn.close()

def update_round_status(round_id: int, new_status: str) -> bool:
    """Actualiza el estado de una ronda simulada."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_utc_iso = datetime.now(timezone.utc).isoformat()
        sql = "UPDATE rounds SET status = ?"
        params = [new_status]
        if new_status in ['finished', 'cancelled']:
            sql += ", end_time = ?"
            params.append(now_utc_iso)
        sql += " WHERE id = ?"
        params.append(round_id)
        
        cursor.execute(sql, tuple(params))
        conn.commit()
        updated_rows = cursor.rowcount
        if updated_rows > 0:
            logger.info(f"Estado de ronda simulada {round_id} actualizado a '{new_status}'.")
        else:
            logger.warning(f"No se actualizó estado para ronda simulada {round_id} (¿no existe o estado ya era el mismo?).")
        return updated_rows > 0
    except sqlite3.Error as e:
        logger.error(f"Error actualizando estado de ronda simulada {round_id}: {e}", exc_info=True)
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def save_draw_results(round_id: int, results_list: list[dict]) -> bool:
    """Guarda resultados de un sorteo simulado."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Iniciar transacción explícitamente para inserciones múltiples
        conn.execute("BEGIN TRANSACTION")
        for r_data in results_list:
            cursor.execute(
                """INSERT INTO draw_results 
                   (round_id, drawn_number, draw_order, winner_telegram_id, prize_amount_simulated, prize_amount_real) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (round_id, r_data.get('drawn_number'), r_data.get('draw_order'), r_data.get('winner_telegram_id'),
                 r_data.get('prize_amount_simulated'), r_data.get('prize_amount_real'))
            )
        conn.commit() # Commit al final si todo va bien
        logger.info(f"Resultados del sorteo simulado para ronda {round_id} guardados.")
        return True
    except sqlite3.IntegrityError as ie: # Ej. UNIQUE constraint falló
        logger.warning(f"Error de integridad guardando resultados de sorteo para ronda {round_id}: {ie}")
        if conn: conn.rollback()
        return False
    except sqlite3.Error as e:
        logger.error(f"Error guardando resultados de sorteo para ronda {round_id}: {e}", exc_info=True)
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def save_creator_commission(round_id: int, creator_type: str, creator_telegram_id: str | None,
                            amount_simulated: str, amount_real: float | None, transaction_id: str | None = None) -> bool:
    """Guarda una comisión simulada. Esta función ahora maneja su propia conexión."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO creator_commission
               (round_id, creator_type, creator_telegram_id, amount_simulated, amount_real, transaction_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (round_id, creator_type, creator_telegram_id, amount_simulated, amount_real, transaction_id)
        )
        conn.commit()
        logger.info(f"Comisión simulada '{creator_type}' para ronda {round_id} guardada.")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Comisión simulada '{creator_type}' para ronda {round_id} (Creador: {creator_telegram_id}) ya existe.")
        return False # O True si no se considera un error crítico
    except sqlite3.Error as e:
        logger.error(f"Error guardando comisión simulada '{creator_type}' para ronda {round_id}: {e}", exc_info=True)
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    # Configuración básica de logging si se ejecuta directamente
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # Re-obtener logger después de configurar (para db)
    logger = logging.getLogger(__name__)
    logging.getLogger('db').setLevel(logging.INFO) # Mostrar logs de db también

    print("Ejecutando pruebas directas de db.py...")

    DB_TEST_NAME = 'test_db_direct.db'
    # Limpiar DB de prueba anterior si existe
    if os.path.exists(DB_TEST_NAME):
        os.remove(DB_TEST_NAME)
        logger.info(f"Archivo de DB de prueba '{DB_TEST_NAME}' existente eliminado.")

    init_db(DB_TEST_NAME) # Llama con el nombre de la DB de prueba
    logger.info(f"Base de datos de prueba '{DB_TEST_NAME}' inicializada/verificada.")

    # --- Pruebas de funciones de usuario ---
    print("\n--- Pruebas de funciones de usuario ---")
    get_or_create_user("123", "testuser1", "Test")
    get_or_create_user("456", "testuser2", "Another")
    get_or_create_user("123", "testuser1_updated", "Test Updated") # Probar actualización

    update_user_ton_wallet("123", "EQ_test_wallet_1")
    update_user_ton_wallet("456", "EQ_test_wallet_2")
    update_user_ton_wallet("999", "EQ_non_existent_user") # Probar usuario no existente

    wallet_123 = get_user_ton_wallet("123")
    logger.info(f"Wallet para usuario 123: {wallet_123}")
    wallet_999 = get_user_ton_wallet("999")
    logger.info(f"Wallet para usuario 999: {wallet_999}")


    # --- Pruebas de funciones de transacciones TON ---
    print("\n--- Pruebas de funciones de transacciones TON ---")
    test_tx_hash_1 = "hash_tx_1"
    test_tx_hash_2 = "hash_tx_2"
    test_tx_hash_1_duplicate = "hash_tx_1" # Hash duplicado

    # Prueba check_transaction
    check_1_before = check_transaction(test_tx_hash_1)
    logger.info(f"check_transaction para {test_tx_hash_1}: {check_1_before} (Debería ser False)")

    # Prueba add_ton_transaction
    added_1 = add_ton_transaction(
        telegram_id="123",
        user_ton_wallet="EQ_test_wallet_1",
        bot_ton_wallet="EQ_bot_wallet",
        transaction_hash=test_tx_hash_1,
        value_nano=1000000000,
        comment="Test Payment 1",
        lottery_round_id_assoc=None
    )
    logger.info(f"add_ton_transaction para {test_tx_hash_1}: ID {added_1} (Debería ser un número)")

    added_2 = add_ton_transaction(
        telegram_id="456",
        user_ton_wallet="EQ_test_wallet_2",
        bot_ton_wallet="EQ_bot_wallet",
        transaction_hash=test_tx_hash_2,
        value_nano=500000000,
        comment="Test Payment 2",
        lottery_round_id_assoc=1 # Asociar a ronda simulada ID 1 (si existe)
    )
    logger.info(f"add_ton_transaction para {test_tx_hash_2}: ID {added_2} (Debería ser un número)")
    
    # Prueba add_ton_transaction duplicada
    added_1_duplicate = add_ton_transaction(
        telegram_id="123", # Mismo usuario, misma wallet, etc.
        user_ton_wallet="EQ_test_wallet_1",
        bot_ton_wallet="EQ_bot_wallet",
        transaction_hash=test_tx_hash_1_duplicate, # Hash duplicado
        value_nano=1000000000,
        comment="Test Payment 1 Duplicate",
        lottery_round_id_assoc=None
    )
    logger.info(f"add_ton_transaction duplicada para {test_tx_hash_1_duplicate}: ID {added_1_duplicate} (Debería ser None)")


    # Prueba check_transaction de nuevo
    check_1_after = check_transaction(test_tx_hash_1)
    logger.info(f"check_transaction para {test_tx_hash_1}: {check_1_after} (Debería ser True)")
    check_3_non_existent = check_transaction("hash_non_existent")
    logger.info(f"check_transaction para hash_non_existent: {check_3_non_existent} (Debería ser False)")


    # Prueba add_v_transaction (la función esperada por ton_api.py)
    # Esta función ahora intenta buscar el telegram_id y bot_ton_wallet
    print("\n--- Pruebas de add_v_transaction (usada por ton_api.py) ---")
    test_tx_hash_3 = "hash_tx_3_via_add_v"
    source_for_add_v = "EQ_test_wallet_1" # Wallet que ya asociamos a user 123
    value_for_add_v = 3000000000
    comment_for_add_v = "Payment via add_v"

    check_3_before = check_transaction(test_tx_hash_3)
    logger.info(f"check_transaction para {test_tx_hash_3}: {check_3_before} (Debería ser False)")

    added_via_v_1 = add_v_transaction(source_for_add_v, test_tx_hash_3, value_for_add_v, comment_for_add_v)
    logger.info(f"add_v_transaction para {test_tx_hash_3}: {added_via_v_1} (Debería ser True)")

    check_3_after = check_transaction(test_tx_hash_3)
    logger.info(f"check_transaction para {test_tx_hash_3}: {check_3_after} (Debería ser True)")

    # Prueba add_v_transaction duplicada
    added_via_v_duplicate = add_v_transaction(source_for_add_v, test_tx_hash_3, value_for_add_v, "Duplicate via add_v")
    logger.info(f"add_v_transaction duplicada para {test_tx_hash_3}: {added_via_v_duplicate} (Debería ser False)")


    # --- Pruebas de historial de pagos TON ---
    print("\n--- Pruebas de historial de pagos TON ---")
    history_123 = get_user_ton_payments_history("123")
    logger.info(f"Historial de pagos TON para usuario 123 ({len(history_123)} transacciones):")
    for payment in history_123:
        logger.info(f"  Hash: {payment['transaction_hash'][:10]}..., Valor: {payment['value_nano']}, Comentario: '{payment['comment']}'")

    history_456 = get_user_ton_payments_history("456")
    logger.info(f"Historial de pagos TON para usuario 456 ({len(history_456)} transacciones):")
    for payment in history_456:
        logger.info(f"  Hash: {payment['transaction_hash'][:10]}..., Valor: {payment['value_nano']}, Comentario: '{payment['comment']}'")

    history_non_existent = get_user_ton_payments_history("999")
    logger.info(f"Historial de pagos TON para usuario 999 ({len(history_non_existent)} transacciones):")
    if not history_non_existent:
        logger.info("  Lista vacía como se esperaba.")


    # --- Pruebas de funciones de Rondas Simuladas (Opcional) ---
    # Descomenta y adapta si necesitas probar estas funciones también
    # print("\n--- Pruebas de Rondas Simuladas ---")
    # round_id_1 = create_new_round('scheduled', None, 1.0)
    # if round_id_1:
    #     logger.info(f"Ronda simulada creada con ID: {round_id_1}")
    #     add_participant_to_round(round_id_1, "123", 1)
    #     add_participant_to_round(round_id_1, "456", 2)
    #     count_p = count_round_participants(round_id_1)
    #     logger.info(f"Participantes en ronda {round_id_1}: {count_p}")
    #     update_round_status(round_id_1, 'finished')
    #     round_data = get_round_by_id(round_id_1)
    #     logger.info(f"Estado final de ronda {round_id_1}: {round_data.get('status')}")


    print("\nPruebas directas de db.py finalizadas.")

