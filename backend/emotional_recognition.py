"""Webcam emotion detection demo using Claude. Press `q` to quit.

Faces are boxed locally with OpenCV; the emotion comes from Claude, which is
asked every ASK_INTERVAL seconds to stay within the API's rate limits.
"""
import time

import cv2

from claude_emotion import NoFaceDetected, detect_emotion_frame

ASK_INTERVAL = 1.5  # seconds between Claude calls

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
cap = cv2.VideoCapture(0)

emotion = None
last_asked = 0.0

while True:
    ret, frame = cap.read()
    if not ret:
        break
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)

    # Only call Claude when OpenCV sees a face, and not more often than ASK_INTERVAL.
    # The call blocks for about a second, so the video pauses briefly while it runs.
    if len(faces) and time.monotonic() - last_asked >= ASK_INTERVAL:
        last_asked = time.monotonic()
        try:
            emotion = detect_emotion_frame(frame)
        except NoFaceDetected:
            emotion = None
        except Exception as e:
            print(f"Error: {e}")

    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
        if emotion:
            cv2.putText(frame, emotion, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
    cv2.imshow('frame', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
