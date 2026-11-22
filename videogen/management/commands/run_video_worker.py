from django.core.management.base import BaseCommand

from videogen.worker import run_forever


class Command(BaseCommand):
    help = "รัน worker ของ Video Generator แบบแยก process (ใช้เมื่อ deploy ด้วย waitress/gunicorn และตั้ง VIDEO_WORKER_AUTOSTART=0)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Video worker running — Ctrl+C to stop"))
        try:
            run_forever()
        except KeyboardInterrupt:
            self.stdout.write("stopped")
