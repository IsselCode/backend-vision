import threading
import time
import cv2
import mss
from typing import Optional, Tuple, Dict, List, Union

from utils import draw_rotated_rect

def _video_backends():
    # En Windows suele ir mejor DSHOW y MSMF. En Linux/macOS usa el default.
    backends = []
    try:
        import platform
        if platform.system() == "Windows":
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, 0]
        else:
            backends = [0]  # default (v4l2 en Linux, AVFoundation en macOS)
    except:
        backends = [0]
    return backends

def _try_set_res(cap, w, h, fourcc: Optional[str]) -> bool:
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    # warmup
    for _ in range(3):
        cap.read()
    ok, frame = cap.read()
    if not ok:
        return False
    hh, ww = frame.shape[:2]
    return (ww == w and hh == h)

def _negotiate_resolution(cap) -> Tuple[int, int]:
    # Lista de resoluciones UVC comunes (mayor→menor). Añade más si tu cámara las soporta.
    candidates = [
        (3840,2160), (2560,1440), (2592,1944),  # 4K / QHD / 5MP 4:3
        (1920,1080), (1600,1200),
        (1280,1024), (1280,720),
        (1024,768),  (800,600),
        (640,480)
    ]
    # FOURCC por orden de probabilidad para altas resoluciones
    fourccs = ["MJPG", "YUY2", None]  # None = backend default (p.ej. H264/YUY2)

    # 1) prueba cada fourcc con resoluciones de mayor a menor
    for fcc in fourccs:
        for (w, h) in candidates:
            if _try_set_res(cap, w, h, fcc):
                return w, h

    # 2) último recurso: lo que venga
    ok, frame = cap.read()
    if ok:
        hh, ww = frame.shape[:2]
        return ww, hh
    return 640, 480

class CameraWorker:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # id -> (cx, cy, w, h, angle_deg_cv, (b,g,r))
        self._obbs: Dict[int, Tuple[float, float, float, float, float, Tuple[int, int, int]]] = {}

        self._cam_index = 0
        self._last_jpeg: Optional[bytes] = None

        # meta (opcional)
        self._frame_w: Optional[int] = None
        self._frame_h: Optional[int] = None

    def start(self, cam_index: int = 0) -> Union[tuple[bool, Optional[int], Optional[int]], None, tuple[bool, None, None], tuple[bool, int, int]]:
        with self._lock:
            if self._running:
                return False, self._frame_w, self._frame_h
            self._running = True
            self._cam_index = cam_index
            self._frame_w = None
            self._frame_h = None

        # Define qué capturar: toda la pantalla principal
        # sct = mss.mss()
        # monitor = sct.monitors[1]  # 1 = monitor principal

        # cap = cv2.VideoCapture(self._cam_index)
        # if not cap.isOpened():
        #     with self._lock:
        #         self._running = False
        #     print("No se pudo abrir la cámara.")
        #     return

        # for _ in range(3):
        #     cap.read()

        # Captura pantalla

        # shot = sct.grab(monitor)
        # frame = cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR)
        # frame = np.ascontiguousarray(frame)

        # ok, frame = cap.read()
        # if not ok:
        #     cap.release()
        #     with self._lock:
        #         self._running = False
        #     print("No se pudo leer el frame")
        #     return False, None, None

        # h, w = frame.shape[:2]
        # ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        # with self._lock:
        #     self._frame_w, self._frame_h = int(w), int(h)
        #     if ok2:
        #         self._last_jpeg = buf.tobytes()

        # --- abrir con el mejor backend disponible
        cap = None
        for backend in _video_backends():
            cap = cv2.VideoCapture(self._cam_index, backend) if backend != 0 else cv2.VideoCapture(self._cam_index)
            if cap.isOpened():
                break
        if cap is None or not cap.isOpened():
            with self._lock:
                self._running = False
            print("No se pudo abrir la cámara.")
            return False, None, None

        # --- negociar mejor resolución disponible y confirmar con frame real
        w, h = _negotiate_resolution(cap)
        ok, frame = cap.read()
        if not ok:
            cap.release()
            with self._lock:
                self._running = False
            print("No se pudo leer el primer frame.")
            return False, None, None

        hh, ww = frame.shape[:2]
        ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self._lock:
            self._frame_w, self._frame_h = int(ww), int(hh)
            if ok2:
                self._last_jpeg = buf.tobytes()

        def _loop(existing_cap):

            cap_local = existing_cap

            try:
                while True:
                    with self._lock:
                        running = self._running
                        obb_items = list(self._obbs.items())  # copia para iterar fuera del lock
                    if not running:
                        break

                    ok, frame = cap_local.read()
                    if not ok:
                        print("No se pudo leer el frame")
                        break

                    # === Dibujo ===
                    for bid, (cx, cy, bw, bh, angle_cv, color_bgr) in obb_items:
                        draw_rotated_rect(frame, cx, cy, bw, bh, angle_cv, color_bgr, 2)
                        # marcador e ID
                        cv2.circle(frame, (int(cx), int(cy)), 3, (255, 255, 255), -1)
                        cv2.putText(frame, str(bid), (int(cx) + 6, int(cy) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 2, cv2.LINE_AA)

                    # Mostrar UI de OpenCv
                    # 1 ms para refrescar; si se presiona 'q' se cierra
                    cv2.imshow("Preview", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        with self._lock:
                            self._running = False
                        break

                    ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok2:
                        with self._lock:
                            self._last_jpeg = buf.tobytes()
                    time.sleep(0.015)  # ~66 FPS máx
            finally:
                cap_local.release()
                try:
                    cv2.destroyAllWindows()
                except:
                    pass

            cap.release()

        self._thread = threading.Thread(target=_loop, args=(cap,), daemon=True)
        self._thread.start()
        return True, self._frame_w, self._frame_h

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._running = False
            # limpia todo
            self._obbs.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._last_jpeg = None
        return True

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
                "multi_count": len(self._obbs),
                "bbox_ids": list(self._obbs.keys())
            }
