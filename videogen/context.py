def video_jobs(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from .models import VideoProject

    qs = VideoProject.objects.filter(user=user)
    return {
        "video_active_count": qs.filter(status__in=VideoProject.ACTIVE).count(),
        "video_unseen_count": qs.filter(seen=False, status__in=["completed", "partial", "failed"]).count(),
    }
