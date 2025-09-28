import cv2
import numpy as np

def draw_rotated_rect(frame, cx, cy, w, h, angle_deg, color=(0,255,0), thickness=2):
    rect = ((float(cx), float(cy)), (float(w), float(h)), float(angle_deg))
    box = cv2.boxPoints(rect)          # 4x2 float
    box_i = box.astype(np.int32)
    # dibuja contorno y esquinas para que se note la rotación
    cv2.polylines(frame, [box_i], True, color, thickness)
    # for (x, y) in box_i:
    #     cv2.circle(frame, (int(x), int(y)), 3, (0,255,255), -1)
