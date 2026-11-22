from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def manager_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.can_manage_users:
            messages.error(request, "หน้านี้สำหรับผู้ดูแลระบบเท่านั้น")
            return redirect("chat:index")
        return view(request, *args, **kwargs)

    return wrapper
