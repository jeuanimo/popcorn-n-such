from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .services import AbandonedCartRecoveryService


def recover_cart_view(request, token: str):
	try:
		AbandonedCartRecoveryService.recover_from_signed_token(request=request, signed_token=token)
		messages.success(request, "Your cart was recovered successfully.")
	except ValidationError as exc:
		messages.error(request, str(exc))
	return redirect("cart:view")


def unsubscribe_view(request, token: str):
	success = True
	detail_message = "You are unsubscribed from cart recovery reminders."
	try:
		AbandonedCartRecoveryService.unsubscribe_from_signed_token(signed_token=token)
	except ValidationError as exc:
		success = False
		detail_message = str(exc)

	return render(
		request,
		"abandoned_carts/unsubscribe_result.html",
		{
			"success": success,
			"detail_message": detail_message,
		},
	)
