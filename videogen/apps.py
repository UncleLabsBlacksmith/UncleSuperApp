import os
import sys

from django.apps import AppConfig


class VideogenConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "videogen"

    def ready(self):
        from django.conf import settings

        if not settings.VIDEO_WORKER_AUTOSTART:
            return
        argv = " ".join(sys.argv)
        if "runserver" not in argv:
            return  # คำสั่งอื่น (migrate, shell ฯลฯ) ไม่ต้องเริ่ม worker
        # runserver ที่มี autoreload จะมี 2 process — เริ่มเฉพาะใน process ลูกที่รันเว็บจริง
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in argv:
            return
        from .worker import start_background_worker

        start_background_worker()
