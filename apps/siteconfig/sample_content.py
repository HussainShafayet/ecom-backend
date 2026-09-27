"""The sample identity, pages and FAQ that `seed_site` writes (development data: replace it in the admin)."""

SITE = {
    "site_name": "GoCart",
    "tagline": "Everyday things, delivered",
    "announcement_enabled": True,
    "announcement_text": "Flash Sale! Up to 50% Off Selected Items",
    "announcement_link": "/products/flash-sale",
    "contact_email": "support@gocart.example",
    "contact_phone": "+880 1700-000000",
    "contact_address": "House 12, Road 5, Dhanmondi, Dhaka 1205",
    "opening_hours": "Sat - Thu: 10:00 AM - 8:00 PM",
    "map_embed_url": "https://www.openstreetmap.org/export/embed.html?bbox=90.36%2C23.72%2C90.41%2C23.77&layer=mapnik",
}
SOCIAL_LINKS = [
    ("facebook", "https://www.facebook.com/share/1Dvz2bd5J8/"),
    ("instagram", "https://www.instagram.com/gocartbd/"),
]

NOTE = "<p><em>This is sample text. Replace it in the admin (Site > Static pages) before you open the shop.</em></p>"

PAGES = [
    {
        "slug": "about-us",
        "title": "About Us",
        "footer_group": "company",
        "order": 1,
        "body": (
            "<h2>Our Story</h2>"
            "<p>Since our inception in 2022, we have been on a mission to make online shopping seamless, accessible and "
            "enjoyable for everyone. Driven by our core values of trust, quality and customer-centricity, we aim to bring "
            "high-quality products and a superior shopping experience.</p>"
            "<h2>What we stand for</h2>"
            "<ul>"
            "<li><strong>Integrity</strong>: building trust with transparency and honesty.</li>"
            "<li><strong>Customer first</strong>: exceeding expectations at every touchpoint.</li>"
            "<li><strong>Innovation</strong>: constantly improving our services.</li>"
            "<li><strong>Commitment</strong>: creating a positive impact through dedication.</li>"
            "</ul>"
        ),
    },
    {
        "slug": "privacy-policy",
        "title": "Privacy Policy",
        "footer_group": "legal",
        "order": 1,
        "body": (
            NOTE
            + "<p>Your privacy is important to us. This Privacy Policy explains how we collect, use and protect your information.</p>"
            "<h2>1. Information we collect</h2>"
            "<ul><li>Personal information: your name, e-mail address, phone number and delivery address.</li>"
            "<li>Order information: what you ordered and how you chose to pay.</li>"
            "<li>Browsing data: IP address, browser type and activity on our site.</li>"
            "<li>Cookies: to improve your experience and understand how the site is used.</li></ul>"
            "<h2>2. How we use your information</h2>"
            "<ul><li>To process and deliver your orders.</li>"
            "<li>To provide customer support and answer your messages.</li>"
            "<li>To send you our newsletter (only if you subscribed).</li>"
            "<li>To analyse site performance and improve it.</li></ul>"
            "<h2>3. Sharing your information</h2>"
            "<ul><li>We do not sell your personal data. We share it only where it is needed to deliver your order "
            "(for example with the courier).</li>"
            "<li>We may disclose it to comply with the law.</li></ul>"
            "<h2>4. Cookies</h2>"
            "<p>We use cookies to personalise your shopping experience and improve our services. You can control cookies "
            "in your browser settings.</p>"
            "<h2>5. How we protect your data</h2>"
            "<p>We use secure servers and encryption. No system is completely secure, so please look after your own "
            "account and phone.</p>"
            "<h2>6. Your rights</h2>"
            "<ul><li>You can ask to see, correct or delete your personal information.</li>"
            "<li>You can stop receiving our newsletter at any time.</li></ul>"
            "<h2>7. Changes to this policy</h2>"
            "<p>We may update this policy. Changes are posted on this page.</p>"
            "<h2>8. Contact us</h2>"
            "<p>Questions about this policy? Use the contact page and we will get back to you.</p>"
        ),
    },
    {
        "slug": "terms-of-service",
        "title": "Terms of Service",
        "footer_group": "legal",
        "order": 2,
        "body": (
            NOTE
            + "<h2>1. Using this site</h2>"
            "<p>By placing an order you agree to these terms. Please give correct delivery details: we deliver to the "
            "address and phone number you enter at checkout.</p>"
            "<h2>2. Prices and availability</h2>"
            "<p>Prices are shown in the shop's currency and may change. An order is confirmed only when the goods are "
            "available.</p>"
            "<h2>3. Payment and delivery</h2>"
            "<p>You pay as offered at checkout. Delivery times depend on your area and are estimates.</p>"
            "<h2>4. Cancellations and returns</h2>"
            "<p>You can cancel an order while it is still pending. After that, contact us and we will help.</p>"
        ),
    },
    {
        "slug": "cookie-policy",
        "title": "Cookie Policy",
        "footer_group": "legal",
        "order": 3,
        "body": (
            NOTE
            + "<h2>What we store</h2>"
            "<p>We keep a small amount of data in your browser so the site works: your sign-in, your cart and your "
            "wishlist. We do not use it to follow you around other websites.</p>"
            "<h2>Controlling cookies</h2>"
            "<p>You can clear or block cookies in your browser settings; signing in and the cart may stop working if you do.</p>"
        ),
    },
]

FAQ = [
    ("Orders", "What is your return policy?", "You can return any product within 30 days of purchase. The product must be unused and in its original packaging. Please contact support for further assistance."),
    ("Orders", "Can I change my order after placing it?", "You can cancel an order while it is still pending, from My Orders. After that it can not be modified; contact our support team and we will help."),
    ("Shipping", "How long does shipping take?", "Shipping times depend on your location. Typically, orders are delivered within 3-5 business days."),
    ("Shipping", "Do you offer international shipping?", "Not yet. We deliver inside Bangladesh."),
    ("Payments", "What payment methods do you accept?", "Cash on delivery. More payment methods are coming."),
]
