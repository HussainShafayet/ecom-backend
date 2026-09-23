from django.core.validators import RegexValidator

# The frontend always sends "+880" + exactly 10 digits (SignUp/SignIn validate /^\+?(\d{10})$/ on the
# local part), e.g. +8801712345678.
phone_number_validator = RegexValidator(
    regex=r"^\+880\d{10}$",
    message="Enter a valid phone number: +880 followed by 10 digits.",
)

username_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_.-]{3,50}$",
    message="Username must be 3-50 characters: letters, digits, dot, dash or underscore.",
)
