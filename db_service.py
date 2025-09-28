import os
import sqlite3
from typing import Optional, Dict, Any, List, Iterable

class DatabaseService:
    def __init__(self, db_path: str = "app.db"):
        self.db_path = db_path

    # Conexión por operación (thread-safe a nivel de proceso/Flask)
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Crea la tabla y activa WAL para mejor concurrencia."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True) if os.path.dirname(self.db_path) else None
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bboxes (
                    id INTEGER PRIMARY KEY,              -- viene de Flutter
                    cx REAL NOT NULL,
                    cy REAL NOT NULL,
                    w  REAL NOT NULL,
                    h  REAL NOT NULL,
                    angle_deg_cv REAL NOT NULL,         -- ángulo en grados (convención OpenCV)
                    color_hex TEXT NOT NULL DEFAULT '#00FF00',
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)  -- UTC
                );
            """)
            # Modo WAL: mejor para múltiples hilos/lecturas concurrentes
            cur.execute("PRAGMA journal_mode=WAL;")
            conn.commit()

    # -----------------------------
    # CRUD
    # -----------------------------

    def create_bbox(self, *, id: int, cx: float, cy: float, w: float, h: float, angle_deg_cv: float, color_hex: str = "#00FF00") -> None:
        """Crea una fila nueva. Falla si el id ya existe."""
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO bboxes (id, cx, cy, w, h, angle_deg_cv, color_hex)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (int(id), float(cx), float(cy), float(w), float(h), float(angle_deg_cv), str(color_hex)))
                conn.commit()
            except sqlite3.IntegrityError as e:
                # id duplicado u otra restricción
                raise ValueError(f"bbox id={id} ya existe") from e

    def get_bbox(self, id: int) -> Optional[Dict[str, Any]]:
        """Obtiene una fila por id (o None si no existe)."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bboxes WHERE id = ?", (int(id),))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_bboxes(self) -> List[Dict[str, Any]]:
        """Lista todas las filas (más recientes primero por created_at)."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bboxes ORDER BY datetime(created_at) DESC, id DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def update_bbox(self, id: int, **fields: Any) -> bool:
        """
        Actualiza PARCIALMENTE una fila por id.
        Campos permitidos: cx, cy, w, h, angle_deg_cv, color_hex
        Devuelve True si actualizó, False si no existe.
        """
        allowed = {"cx", "cy", "w", "h", "angle_deg_cv", "color_hex"}
        to_set = {k: v for k, v in fields.items() if k in allowed}
        if not to_set:
            return False

        sets = ", ".join(f"{k} = ?" for k in to_set.keys())
        params = list(to_set.values()) + [int(id)]

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE bboxes SET {sets} WHERE id = ?", params)
            conn.commit()
            return cur.rowcount > 0

    def delete_bbox(self, id: int) -> bool:
        """Elimina una fila por id. True si eliminó, False si no existía."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM bboxes WHERE id = ?", (int(id),))
            conn.commit()
            return cur.rowcount > 0

    # -----------------------------
    # Opcional: UPSERT (crea si no existe, actualiza si existe)
    # -----------------------------

    def upsert_bbox(self, *,
                    id: int,
                    cx: float, cy: float,
                    w: float, h: float,
                    angle_deg_cv: float,
                    color_hex: str = "#00FF00") -> None:
        """Crea o actualiza la fila con ese id (atómico)."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO bboxes (id, cx, cy, w, h, angle_deg_cv, color_hex)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    cx=excluded.cx,
                    cy=excluded.cy,
                    w=excluded.w,
                    h=excluded.h,
                    angle_deg_cv=excluded.angle_deg_cv,
                    color_hex=excluded.color_hex
            """, (int(id), float(cx), float(cy), float(w), float(h), float(angle_deg_cv), str(color_hex)))
            conn.commit()
