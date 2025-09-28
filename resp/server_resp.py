# # server.py
# from flask import Flask, request, jsonify, Response
# from camera_worker import CameraWorker
# import time
# from math import degrees
#
# app = Flask(__name__)
# worker = CameraWorker()
#
# @app.get("/status")
# def status():
#     return jsonify({"running": worker.is_running()})
#
# @app.get("/meta")
# def meta():
#     if not worker.is_running():
#         return jsonify({"running": False, "msg": "Cámara no está en ejecución"}), 400
#     return jsonify(worker.get_meta())
#
# @app.post("/start")
# def start_camera():
#     data = request.get_json(silent=True) or {}
#     cam_index = int(data.get("index", 0))
#     width = int(data.get("width", 1920))
#     height = int(data.get("height", 1080))
#     started = worker.start(cam_index, width, height)
#     if not started:
#         return jsonify({"ok": False, "msg": "La cámara ya estaba en ejecución"}), 400
#     return jsonify({"ok": True})
#
# @app.post("/stop")
# def stop_camera():
#     stopped = worker.stop()
#     if not stopped:
#         return jsonify({"ok": False, "msg": "La cámara no estaba en ejecución"}), 400
#     return jsonify({"ok": True})
#
# # === MISMO ENDPOINT, ahora acepta AABB u OBB ===
# @app.post("/bbox")
# def set_bbox():
#     if not worker.is_running():
#         return jsonify({"ok": False, "msg": "La cámara no está en ejecución"}), 400
#
#     data = request.get_json(force=True)
#
#     # --- OBB ---
#     if all(k in data for k in ("cx", "cy", "w", "h")) and any(k in data for k in ("angle_deg","angle","angle_rad")):
#         cx = float(data["cx"]); cy = float(data["cy"])
#         w  = float(data["w"]);  h  = float(data["h"])
#
#         if "angle_deg" in data:
#             ang_screen = float(data["angle_deg"])
#         elif "angle_rad" in data:
#             ang_screen = float(data["angle_rad"]) * 180.0 / 3.141592653589793
#         else:
#             ang_screen = float(data["angle"])  # asumimos grados
#
#         # # pantalla -> OpenCV: invertir signo UNA SOLA VEZ
#         # ang_cv = -ang_screen
#
#         worker.set_bbox_rotated(cx, cy, w, h, ang_screen)
#         return jsonify({"ok": True, "type": "obb", "bbox": {"cx": cx, "cy": cy, "w": w, "h": h, "angle_deg_cv": ang_screen}})
#
#     # --- AABB ---
#     if all(k in data for k in ("x1","y1","x2","y2")):
#         x1 = int(data["x1"]); y1 = int(data["y1"])
#         x2 = int(data["x2"]); y2 = int(data["y2"])
#         worker.set_bbox(x1, y1, x2, y2)
#         return jsonify({"ok": True, "type":"aabb"})
#
#     return jsonify({"ok": False, "msg": "Faltan parámetros"}), 400
#
# @app.delete("/bbox")
# def clear_bbox():
#     if not worker.is_running():
#         return jsonify({"ok": False, "msg": "La cámara no está en ejecución"}), 400
#     worker.clear_bbox()
#     return jsonify({"ok": True})
#
# @app.get("/snapshot.jpg")
# def snapshot():
#     if not worker.is_running():
#         return jsonify({"ok": False, "msg": "Cámara no está en ejecución"}), 400
#     jpeg = worker.get_last_jpeg()
#     if not jpeg:
#         return jsonify({"ok": False, "msg": "Aún no hay frame"}), 503
#     headers = {
#         "Cache-Control": "no-cache, no-store, must-revalidate",
#         "Pragma": "no-cache",
#         "Expires": "0",
#     }
#     return Response(jpeg, mimetype="image/jpeg", headers=headers)
#
# @app.get("/stream.mjpg")
# def stream_mjpeg():
#     if not worker.is_running():
#         return jsonify({"ok": False, "msg": "Cámara no está en ejecución"}), 400
#
#     def gen():
#         boundary = "--frame"
#         while worker.is_running():
#             jpeg = worker.get_last_jpeg()
#             if jpeg:
#                 yield (
#                     f"{boundary}\r\n"
#                     "Content-Type: image/jpeg\r\n"
#                     f"Content-Length: {len(jpeg)}\r\n\r\n"
#                 ).encode("utf-8") + jpeg + b"\r\n"
#             time.sleep(0.03)
#         yield b"--frame--\r\n"
#
#     headers = {
#         "Cache-Control": "no-cache, no-store, must-revalidate",
#         "Pragma": "no-cache",
#         "Expires": "0",
#         "Connection": "close",
#     }
#     return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame", headers=headers)
