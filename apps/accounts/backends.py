from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsernameOrEmailBackend(ModelBackend):
    """Authenticate by username, email or employee ID — same input field.

    Employee portal usernames are slugified first names (see
    `apps.employees.services._unique_username_for`), so staff who type
    their emp_code (e.g. `BLR-2024-0012`) used to get "Invalid
    credentials" no matter what the password was. The emp_code lookup
    goes through `Employee.user_account`, so it only ever resolves to the
    account HR linked to that employee row.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        identifier = username.strip()
        if not identifier:
            return None
        User = get_user_model()
        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()
        if user is None:
            user = self._user_for_emp_code(identifier)
        if user is None:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _user_for_emp_code(identifier):
        # Imported lazily: employees depends on accounts.
        from apps.employees.models import Employee

        emp = (
            Employee.all_objects
            .filter(emp_code__iexact=identifier, user_account__isnull=False)
            .select_related("user_account")
            .first()
        )
        return emp.user_account if emp is not None else None
