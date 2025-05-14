# botloteria/src/db.py

import sqlite3
import logging
# Importamos datetime y timezone para manejo de tiempo y zonas horarias
from datetime import datetime, timedelta, timezone


logger = logging.getLogger(__name__)

DATABASE_NAME = 'bot_data.db'

# Función para generar la dirección simulada (Se llama desde create_new_round)
# Aunque hashlib no se usa en otras funciones de db.py, la lógica de generación de dirección es específica de este módulo.
import hashlib # Necesario para generar la dirección simulada

def generate_simulated_smart_contract_address(round_id: int) -> str:
    """Genera una dirección simulada para el Smart Contract basada en ID de ronda y un timestamp."""
    # Usamos el ID de ronda y un timestamp para generar una dirección única por ronda en la simulación.
    # En una implementación real, la dirección del contrato derivaría de su código y datos iniciales,
    # y se obtendría al desplegar o interactuar con el contrato en la blockchain.
    data_to_hash = f"contract_{round_id}-{datetime.now().timestamp()}"
    simulated_hash = hashlib.sha256(data_to_hash.encode()).hexdigest()
    return f"EQ_{simulated_hash[:12]}" # Formato que se parece a una dirección de TON


def init_db():
    """Inicializa la base de datos y crea las tablas si no existen, añadiendo columnas si faltan."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        # Tabla para usuarios (registraremos su telegram_id y username)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id TEXT PRIMARY KEY,
                username TEXT UNIQUE
            )
        ''')

        # Tabla para rondas
        # status: 'waiting_to_start', 'waiting_for_payments', 'drawing', 'finished', 'cancelled'
        # round_type: 'scheduled', 'user_created'
        # deleted: 0 (False) o 1 (True) - Marca para eliminación
        # simulated_contract_address: Dirección simulada del Smart Contract
        # start_time: Cuando se creó la ronda (guardado como texto ISO 8601)
        # end_time: Cuando terminó (sorteada o cancelada, guardado como texto ISO 8601)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME,
                status TEXT NOT NULL,
                round_type TEXT NOT NULL DEFAULT 'scheduled',
                creator_telegram_id TEXT,
                deleted BOOLEAN DEFAULT 0,
                simulated_contract_address TEXT,
                FOREIGN KEY (creator_telegram_id) REFERENCES users(telegram_id)
            )
        ''')

        # --- Añadir nuevas columnas a 'rounds' si la base de datos ya existe (lógica de migración simple) ---
        # Intentamos leer de la columna; si falla (OperationalError), la añadimos.
        try:
            cursor.execute("SELECT round_type FROM rounds LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE rounds ADD COLUMN round_type TEXT NOT NULL DEFAULT 'scheduled'")
            logger.info("Columna 'round_type' añadida a la tabla 'rounds'.")
        try:
            cursor.execute("SELECT creator_telegram_id FROM rounds LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE rounds ADD COLUMN creator_telegram_id TEXT")
            logger.info("Columna 'creator_telegram_id' añadida a la tabla 'rounds'.")
        try:
            cursor.execute("SELECT deleted FROM rounds LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE rounds ADD COLUMN deleted BOOLEAN DEFAULT 0")
            logger.info("Columna 'deleted' añadida a la tabla 'rounds'.")
        try:
            cursor.execute("SELECT simulated_contract_address FROM rounds LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE rounds ADD COLUMN simulated_contract_address TEXT")
            logger.info("Columna 'simulated_contract_address' añadida a la tabla 'rounds'.")
        # --- Fin Añadir nuevas columnas a 'rounds' ---


        # Tabla para participantes de ronda
        # round_id: A qué ronda pertenecen
        # telegram_id: Quién es el participante
        # assigned_number: El número asignado en esa ronda (1 al número de participantes)
        # paid_simulated: Si ha "pagado" en la simulación inicial (ya no se usa mucho)
        # paid_real: Si ha "pagado real" simulado (confirmado pago al contrato simulado). Ahora es true al unirse.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS round_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                telegram_id TEXT NOT NULL,
                assigned_number INTEGER,
                paid_simulated BOOLEAN DEFAULT 0,
                paid_real BOOLEAN DEFAULT 0,
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
                UNIQUE(round_id, telegram_id) -- Un usuario solo puede participar una vez por ronda
            )
        ''')

        # Tabla para resultados del sorteo
        # round_id: A qué ronda pertenecen los resultados
        # drawn_number: El número que salió sorteado
        # draw_order: El orden en que salió (para múltiples ganadores). Ahora siempre 0.
        # winner_telegram_id: Quién tenía ese número (si alguien lo tenía)
        # prize_amount_simulated: Cuánto ganó en la simulación (texto)
        # prize_amount_real: Cuánto ganó en la simulación (numérico, para cálculos)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS draw_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                drawn_number INTEGER NOT NULL,
                draw_order INTEGER NOT NULL,
                winner_telegram_id TEXT,
                prize_amount_simulated TEXT,
                prize_amount_real REAL,
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (winner_telegram_id) REFERENCES users(telegram_id),
                UNIQUE(round_id, draw_order) -- Solo un resultado por orden de sorteo por ronda
            )
        ''')

        # Tabla para registrar la comisión del creador por ronda (Bot, Usuario Creador, Gas Simulado)
        # round_id: A qué ronda pertenece la comisión
        # creator_type: Tipo de entidad ('bot', 'user', 'gas_fee')
        # creator_telegram_id: ID del usuario si creator_type es 'user' (NULL para 'bot' o 'gas_fee')
        # amount_simulated: Monto de la comisión simulada (texto)
        # amount_real: Monto de la comisión simulada (numérico)
        # transaction_id: Opcional: ID de transacción de TON real (puede ser NULL)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS creator_commission (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                creator_type TEXT NOT NULL,
                creator_telegram_id TEXT,
                amount_simulated TEXT,
                amount_real REAL,
                transaction_id TEXT,
                FOREIGN KEY (round_id) REFERENCES rounds(id),
                FOREIGN KEY (creator_telegram_id) REFERENCES users(telegram_id),
                UNIQUE(round_id, creator_type) -- <-- Clave única compuesta: Una entrada por ronda y tipo de creador
            )
        ''')
        # --- Añadir nuevas columnas a 'creator_commission' si faltan (lógica de migración simple) ---
        try:
            cursor.execute("SELECT creator_type FROM creator_commission LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE creator_commission ADD COLUMN creator_type TEXT NOT NULL DEFAULT 'bot'")
            logger.info("Columna 'creator_type' añadida a la tabla 'creator_commission'.")
            # Si se añade creator_type, es probable que también falte creator_telegram_id
            try:
                 cursor.execute("SELECT creator_telegram_id FROM creator_commission LIMIT 1")
            except sqlite3.OperationalError:
                 cursor.execute("ALTER TABLE creator_commission ADD COLUMN creator_telegram_id TEXT")
                 logger.info("Columna 'creator_telegram_id' añadida a la tabla 'creator_commission'.")
        # --- Fin Añadir nuevas columnas a 'creator_commission' ---


        conn.commit() # Confirmar todos los cambios pendientes en la base de datos
        logger.info("Tablas y columnas de base de datos creadas o verificadas.")

    except sqlite3.Error as e:
        logger.error(f"Error al inicializar/actualizar la base de datos: {e}")
        # En un bot de producción, podrías querer salir o manejar este error de forma más robusta.
    finally:
        if conn:
            conn.close() # Asegurarse de cerrar la conexión


# --- Funciones de Interacción con la Base de Datos ---
# Estas funciones encapsulan la lógica de acceso directo a la DB.

def get_db_connection():
    """Establece una conexión a la base de datos SQLite."""
    # Puedes añadir lógica aquí para manejar múltiples hilos si es necesario,
    # aunque SQLite tiene limitaciones. Para una aplicación más grande, SQLAlchemy es mejor.
    # Para la depuración de transacciones, es útil tener isolation_level=None
    # pero el comportamiento estándar es suficiente si las transacciones se manejan externamente.
    return sqlite3.connect(DATABASE_NAME)

def get_or_create_user(telegram_id: str, username: str) -> None:
    """
    Busca un usuario por telegram_id. Si no existe, lo crea.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
        if user is None:
            # Crear nuevo usuario si no existe
            cursor.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
            conn.commit()
            logger.info(f"Usuario creado: {username} ({telegram_id})")
    except sqlite3.Error as e:
        logger.error(f"Error al obtener o crear usuario {telegram_id}: {e}")
    finally:
        if conn:
            conn.close()


def create_new_round(round_type: str, creator_telegram_id: str | None) -> int | None:
    """
    Crea una nueva ronda en la base de datos con estado 'waiting_to_start', tipo y creador opcional.
    Genera y guarda la dirección simulada del Smart Contract para la ronda.
    Es llamada desde round_manager.py.
    Retorna el ID de la nueva ronda o None si hay error.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rounds (status, round_type, creator_telegram_id) VALUES (?, ?, ?)",
            ('waiting_to_start', round_type, creator_telegram_id)
        )
        round_id = cursor.lastrowid

        simulated_addr = generate_simulated_smart_contract_address(round_id)

        cursor.execute(
            "UPDATE rounds SET simulated_contract_address = ? WHERE id = ?",
            (simulated_addr, round_id)
        )

        conn.commit()
        logger.info(f"Nueva ronda de tipo '{round_type}' creada en DB con ID: {round_id}, Dirección Simulada: {simulated_addr} (Creador: {creator_telegram_id}).")
        return round_id
    except sqlite3.Error as e:
        logger.error(f"Error al crear nueva ronda de tipo '{round_type}' en DB: {e}")
        if conn: conn.rollback()
        return None
    finally:
        if conn:
            conn.close()


def get_active_round() -> tuple | None:
    """
    Busca la ronda activa actual (estado 'waiting_to_start' o 'waiting_for_payments')
    que NO esté marcada como eliminada. Es llamada desde round_manager.py.
    Retorna una tupla con los datos de la ronda o None si no hay ronda activa.
    Retorna (id, start_time, end_time, status, round_type, creator_telegram_id, deleted, simulated_contract_address)
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, start_time, end_time, status, round_type, creator_telegram_id, deleted, simulated_contract_address FROM rounds WHERE status IN (?, ?) AND deleted = 0 ORDER BY start_time DESC LIMIT 1",
            ('waiting_to_start', 'waiting_for_payments')
        )
        round_data = cursor.fetchone()

        if round_data:
            round_data = list(round_data)
            round_data[6] = bool(round_data[6])
            round_data = tuple(round_data)

            logger.debug(f"Ronda activa encontrada en DB: {round_data}")
        else:
            logger.debug("No se encontró ronda activa en DB.")

        return round_data
    except sqlite3.Error as e:
        logger.error(f"Error al obtener ronda activa de DB: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_round_by_id(round_id: int) -> tuple | None:
    """
    Busca una ronda específica por su ID. Es llamada desde round_manager.py.
    Retorna una tupla con los datos de la ronda o None si no existe.
    Retorna (id, start_time, end_time, status, round_type, creator_telegram_id, deleted, simulated_contract_address)
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, start_time, end_time, status, round_type, creator_telegram_id, deleted, simulated_contract_address FROM rounds WHERE id = ?",
            (round_id,)
        )
        round_data = cursor.fetchone()

        if round_data:
            round_data = list(round_data)
            round_data[6] = bool(round_data[6])
            round_data = tuple(round_data)

            logger.debug(f"Ronda encontrada por ID {round_id}: {round_data}")
        else:
            logger.debug(f"No se encontró ronda con ID {round_id}.")

        return round_data
    except sqlite3.Error as e:
        logger.error(f"Error al obtener ronda por ID {round_id} de DB: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_open_rounds() -> list[tuple]:
    """
    Obtiene una lista de rondas que están abiertas ('waiting_to_start' o 'waiting_for_payments')
    y NO marcadas como eliminadas. Es llamada desde round_manager.py.
    Retorna una lista de tuplas.
    Retorna (id, start_time, status, round_type, simulated_contract_address)
    """
    conn = None
    rounds_list = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, start_time, status, round_type, simulated_contract_address FROM rounds WHERE status IN (?, ?) AND deleted = 0 ORDER BY start_time DESC",
            ('waiting_to_start', 'waiting_for_payments')
        )
        rounds_list = cursor.fetchall()

        logger.debug(f"Obtenidas {len(rounds_list)} rondas abiertas.")
    except sqlite3.Error as e:
        logger.error(f"Error al obtener rondas abiertas de DB: {e}")
    finally:
        if conn:
            conn.close()

    return rounds_list


def get_rounds_by_status(status_list: list[str], check_deleted: bool = False) -> list[tuple]:
    """
    Obtiene una lista de rondas por sus estados. Es llamada desde bot.py (JobQueue).
    Incluye opción para filtrar por el flag 'deleted'.
    Retorna una lista de tuplas (id, start_time, status, round_type, creator_telegram_id, deleted, simulated_contract_address).
    """
    conn = None
    rounds_list = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        status_placeholders = ', '.join(['?' for _ in status_list])
        sql = f"SELECT id, start_time, status, round_type, creator_telegram_id, deleted, simulated_contract_address FROM rounds WHERE status IN ({status_placeholders})"
        query_params = status_list

        if check_deleted:
            sql += " AND deleted = 0"

        sql += " ORDER BY start_time DESC"

        cursor.execute(sql, tuple(query_params))
        rounds_list = cursor.fetchall()

        logger.debug(f"Obtenidas {len(rounds_list)} rondas con estados {status_list} (check_deleted={check_deleted}).")
    except sqlite3.Error as e:
        logger.error(f"Error al obtener rondas por estados {status_list} de DB: {e}")
    finally:
        if conn:
            conn.close()

    return rounds_list


def add_participant_to_round(round_id: int, telegram_id: str, assigned_number: int) -> bool:
    """
    Añade un usuario como participante a una ronda específica.
    Retorna True si se añadió correctamente, False si ya participaba o hubo error.
    Es llamada desde round_manager.py.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO round_participants (round_id, telegram_id, assigned_number) VALUES (?, ?, ?)",
            (round_id, telegram_id, assigned_number)
        )
        conn.commit()
        logger.info(f"Participante {telegram_id} añadido a ronda {round_id} con número {assigned_number}.")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Participante {telegram_id} ya estaba en ronda {round_id}.")
        return False
    except sqlite3.Error as e:
        logger.error(f"Error al añadir participante {telegram_id} a ronda {round_id}: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def get_participants_in_round(round_id: int) -> list[tuple]:
    """
    Obtiene la lista de participantes (telegram_id, username, assigned_number, paid_simulated, paid_real)
    para una ronda específica. Es llamada desde round_manager.py y handlers.py.
    Retorna una lista de tuplas.
    """
    conn = None
    participants_list = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Usamos LEFT JOIN para incluir participantes incluso si su usuario no está en la tabla users (aunque get_or_create_user debería evitar esto)
        # Esto puede ayudar a diagnosticar si faltan usuarios.
        cursor.execute(
            """
            SELECT
                rp.telegram_id,
                u.username, -- Será NULL if no matching user
                rp.assigned_number,
                rp.paid_simulated,
                rp.paid_real
            FROM round_participants rp
            LEFT JOIN users u ON rp.telegram_id = u.telegram_id -- <-- CAMBIO: Usar LEFT JOIN
            WHERE rp.round_id = ?
            ORDER BY rp.assigned_number
            """,
            (round_id,)
        )
        participants_list = cursor.fetchall()

        participants_list = [list(p) for p in participants_list]
        for p in participants_list:
            p[3] = bool(p[3])
            p[4] = bool(p[4])
        participants_list = [tuple(p) for p in participants_list]

        # --- AÑADE ESTE LOG DE DEPURACIÓN AQUÍ ---
        logger.debug(f"Datos brutos de participantes obtenidos de DB para ronda {round_id}: {participants_list}") # <-- Nuevo log

        logger.debug(f"Obtenidos {len(participants_list)} participantes para ronda {round_id}.")
    except sqlite3.Error as e:
        logger.error(f"Error al obtener participantes para ronda {round_id}: {e}")
    finally:
        if conn:
            conn.close()

    return participants_list


def count_participants_in_round(round_id: int) -> int:
    """
    Cuenta el número de participantes en una ronda específica. Es llamada desde round_manager.py.
    Retorna el número de participantes.
    """
    conn = None
    count = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM round_participants WHERE round_id = ?", (round_id,))
        count = cursor.fetchone()[0]
        logger.debug(f"Contados {count} participantes en ronda {round_id}.")
    except sqlite3.Error as e:
        logger.error(f"Error al contar participantes en ronda {round_id}: {e}")
    finally:
        if conn:
            conn.close()

    return count


def update_participant_paid_status(round_id: int, telegram_id: str, paid_simulated: bool = None, paid_real: bool = None) -> bool:
    """
    Actualiza el estado de pago simulado y/o pago real de un participante en una ronda específica.
    Si un parámetro de pago es None, no se actualiza ese campo.
    Retorna True si se actualizó, False si no se encontró o hubo error.
    Es llamada desde payment_manager.py y round_manager.py.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        update_fields = []
        update_values = []

        if paid_simulated is not None:
            update_fields.append("paid_simulated = ?")
            update_values.append(1 if paid_simulated else 0)
        if paid_real is not None:
            update_fields.append("paid_real = ?")
            update_values.append(1 if paid_real else 0)

        if not update_fields:
             logger.warning("Llamada a update_participant_paid_status sin campos para actualizar.")
             return False

        sql = f"UPDATE round_participants SET {', '.join(update_fields)} WHERE round_id = ? AND telegram_id = ?"
        update_values.extend([round_id, telegram_id])

        cursor.execute(sql, tuple(update_values))
        conn.commit()

        if cursor.rowcount > 0:
            logger.info(f"Estado de pago (simulado={paid_simulated}, real={paid_real}) actualizado para participante {telegram_id} en ronda {round_id}.")
            return True
        else:
            logger.warning(f"No se encontró participante {telegram_id} en ronda {round_id} para actualizar pago.")
            return False
    except sqlite3.Error as e:
        logger.error(f"Error al actualizar estado de pago para participante {telegram_id} en ronda {round_id}: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def count_paid_participants_in_round(round_id: int, use_real_paid: bool = False) -> int:
    """
    Cuenta el número de participantes con paid_simulated = TRUE o paid_real = TRUE
    en una ronda específica. Es llamada desde payment_manager.py y bot.py (JobQueue).
    use_real_paid=True para contar pagos reales, False para pagos simulados.
    Retorna el número de participantes pagados.
    """
    conn = None
    count = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if use_real_paid:
             cursor.execute("SELECT COUNT(*) FROM round_participants WHERE round_id = ? AND paid_real = 1", (round_id,))
        else:
             cursor.execute("SELECT COUNT(*) FROM round_participants WHERE round_id = ? AND paid_simulated = 1", (round_id,))
        count = cursor.fetchone()[0]
        logger.debug(f"Contados {count} pagos {'reales simulados' if use_real_paid else 'simulados'} en ronda {round_id}.")
    except sqlite3.Error as e:
        logger.error(f"Error al contar pagos en ronda {round_id}: {e}")
    finally:
        if conn:
            conn.close()

    return count


def update_round_status(round_id: int, new_status: str) -> bool:
    """
    Actualiza el estado de una ronda en la base de datos.
    Si el estado es 'finished' o 'cancelled', también establece la hora de fin.
    Retorna True si se actualizó, False si no se encontró o hubo error.
    Es llamada desde round_manager.py.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if new_status in ['finished', 'cancelled']:
             cursor.execute(
                "UPDATE rounds SET status = ?, end_time = ? WHERE id = ?",
                (new_status, current_time, round_id)
             )
        else:
            cursor.execute(
                "UPDATE rounds SET status = ? WHERE id = ?",
                (new_status, round_id)
            )

        conn.commit()

        if cursor.rowcount > 0:
            logger.info(f"Estado de ronda {round_id} actualizado a '{new_status}'.")
            return True
        else:
            logger.warning(f"No se encontró ronda con ID {round_id} para actualizar estado.")
            return False
    except sqlite3.Error as e:
        logger.error(f"Error al actualizar estado de ronda {round_id} a '{new_status}': {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def mark_round_as_deleted(round_id: int) -> bool:
    """
    Marca una ronda como eliminada lógicamente en la base de datos.
    Retorna True si se marcó, False si no se encontró o hubo error.
    Es llamada desde round_manager.py.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE rounds SET deleted = 1 WHERE id = ?",
            (round_id,)
        )
        conn.commit()

        if cursor.rowcount > 0:
            logger.info(f"Ronda {round_id} marcada como eliminada.")
            return True
        else:
            logger.warning(f"No se encontró ronda con ID {round_id} para marcar como eliminada.")
            return False
    except sqlite3.Error as e:
        logger.error(f"Error al marcar ronda {round_id} como eliminada: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def save_draw_results(round_id: int, results_list: list[dict]) -> bool:
    """
    Guarda los resultados del sorteo para una ronda en la tabla draw_results.
    results_list es una lista de diccionarios como:
    {'drawn_number': int, 'draw_order': int, 'winner_telegram_id': str | None,
     'prize_amount_simulated': str, 'prize_amount_real': float | None}
    Es llamada desde payment_manager.py.
    Retorna True si se guardó, False si hubo error.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # La restricción UNIQUE(round_id, draw_order) en la tabla draw_results ayudará con esto.

        data_to_insert = []
        for r in results_list:
             data_to_insert.append((
                 round_id,
                 r.get('drawn_number'),
                 r.get('draw_order'),
                 r.get('winner_telegram_id'),
                 r.get('prize_amount_simulated'),
                 r.get('prize_amount_real')
             ))


        cursor.executemany(
            """
            INSERT INTO draw_results (
                round_id, drawn_number, draw_order, winner_telegram_id,
                prize_amount_simulated, prize_amount_real
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            data_to_insert
        )
        conn.commit()
        logger.info(f"Resultados del sorteo guardados para ronda {round_id}.")
        return True
    except sqlite3.IntegrityError as e:
         logger.warning(f"Integrity Error al guardar resultados del sorteo para ronda {round_id}: {e}")
         if conn: conn.rollback()
         return False
    except sqlite3.Error as e:
        logger.error(f"Error al guardar resultados del sorteo para ronda {round_id}: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


# save_creator_commission ahora es llamada con un cursor desde payment_manager
def save_creator_commission(cursor, round_id: int, creator_type: str, creator_telegram_id: str | None, amount_simulated: str, amount_real: float | None, transaction_id: str | None = None) -> bool:
    """
    Guarda el registro de la comisión para una ronda usando un cursor proporcionado.
    No gestiona la conexión ni el commit/rollback. Relanza IntegrityError y otros errores SQLite.
    Retorna True si la inserción se ejecutó sin errores no-IntegrityError.
    """
    try:
        # La restricción UNIQUE(round_id, creator_type) en la tabla manejará los duplicados.
        cursor.execute(
            """
            INSERT INTO creator_commission (
                round_id, creator_type, creator_telegram_id, amount_simulated, amount_real, transaction_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (round_id, creator_type, creator_telegram_id, amount_simulated, amount_real, transaction_id)
        )
        # No hacemos commit aquí.
        logger.debug(f"Inserción de comisión '{creator_type}' para ronda {round_id} ejecutada (pendiente commit).")
        return True
    except sqlite3.IntegrityError as e:
        # Capturamos IntegrityError aquí para loguear, pero la relanzamos para que el llamador gestione la transacción.
        logger.warning(f"Intento de guardar comisión duplicada (IntegrityError) para ronda {round_id}, tipo '{creator_type}'. {e}")
        raise e # Relanzar la excepción

    except sqlite3.Error as e:
        # Capturamos otros errores SQLite y relanzamos.
        logger.error(f"Error SQLite al guardar comisión para ronda {round_id}, tipo '{creator_type}': {e}")
        raise e