from fastapi import APIRouter

from database import get_db, rows_to_list


router = APIRouter()


@router.get("/api/bot/alertas")
def listar_alertas_bot():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.id, a.conversacion_id, a.comercio_id, c.nombre AS comercio,
                   a.motivo, a.notificada, a.notificada_at, a.creada_at
            FROM bot_alertas a
            LEFT JOIN comercios c ON c.id = a.comercio_id
            ORDER BY a.creada_at DESC
            LIMIT 200
            """
        )
        return {"alertas": rows_to_list(cursor.fetchall())}
    finally:
        conn.close()
