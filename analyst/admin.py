from django.contrib import admin

from .models import AnalysisFile, AnalysisMessage, AnalysisSession

admin.site.register(AnalysisSession)
admin.site.register(AnalysisFile)
admin.site.register(AnalysisMessage)
