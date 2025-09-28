# # camera_worker.py
# import threading
# import time
# import cv2
# import numpy as np
# from typing import Optional, Tuple
#
# from utils import draw_rotated_rect
#
#
# class CameraWorker:
#     def __init__(self):
#         self._thread: Optional[threading.Thread] = None
#         self._running = False
#         self._lock = threading.Lock()
#
#         # BBoxes
#         self._bbox_aabb: Optional[Tuple[int, int, int, int]] = None  # x1,y1,x2,y2
#         self._bbox_obb: Optional[Tuple[float, float, float, float, float]] = None  # cx,cy,w,h,angle_deg
#
#
#         self._cam_index = 0
#         self._last_jpeg: Optional[bytes] = None
#
#         # meta (opcional)
#         self._frame_w: Optional[int] = None
#         self._frame_h: Optional[int] = None
#
#     def start(self, cam_index: int = 0, width: int = 640, height: int = 480) -> bool:
#         with self._lock:
#             if self._running:
#                 return False
#             self._running = True
#             self._cam_index = cam_index
#             self._frame_w = None
#             self._frame_h = None
#
#         def _loop():
#             cap = cv2.VideoCapture(self._cam_index)
#             # cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # útil p/DroidCam
#             cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
#             cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
#
#             if not cap.isOpened():
#                 with self._lock:
#                     self._running = False
#                 print("No se pudo abrir la cámara.")
#                 return
#
#             while True:
#                 with self._lock:
#                     running = self._running
#                     bbox_aabb = self._bbox_aabb
#                     bbox_obb  = self._bbox_obb
#
#                 if not running:
#                     break
#
#                 ok, frame = cap.read()
#                 if not ok:
#                     print("No se pudo leer el frame")
#                     break
#
#                 # meta de resolución real
#                 if self._frame_w is None:
#                     h, w = frame.shape[:2]
#                     with self._lock:
#                         self._frame_w, self._frame_h = w, h
#
#                 # Dibujo del bbox OBB (prioridad) o AABB
#                 # dentro del loop en camera_worker.py
#                 if bbox_obb is not None:
#                     cx, cy, bw, bh, angle_cv = bbox_obb  # angle_cv ya debe venir listo para OpenCV
#                     draw_rotated_rect(frame, cx, cy, bw, bh, angle_cv, (0, 255, 0), 2)
#                     # debug visual opcional
#                     cv2.circle(frame, (int(cx), int(cy)), 4, (255, 0, 255), -1)
#                     cv2.putText(frame, f"ang={angle_cv:.1f}", (int(cx) + 8, int(cy) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
#                 elif bbox_aabb is not None:
#                     x1, y1, x2, y2 = bbox_aabb
#                     cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
#
#                 ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
#                 if ok2:
#                     with self._lock:
#                         self._last_jpeg = buf.tobytes()
#
#                 time.sleep(0.015)  # ~66 FPS máx
#
#             cap.release()
#
#         self._thread = threading.Thread(target=_loop, daemon=True)
#         self._thread.start()
#         return True
#
#     def stop(self) -> bool:
#         with self._lock:
#             if not self._running:
#                 return False
#             self._running = False
#             self._bbox_aabb = None
#             self._bbox_obb = None
#         if self._thread and self._thread.is_alive():
#             self._thread.join(timeout=3.0)
#         self._thread = None
#         self._last_jpeg = None
#         return True
#
#     # === Setters de bbox ===
#     def set_bbox(self, x1: int, y1: int, x2: int, y2: int) -> None:
#         """AABB eje-alineado (modo clásico)."""
#         with self._lock:
#             self._bbox_aabb = (int(x1), int(y1), int(x2), int(y2))
#             self._bbox_obb = None  # reemplaza OBB
#
#     def set_bbox_rotated(self, cx: float, cy: float, w: float, h: float, angle_deg: float) -> None:
#         """OBB rotado (center, width, height, angle en grados)."""
#         with self._lock:
#             self._bbox_obb = (float(cx), float(cy), float(w), float(h), float(angle_deg))
#             self._bbox_aabb = None  # reemplaza AABB
#
#     def clear_bbox(self) -> None:
#         with self._lock:
#             self._bbox_aabb = None
#             self._bbox_obb = None
#
#     def get_last_jpeg(self) -> Optional[bytes]:
#         with self._lock:
#             return self._last_jpeg
#
#     def is_running(self) -> bool:
#         with self._lock:
#             return self._running
#
#     def get_meta(self):
#         with self._lock:
#             return {
#                 "running": self._running,
#                 "frame_w": self._frame_w,
#                 "frame_h": self._frame_h,
#                 "bbox_type": "obb" if self._bbox_obb is not None else ("aabb" if self._bbox_aabb else None)
#             }
