from django.dispatch import Signal

# Sent after a successful OTP verification with whatever the guest had in the browser.
#   user:       the User who just signed in
#   cart:       list of dicts   [{"product_id", "quantity", "variant_id"?}, ...]   (untrusted, unvalidated)
#   favorites:  list of dicts   [{"product_id"}, ...]                              (untrusted, unvalidated)
# `accounts` stays free of shop logic: the cart/wishlist apps connect a receiver that merges the data.
# Receivers run with send_robust, so a bug there can never block a sign-in.
guest_data_received = Signal()
