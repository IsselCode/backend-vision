from flask import Flask, request, jsonify, Response
from camera_worker import CameraWorker
import time
from typing import Tuple, List, Any
from werkzeug.exceptions import BadRequest
from db_service import DatabaseService

db = DatabaseService("app.db")
db.init_db()

app = Flask(__name__)
worker = CameraWorker()

# ─────────────────────────────────────────────────────────────────────────────
# Helpers: parseo de ángulo y color
# ─────────────────────────────────────────────────────────────────────────────

def _parse_angle_deg(d: dict) -> float:
    """
    Acepta: angle_deg (pantalla), angle_rad (pantalla), angle (asumimos grados).
    En tu pipeline actual ya mandas ángulo que funciona 1:1 con OpenCV (draw_rotated_rect).
    Si algún día inviertes signo, hazlo aquí UNA sola vez.
    """
    if "angle_deg" in d:
        return float(d["angle_deg"])
    if "angle_rad" in d:
        return float(d["angle_rad"]) * 180.0 / 3.141592653589793
    if "angle" in d:
        return float(d["angle"])  # asumimos grados
    raise KeyError("angle_deg/angle_rad/angle faltante")

def _parse_color_bgr(d: dict) -> Tuple[int, int, int]:
    """
    Acepta varias formas:
      - color_bgr: [b,g,r]
      - color_rgb: [r,g,b]
      - color_hex: '#RRGGBB' o 'RRGGBB'
    Si no viene nada: verde (0,255,0)
    """
    if "color_bgr" in d:
        b, g, r = d["color_bgr"]
        return int(b), int(g), int(r)

    if "color_rgb" in d:
        r, g, b = d["color_rgb"]
        return int(b), int(g), int(r)

    if "color_hex" in d:
        hx = str(d["color_hex"]).lstrip("#")
        if len(hx) == 6:
            r = int(hx[0:2], 16)
            g = int(hx[2:4], 16)
            b = int(hx[4:6], 16)
            return b, g, r

    return (0, 255, 0)

def _color_hex_from_input(d: dict) -> str:
    # prioridad: color_hex -> color_rgb -> color_bgr -> default
    if "color_hex" in d and isinstance(d["color_hex"], str):
        hx = d["color_hex"].lstrip("#")
        if len(hx) == 6:
            return f"#{hx.upper()}"
    if "color_rgb" in d and isinstance(d["color_rgb"], (list, tuple)) and len(d["color_rgb"]) == 3:
        r, g, b = [int(x) & 255 for x in d["color_rgb"]]
        return f"#{r:02X}{g:02X}{b:02X}"
    if "color_bgr" in d and isinstance(d["color_bgr"], (list, tuple)) and len(d["color_bgr"]) == 3:
        b, g, r = [int(x) & 255 for x in d["color_bgr"]]
        return f"#{r:02X}{g:02X}{b:02X}"
    return "#00FF00"

# ─────────────────────────────────────────────────────────────────────────────
# Básicos / cámara
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/status")
def status():
    return jsonify({"running": worker.is_running()})

@app.get("/meta")
def meta():
    if not worker.is_running():
        return jsonify({"running": False, "msg": "Cámara no está en ejecución"}), 400
    return jsonify(worker.get_meta())

@app.post("/start")
def start_camera():
    data = request.get_json(silent=True) or {}
    cam_index = int(data.get("index", 0))
    width = int(data.get("width", 1920))
    height = int(data.get("height", 1080))
    started = worker.start(cam_index, width, height)
    if not started:
        return jsonify({"ok": False, "msg": "La cámara ya estaba en ejecución"}), 400
    return jsonify({"ok": True})

@app.post("/stop")
def stop_camera():
    stopped = worker.stop()
    if not stopped:
        return jsonify({"ok": False, "msg": "La cámara no estaba en ejecución"}), 400
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────────────────────
# CRUD múltiple por id
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/bbox")
def upsert_bbox():
    if not worker.is_running():
        return jsonify({"ok": False, "msg": "La cámara no está en ejecución"}), 400

    data = request.get_json(force=True) or {}

    required = ("id", "cx", "cy", "w", "h")
    if not all(k in data for k in required) or not any(k in data for k in ("angle_deg","angle","angle_rad")):
        return jsonify({"ok": False, "msg": f"Faltan campos: {required} + angle_*"}), 400

    try:
        # 1) Parseo y validaciones mínimas
        bid = int(data["id"])
        cx = float(data["cx"]); cy = float(data["cy"])
        w  = float(data["w"]);  h  = float(data["h"])
        if w <= 0 or h <= 0:
            return jsonify({"ok": False, "msg": "w y h deben ser > 0"}), 400

        ang_cv   = _parse_angle_deg(data)          # en grados (convención OpenCV que ya usas)
        colorHex = _color_hex_from_input(data)     # para DB
        colorBGR = _parse_color_bgr(data)          # para dibujar

        # 2) Dibujo en vivo
        worker.upsert_bbox_rotated(bid, cx, cy, w, h, ang_cv, colorBGR)

        # 3) Persistencia
        db.upsert_bbox(
            id=bid, cx=cx, cy=cy, w=w, h=h,
            angle_deg_cv=ang_cv, color_hex=colorHex
        )

        return jsonify({
            "ok": True,
            "id": bid,
            "saved": {
                "cx": cx, "cy": cy, "w": w, "h": h,
                "angle_deg_cv": ang_cv,
                "color_hex": colorHex
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error al guardar bbox: {e}"}), 500

@app.patch("/bbox/<int:bid>")
def patch_bbox(bid: int):
    # 1) JSON válido
    try:
        data = request.get_json(silent=False)
    except BadRequest:
        return jsonify({"ok": False, "msg": "JSON inválido o Content-Type incorrecto"}), 400
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "Cuerpo JSON debe ser un objeto"}), 400

    # 2) Cargar estado actual DESDE DB (fuente de verdad para PATCH)
    cur = db.get_bbox(bid)
    if cur is None:
        return jsonify({"ok": False, "msg": f"id {bid} no existe"}), 404

    # 3) Merge parcial + validaciones mínimas
    try:
        cx = float(data.get("cx", cur["cx"]))
        cy = float(data.get("cy", cur["cy"]))
        w  = float(data.get("w",  cur["w"]))
        h  = float(data.get("h",  cur["h"]))
        if w <= 0 or h <= 0:
            return jsonify({"ok": False, "msg": "w y h deben ser > 0"}), 400

        if any(k in data for k in ("angle_deg","angle","angle_rad")):
            ang_cv = _parse_angle_deg(data)
        else:
            ang_cv = float(cur["angle_deg_cv"])

        # Color: si se envía algo, normaliza a hex+bgr; si no, usa el actual
        if any(k in data for k in ("color_hex","color_rgb","color_bgr")):
            color_hex = _color_hex_from_input(data)
            color_bgr = _parse_color_bgr(data)
        else:
            color_hex = cur["color_hex"]
            # derivar BGR desde el hex actual
            color_bgr = _parse_color_bgr({"color_hex": color_hex})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Payload inválido: {e}"}), 400

    # 4) Persistencia en DB
    try:
        db.update_bbox(
            bid,
            cx=cx, cy=cy, w=w, h=h,
            angle_deg_cv=ang_cv,
            color_hex=color_hex
        )
    except Exception as e:
        app.logger.exception("Error al actualizar DB")
        return jsonify({"ok": False, "msg": f"Error DB: {e}"}), 500

    # 5) Actualizar worker (best-effort)
    worker_updated = False
    if worker.is_running():
        try:
            worker.upsert_bbox_rotated(bid, cx, cy, w, h, ang_cv, color_bgr)
            worker_updated = True
        except Exception:
            app.logger.exception("Error al actualizar worker")

    # 6) Respuesta
    return jsonify({
        "ok": True,
        "id": bid,
        "updated": {
            "cx": cx, "cy": cy, "w": w, "h": h,
            "angle_deg_cv": ang_cv,
            "color_hex": color_hex
        },
        "worker_updated": worker_updated
    }), 200

@app.delete("/bbox/<int:bid>")
def delete_bbox(bid: int):
    # 1) Quitar del worker si está corriendo (best-effort)
    removed_worker = False
    if worker.is_running():
        try:
            removed_worker = worker.remove_bbox(bid)
        except Exception as e:
            app.logger.exception("Error al eliminar en worker")

    # 2) Quitar de la base (si no existe, devuelve False)
    try:
        removed_db = db.delete_bbox(bid)
    except Exception as e:
        app.logger.exception("Error al eliminar en DB")
        return jsonify({"ok": False, "msg": f"Error DB: {e}"}), 500

    # 3) Si no estaba ni en worker ni en DB -> 404
    if not removed_worker and not removed_db:
        return jsonify({"ok": False, "msg": f"id {bid} no existe"}), 404

    # 4) OK: informa qué se eliminó
    return jsonify({
        "ok": True,
        "id": bid,
        "removed": {
            "worker": removed_worker,
            "db": removed_db
        }
    }), 200

# ─────────────────────────────────────────────────────────────────────────────
# Operaciones sobre el conjunto completo
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/bboxes")
def get_bboxes():
    """
    Devuelve bounding boxes.
    - ?source=db     (default): desde la base de datos (persistente)
    - ?source=worker          : los que el worker está dibujando ahora (si corre)
    - ?source=both            : ambos (útil para comparar)
    """
    src = (request.args.get("source") or "db").lower()

    if src == "worker":
        running = worker.is_running()
        items = worker.get_bboxes() if running else []
        return jsonify({
            "ok": True,
            "source": "worker",
            "running": running,
            "items": items,  # [{"id", "cx","cy","w","h","angle_deg_cv","color_bgr"}]
        })

    if src == "both":
        running = worker.is_running()
        wk = worker.get_bboxes() if running else []
        # Mapeo filas de DB al contrato de API
        db_rows = db.get_all_bboxes()
        db_items = [{
            "id": int(r["id"]),
            "cx": float(r["cx"]),
            "cy": float(r["cy"]),
            "w":  float(r["w"]),
            "h":  float(r["h"]),
            "angle_deg": float(r["angle_deg_cv"]),  # guardas mismo convenio
            "color_hex": r["color_hex"],
            "created_at": r["created_at"],
        } for r in db_rows]
        return jsonify({
            "ok": True,
            "source": "both",
            "running": running,
            "db_items": db_items,
            "worker_items": wk,
        })

    # default: DB
    rows = db.get_all_bboxes()
    items = [{
        "id": int(r["id"]),
        "cx": float(r["cx"]),
        "cy": float(r["cy"]),
        "w":  float(r["w"]),
        "h":  float(r["h"]),
        "angle_deg": float(r["angle_deg_cv"]),
        "color_hex": r["color_hex"],
        "created_at": r["created_at"],
    } for r in rows]
    return jsonify({"ok": True, "source": "db", "items": items})

@app.put("/bboxes")
def put_bboxes():
    """
    Reemplaza TODO el set por la lista dada.
    Body esperado (lista):
      [
        {"id": 1, "cx":..., "cy":..., "w":..., "h":..., "angle_deg":..., "color_rgb":[r,g,b]},
        ...
      ]
    """
    if not worker.is_running():
        return jsonify({"ok": False, "msg": "Cámara no está en ejecución"}), 400

    items_json: List[dict] = request.get_json(force=True)
    items_py: List[Any] = []
    for d in items_json:
        bid = int(d["id"])
        cx = float(d["cx"]); cy = float(d["cy"])
        w  = float(d["w"]);  h  = float(d["h"])
        ang_cv = _parse_angle_deg(d)
        col = _parse_color_bgr(d)
        items_py.append((bid, cx, cy, w, h, ang_cv, col))

    worker.set_bboxes(items_py)
    return jsonify({"ok": True, "count": len(items_py)})

@app.delete("/bboxes")
def clear_bboxes():
    if not worker.is_running():
        return jsonify({"ok": False, "msg": "Cámara no está en ejecución"}), 400
    worker.clear_bboxes()
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────────────────────
# Imagen / stream
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/snapshot.jpg")
def snapshot():
    if not worker.is_running():
        return jsonify({"ok": False, "msg": "Cámara no está en ejecución"}), 400
    jpeg = worker.get_last_jpeg()
    if not jpeg:
        return jsonify({"ok": False, "msg": "Aún no hay frame"}), 503
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return Response(jpeg, mimetype="image/jpeg", headers=headers)

@app.get("/stream.mjpg")
def stream_mjpeg():
    if not worker.is_running():
        return jsonify({"ok": False, "msg": "Cámara no está en ejecución"}), 400

    def gen():
        boundary = "--frame"
        while worker.is_running():
            jpeg = worker.get_last_jpeg()
            if jpeg:
                yield (
                    f"{boundary}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode("utf-8") + jpeg + b"\r\n"
            time.sleep(0.03)
        yield b"--frame--\r\n"

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "close",
    }
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame", headers=headers)

# ─────────────────────────────────────────────────────────────────────────────
# Opcional: CORS (si accederás desde otra app/puerto)
# from flask_cors import CORS
# CORS(app, resources={r"/*": {"origins": "*"}})
# ─────────────────────────────────────────────────────────────────────────────
