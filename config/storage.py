"""Static files ที่ต่อท้าย ?v=<เวลาแก้ไขไฟล์> อัตโนมัติ
เบราว์เซอร์จะโหลด CSS/JS ใหม่ทันทีที่ไฟล์เปลี่ยน ไม่ต้องกด Ctrl+F5

Developed by Uncle Engineer — https://uncle-engineer.com/
"""
import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        try:
            path = finders.find(name)
            if not path and self.exists(name):
                path = self.path(name)
            if path:
                url += ("&" if "?" in url else "?") + "v=" + format(int(os.stat(path).st_mtime), "x")
        except (OSError, ValueError, NotImplementedError):
            pass
        return url
