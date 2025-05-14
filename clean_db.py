import sqlite3
import logging
import os

# Configurar logging para ver qué hace el script
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DATABASE_NAME = 'bot_data.db'

def clean_database():
    """
    Elimina todos los datos de las tablas de juego (rondas, participantes, resultados, comisiones).
    Mantiene la tabla de usuarios.
    """
    conn = None
    try:
        # Verificar si el archivo de base de datos existe
        if not os.path.exists(DATABASE_NAME):
            logger.warning(f"El archivo de base de datos '{DATABASE_NAME}' no existe. No hay nada que limpiar.")
            return

        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        logger.info(f"Conectado a la base de datos '{DATABASE_NAME}'. Iniciando limpieza...")

        # Desactivar temporalmente las restricciones de clave externa para facilitar la eliminación
        # Esto es útil si no borramos en el orden correcto, pero intentar borrar en orden es mejor.
        # cursor.execute("PRAGMA foreign_keys = OFF;")

        # Eliminar datos en el orden correcto para evitar problemas con claves externas:
        # 1. Comisiones (depende de rondas)
        # 2. Resultados del sorteo (depende de rondas y usuarios)
        # 3. Participantes de ronda (depende de rondas y usuarios)
        # 4. Rondas

        logger.info("Eliminando datos de 'creator_commission'...")
        cursor.execute("DELETE FROM creator_commission")
        logger.info("Datos de 'creator_commission' eliminados.")

        logger.info("Eliminando datos de 'draw_results'...")
        cursor.execute("DELETE FROM draw_results")
        logger.info("Datos de 'draw_results' eliminados.")

        logger.info("Eliminando datos de 'round_participants'...")
        cursor.execute("DELETE FROM round_participants")
        logger.info("Datos de 'round_participants' eliminados.")

        logger.info("Eliminando datos de 'rounds'...")
        cursor.execute("DELETE FROM rounds")
        logger.info("Datos de 'rounds' eliminados.")

        # Opcional: Si quisieras eliminar usuarios también, descomenta la siguiente línea
        # logger.info("Eliminando datos de 'users'...")
        # cursor.execute("DELETE FROM users")
        # logger.info("Datos de 'users' eliminados.")


        # Reactivar restricciones de clave externa
        # cursor.execute("PRAGMA foreign_keys = ON;")

        conn.commit()
        logger.info("Limpieza de base de datos completada. Todas las rondas, participantes, resultados y comisiones han sido eliminados.")

    except sqlite3.Error as e:
        logger.error(f"Error durante la limpieza de la base de datos: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    clean_database()