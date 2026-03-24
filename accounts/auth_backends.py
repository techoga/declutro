from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from .utils import normalize_email_address, normalize_phone_number


class PhoneOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, identifier=None, **kwargs):
        if password is None:
            return None

        login_identifier = identifier or username or kwargs.get("phone_number") or kwargs.get("email")
        if not login_identifier:
            return None

        UserModel = get_user_model()
        user = None

        if "@" in login_identifier:
            email = normalize_email_address(login_identifier)
            if email:
                try:
                    user = UserModel.objects.get(email__iexact=email)
                except UserModel.DoesNotExist:
                    return None
        else:
            try:
                phone_number = normalize_phone_number(login_identifier)
            except ValidationError:
                return None
            try:
                user = UserModel.objects.get(phone_number=phone_number)
            except UserModel.DoesNotExist:
                return None

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
