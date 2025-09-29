import threading
import time
import cv2
import numpy as np
import mss
from typing import Optional, Tuple, Dict, List

from utils import draw_rotated_rect


class CameraWorker:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # === Legacy (opcional) ===
        self._bbox_aabb: Optional[Tuple[int, int, int, int]] = None  # x1,y1,x2,y2
        self._bbox_obb: Optional[Tuple[float, float, float, float, float]] = None  # cx,cy,w,h,angle_deg

        # === Multi-OBB ===
        # id -> (cx, cy, w, h, angle_deg_cv, (b,g,r))
        self._obbs: Dict[int, Tuple[float, float, float, float, float, Tuple[int, int, int]]] = {}

        self._cam_index = 0
        self._last_jpeg: Optional[bytes] = None

        # meta (opcional)
        self._frame_w: Optional[int] = None
        self._frame_h: Optional[int] = None

    def start(self, cam_index: int = 0, width: int = 640, height: int = 480) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._cam_index = cam_index
            self._frame_w = None
            self._frame_h = None

        def _loop():

            cap = cv2.VideoCapture(self._cam_index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)



            # sct = mss.mss()

            # Define qué capturar: toda la pantalla principal
            # monitor = sct.monitors[1]  # 1 = monitor principal

            if not cap.isOpened():
                with self._lock:
                    self._running = False
                print("No se pudo abrir la cámara.")
                return

            while True:
                # snapshot de estado bajo lock (rápido)
                with self._lock:
                    running = self._running
                    bbox_aabb = self._bbox_aabb
                    bbox_obb = self._bbox_obb
                    obb_items = list(self._obbs.items())  # copia para iterar fuera del lock

                if not running:
                    break

                # Captura pantalla
                # shot = sct.grab(monitor)
                # frame = cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR)
                # frame = np.ascontiguousarray(frame)

                ok, frame = cap.read()
                if not ok:
                    print("No se pudo leer el frame")
                    break

                # meta de resolución real
                if self._frame_w is None:
                    h, w = frame.shape[:2]
                    with self._lock:
                        self._frame_w, self._frame_h = w, h

                # === Dibujo ===

                # 1) OBB "único" (legacy)
                if bbox_obb is not None:
                    cx, cy, bw, bh, angle_cv = bbox_obb  # ángulo ya con convención OpenCV
                    draw_rotated_rect(frame, cx, cy, bw, bh, angle_cv, (0, 255, 0), 2)
                    # debug opcional
                    cv2.circle(frame, (int(cx), int(cy)), 4, (255, 0, 255), -1)
                    cv2.putText(frame, f"ang={angle_cv:.1f}", (int(cx) + 8, int(cy) - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

                # 2) AABB "único" (legacy)
                if bbox_aabb is not None:
                    x1, y1, x2, y2 = bbox_aabb
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # 3) Multi-OBB
                for bid, (cx, cy, bw, bh, angle_cv, color_bgr) in obb_items:
                    draw_rotated_rect(frame, cx, cy, bw, bh, angle_cv, color_bgr, 2)
                    # marcador e ID
                    cv2.circle(frame, (int(cx), int(cy)), 3, (255, 255, 255), -1)
                    cv2.putText(frame, str(bid), (int(cx) + 6, int(cy) - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 2, cv2.LINE_AA)

                cv2.imshow("Preview", frame)
                # 1 ms para refrescar; si se presiona 'q' se cierra
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    with self._lock:
                        self._running = False
                    break

                ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok2:
                    with self._lock:
                        self._last_jpeg = buf.tobytes()

                time.sleep(0.015)  # ~66 FPS máx

            cap.release()

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._running = False
            # limpia todo
            self._bbox_aabb = None
            self._bbox_obb = None
            self._obbs.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._last_jpeg = None
        return True

    # === Legacy setters (compatibilidad) ===
    def set_bbox(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """AABB eje-alineado (modo clásico)."""
        with self._lock:
            self._bbox_aabb = (int(x1), int(y1), int(x2), int(y2))
            self._bbox_obb = None  # reemplaza OBB "único"

    def set_bbox_rotated(self, cx: float, cy: float, w: float, h: float, angle_deg_cv: float) -> None:
        """OBB rotado (centro, ancho, alto, ángulo en grados OpenCV)."""
        with self._lock:
            self._bbox_obb = (float(cx), float(cy), float(w), float(h), float(angle_deg_cv))
            self._bbox_aabb = None  # reemplaza AABB "único"

    def clear_bbox(self) -> None:
        with self._lock:
            self._bbox_aabb = None
            self._bbox_obb = None

    # === Multi-OBB API ===
    def upsert_bbox_rotated(
        self,
        bbox_id: int,
        cx: float,
        cy: float,
        w: float,
        h: float,
        angle_deg_cv: float,
        color_bgr: Tuple[int, int, int] = (0, 255, 0),
    ) -> None:
        """Crea o actualiza un OBB con id."""
        with self._lock:
            self._obbs[int(bbox_id)] = (float(cx), float(cy), float(w), float(h), float(angle_deg_cv), tuple(map(int, color_bgr)))

    def remove_bbox(self, bbox_id: int) -> bool:
        with self._lock:
            return self._obbs.pop(int(bbox_id), None) is not None

    def clear_bboxes(self) -> None:
        with self._lock:
            self._obbs.clear()

    def set_bboxes(self, items: List[Tuple[int, float, float, float, float, float, Tuple[int, int, int]]]) -> None:
        """
        Reemplaza todas las cajas por las dadas.
        items: lista de tuplas (id, cx, cy, w, h, angle_deg_cv, color_bgr)
        """
        with self._lock:
            self._obbs.clear()
            for it in items:
                if len(it) == 7:
                    bid, cx, cy, w, h, ang, col = it
                else:
                    # si no trae color, usa verde
                    bid, cx, cy, w, h, ang = it
                    col = (0, 255, 0)
                self._obbs[int(bid)] = (float(cx), float(cy), float(w), float(h), float(ang), tuple(map(int, col)))

    def get_bboxes(self) -> List[dict]:
        """Devuelve snapshot de OBBs (útil para /meta o debugging)."""
        with self._lock:
            out = []
            for bid, (cx, cy, w, h, ang, col) in self._obbs.items():
                out.append({
                    "id": int(bid),
                    "cx": float(cx),
                    "cy": float(cy),
                    "w": float(w),
                    "h": float(h),
                    "angle_deg_cv": float(ang),
                    "color_bgr": tuple(col),
                })
            return out

    def get_last_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._last_jpeg

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def get_meta(self):
        with self._lock:
            return {
                "running": self._running,
                "frame_w": self._frame_w,
                "frame_h": self._frame_h,
                "bbox_type": (
                    "obb" if self._bbox_obb is not None else ("aabb" if self._bbox_aabb else None)
                ),
                "multi_count": len(self._obbs),
            }
