"""
Management command: seed_demo_data

Populates the database with realistic but entirely fictional demo data for
local development. Safe to run multiple times — all operations are idempotent
via get_or_create. No real personal information is used.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --flush   # clears existing demo data first
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _out(style_func, msg: str) -> str:
    return style_func(f"  {msg}")


# ---------------------------------------------------------------------------
# Seed data tables
# ---------------------------------------------------------------------------

ROLES = [
    ("customer", "Regular purchasing customer"),
    ("seller", "Fundraiser seller / pop-up store owner"),
    ("team_captain", "Fundraiser team captain"),
    ("organization_manager", "Manages an organization's fundraising"),
    ("staff", "Internal staff — order fulfillment, CRM"),
    ("admin", "Full administrative access"),
]

USERS = [
    # (username, email, first, last, password, is_staff, is_superuser, role_keys, phone)
    ("admin",       "admin@popcornnsuch.local",    "Admin",    "User",    "adminpass123!",    True,  True,  ["admin"],                     "555-000-0001"),
    ("staffuser",   "staff@popcornnsuch.local",    "Staff",    "Person",  "staffpass123!",    True,  False, ["staff"],                     "555-000-0002"),
    ("orgmanager",  "orgmgr@popcornnsuch.local",   "Morgan",   "Taylor",  "orgpass123!",      False, False, ["organization_manager"],      "555-000-0003"),
    ("seller1",     "alex.chen@popcornnsuch.local","Alex",     "Chen",    "sellerpass123!",   False, False, ["seller", "team_captain"],    "555-000-0004"),
    ("seller2",     "jamie.r@popcornnsuch.local",  "Jamie",    "Rivera",  "sellerpass123!",   False, False, ["seller"],                    "555-000-0005"),
    ("customer1",   "pat.jones@popcornnsuch.local","Pat",      "Jones",   "custpass123!",     False, False, ["customer"],                  "555-000-0006"),
    ("customer2",   "sam.kim@popcornnsuch.local",  "Sam",      "Kim",     "custpass123!",     False, False, ["customer"],                  "555-000-0007"),
]

SAVED_ADDRESSES = [
    # (username, label, recipient_name, line1, line2, city, state, zip, is_default)
    ("customer1", "Home", "Pat Jones", "742 Evergreen Terrace", "", "Springfield", "IL", "62701", True),
    ("customer2", "Home", "Sam Kim",   "100 Main Street",       "", "Shelbyville", "IL", "62565", True),
]

ORGANIZATION = {
    "name": "Maplewood Elementary School",
    "org_type": "school",
    "lead_status": "active_fundraiser",
    "main_contact": "Principal Dana Park",
    "email": "principal@maplewoodelementary.local",
    "phone": "555-200-1000",
    "address_line_1": "500 Maplewood Drive",
    "city": "Springfield",
    "state": "IL",
    "postal_code": "62702",
}

SUPPLIERS = [
    {
        "name": "Great Lakes Ingredients Co.",
        "category": "ingredients",
        "contact_person": "Dale Norris",
        "email": "dale@greatlakesingredients.local",
        "phone": "555-300-0001",
        "city": "Chicago",
        "state": "IL",
        "products_supplies_provided": "Bulk popcorn kernels, flavoring oils, cheese powders",
        "payment_terms": "Net 30",
        "average_lead_time_days": 5,
        "rating": 5,
    },
    {
        "name": "Midwest Packaging Supply",
        "category": "packaging",
        "contact_person": "Rhonda Marsh",
        "email": "rhonda@midwestpackaging.local",
        "phone": "555-300-0002",
        "city": "Peoria",
        "state": "IL",
        "products_supplies_provided": "Popcorn bags, tins, boxes, gift wrap",
        "payment_terms": "Net 15",
        "average_lead_time_days": 7,
        "rating": 4,
    },
]

SUPPLIES = [
    # (name, sku_code, category, unit, qty, threshold)
    ("Yellow Butterfly Popcorn Kernels",  "SUP-KERN-YLW",  "ingredient",       "lb",  200, 50),
    ("White Mushroom Popcorn Kernels",    "SUP-KERN-WHT",  "ingredient",       "lb",  150, 30),
    ("Cheddar Cheese Powder",             "SUP-CHDR-PWD",  "ingredient",       "lb",   80, 20),
    ("Caramel Sauce Mix",                 "SUP-CARM-MIX",  "ingredient",       "lb",   60, 15),
    ("Jalapeño Seasoning Blend",          "SUP-JLPN-BLD",  "ingredient",       "lb",   40, 10),
    ("Birthday Cake Flavoring",           "SUP-BDAY-FLV",  "ingredient",       "oz",  120, 30),
    ("White Cheddar Powder",              "SUP-WCHD-PWD",  "ingredient",       "lb",   50, 15),
    ("Coconut Oil (popping)",             "SUP-COIL-POP",  "ingredient",       "gal",  30,  8),
    ("1 lb Resealable Bags",              "SUP-BAG-1LB",   "packaging",        "case", 40, 10),
    ("2 lb Resealable Bags",              "SUP-BAG-2LB",   "packaging",        "case", 30,  8),
    ("Gift Tin 2-qt",                     "SUP-TIN-2QT",   "packaging",        "each", 80, 20),
    ("Shipping Box 12x9x4",              "SUP-BOX-SM",    "shipping_supply",  "each", 60, 15),
    ("Packing Peanuts (bag)",             "SUP-PPNT-BAG",  "shipping_supply",  "bag",  20,  5),
]

PRODUCTS_DATA = [
    # (name, flavor, description, fundraiser, standalone, skus)
    # skus: list of (sku_suffix, size, retail, cost, weight_oz, qty)
    (
        "Cheddar Popcorn",
        "Cheddar",
        "Classic sharp cheddar popcorn — perfectly seasoned and impossible to put down.",
        True, True,
        [
            ("CHDR-1LB",  "1 lb Bag",  Decimal("9.99"),  Decimal("3.50"), Decimal("16.0"), 75),
            ("CHDR-2LB",  "2 lb Bag",  Decimal("17.99"), Decimal("6.50"), Decimal("32.0"), 50),
            ("CHDR-TIN",  "Gift Tin",  Decimal("24.99"), Decimal("9.00"), Decimal("48.0"), 30),
        ],
    ),
    (
        "Caramel Popcorn",
        "Caramel",
        "Rich, buttery caramel coating on every kernel. A crowd favorite.",
        True, True,
        [
            ("CARM-1LB",  "1 lb Bag",  Decimal("9.99"),  Decimal("3.50"), Decimal("16.0"), 80),
            ("CARM-2LB",  "2 lb Bag",  Decimal("17.99"), Decimal("6.50"), Decimal("32.0"), 55),
            ("CARM-TIN",  "Gift Tin",  Decimal("24.99"), Decimal("9.00"), Decimal("48.0"), 25),
        ],
    ),
    (
        "Chicago Mix",
        "Cheddar & Caramel",
        "The iconic Chicago combination — savory cheddar meets sweet caramel in every bite.",
        True, True,
        [
            ("CHGO-1LB",  "1 lb Bag",  Decimal("10.99"), Decimal("3.75"), Decimal("16.0"), 90),
            ("CHGO-2LB",  "2 lb Bag",  Decimal("19.99"), Decimal("7.00"), Decimal("32.0"), 60),
            ("CHGO-TIN",  "Gift Tin",  Decimal("26.99"), Decimal("9.50"), Decimal("48.0"), 35),
        ],
    ),
    (
        "Kettle Corn",
        "Sweet & Salty",
        "Old-fashioned kettle corn with the perfect balance of sweet and salty.",
        True, True,
        [
            ("KETL-1LB",  "1 lb Bag",  Decimal("8.99"),  Decimal("3.00"), Decimal("16.0"), 70),
            ("KETL-2LB",  "2 lb Bag",  Decimal("15.99"), Decimal("5.50"), Decimal("32.0"), 45),
        ],
    ),
    (
        "White Cheddar Popcorn",
        "White Cheddar",
        "Lighter, creamier white cheddar seasoning on our signature popcorn.",
        True, True,
        [
            ("WCHD-1LB",  "1 lb Bag",  Decimal("9.99"),  Decimal("3.50"), Decimal("16.0"), 60),
            ("WCHD-2LB",  "2 lb Bag",  Decimal("17.99"), Decimal("6.50"), Decimal("32.0"), 40),
        ],
    ),
    (
        "Movie Theater Butter Popcorn",
        "Butter",
        "Loaded with that classic movie theater butter flavor everyone loves.",
        True, True,
        [
            ("MVBT-1LB",  "1 lb Bag",  Decimal("8.99"),  Decimal("3.00"), Decimal("16.0"), 65),
            ("MVBT-2LB",  "2 lb Bag",  Decimal("15.99"), Decimal("5.50"), Decimal("32.0"), 45),
            ("MVBT-TIN",  "Gift Tin",  Decimal("22.99"), Decimal("8.00"), Decimal("48.0"), 20),
        ],
    ),
    (
        "Spicy Jalapeño Cheddar Popcorn",
        "Jalapeño Cheddar",
        "Bold jalapeño heat meets sharp cheddar. Not for the faint of heart.",
        True, True,
        [
            ("JLPN-1LB",  "1 lb Bag",  Decimal("10.99"), Decimal("3.75"), Decimal("16.0"), 50),
            ("JLPN-2LB",  "2 lb Bag",  Decimal("19.99"), Decimal("7.00"), Decimal("32.0"), 30),
        ],
    ),
    (
        "Birthday Cake Popcorn",
        "Birthday Cake",
        "Fun, colorful, and sweet — our birthday cake popcorn is a party in a bag.",
        True, True,
        [
            ("BDAY-1LB",  "1 lb Bag",  Decimal("10.99"), Decimal("3.75"), Decimal("16.0"), 55),
            ("BDAY-TIN",  "Gift Tin",  Decimal("26.99"), Decimal("9.50"), Decimal("48.0"), 20),
        ],
    ),
]

SAMPLE_ORDERS = [
    # (customer_username, sku_suffix, qty, status, payment_status, days_ago)
    ("customer1", "CHDR-1LB", 2, "paid",       "captured", 14),
    ("customer1", "CHGO-2LB", 1, "shipped",    "captured", 30),
    ("customer2", "CARM-TIN", 1, "processing", "captured",  3),
    ("customer2", "KETL-1LB", 3, "paid",       "captured",  7),
    ("customer1", "BDAY-1LB", 2, "delivered",  "captured", 45),
]


class Command(BaseCommand):
    help = "Seed the database with demo data for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing demo data before seeding (by username prefix).",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding demo data…"))

        if options["flush"]:
            self._flush()

        roles = self._seed_roles()
        users = self._seed_users(roles)
        self._seed_saved_addresses(users)
        org = self._seed_organization(users)
        self._seed_suppliers(users)
        self._seed_supplies()
        category = self._seed_product_category()
        skus_by_suffix = self._seed_products(category)
        campaign, teams = self._seed_fundraiser(org, users, skus_by_suffix)
        self._seed_seller_stores(users, campaign, teams)
        self._seed_orders(users, skus_by_suffix)

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded successfully.\n"))
        self._print_login_summary()

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def _flush(self):
        self.stdout.write("  Flushing demo data…")
        demo_usernames = [u[0] for u in USERS]
        User.objects.filter(username__in=demo_usernames).delete()
        self.stdout.write(self.style.WARNING("  Demo users (and related data) deleted."))

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------

    def _seed_roles(self) -> dict:
        from accounts.models import Role

        self.stdout.write(self.style.MIGRATE_LABEL("  Roles"))
        roles = {}
        for key, description in ROLES:
            role, created = Role.objects.get_or_create(key=key, defaults={"description": description})
            roles[key] = role
            if created:
                self.stdout.write(f"    + Role: {key}")
        return roles

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def _seed_users(self, roles: dict) -> dict[str, User]:
        from accounts.models import UserProfile

        self.stdout.write(self.style.MIGRATE_LABEL("  Users"))
        users: dict[str, User] = {}
        for username, email, first, last, password, is_staff, is_superuser, role_keys, phone in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "first_name": first,
                    "last_name": last,
                    "is_staff": is_staff,
                    "is_superuser": is_superuser,
                    "phone_number": phone,
                    "is_verified": True,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
                self.stdout.write(f"    + User: {username}")

            # Attach roles
            for key in role_keys:
                if key in roles:
                    user.roles.add(roles[key])

            # Ensure profile exists
            UserProfile.objects.get_or_create(
                user=user,
                defaults={"display_name": f"{first} {last}"},
            )
            users[username] = user
        return users

    # ------------------------------------------------------------------
    # Saved addresses
    # ------------------------------------------------------------------

    def _seed_saved_addresses(self, users: dict[str, User]):
        from accounts.models import SavedAddress

        self.stdout.write(self.style.MIGRATE_LABEL("  Saved addresses"))
        for username, label, recipient, line1, line2, city, state, postal, is_default in SAVED_ADDRESSES:
            user = users[username]
            addr, created = SavedAddress.objects.get_or_create(
                user=user,
                label=label,
                defaults={
                    "recipient_name": recipient,
                    "address_line_1": line1,
                    "address_line_2": line2,
                    "city": city,
                    "state": state,
                    "postal_code": postal,
                    "country": "US",
                    "is_default": is_default,
                },
            )
            if created:
                self.stdout.write(f"    + Address: {username} / {label}")

    # ------------------------------------------------------------------
    # Organization
    # ------------------------------------------------------------------

    def _seed_organization(self, users: dict[str, User]):
        from organizations.models import Organization, OrganizationNote

        self.stdout.write(self.style.MIGRATE_LABEL("  Organization"))
        org, created = Organization.objects.get_or_create(
            name=ORGANIZATION["name"],
            defaults={
                **{k: v for k, v in ORGANIZATION.items() if k != "name"},
                "manager": users["orgmanager"],
                "relationship_owner": users["staffuser"],
                "last_contact_date": datetime.date(2026, 5, 1),
                "next_contact_date": datetime.date(2026, 6, 1),
            },
        )
        if created:
            self.stdout.write(f"    + Organization: {org.name}")
            OrganizationNote.objects.create(
                organization=org,
                note="Initial contact made. Principal Park is enthusiastic about the fall popcorn fundraiser.",
                created_by=users["staffuser"],
            )
        return org

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------

    def _seed_suppliers(self, users: dict[str, User]):
        from suppliers.models import Supplier

        self.stdout.write(self.style.MIGRATE_LABEL("  Suppliers"))
        for data in SUPPLIERS:
            supplier, created = Supplier.objects.get_or_create(
                name=data["name"],
                defaults={**data, "created_by": users["admin"]},
            )
            if created:
                self.stdout.write(f"    + Supplier: {supplier.name}")

    # ------------------------------------------------------------------
    # Supplies
    # ------------------------------------------------------------------

    def _seed_supplies(self):
        from supplies.models import Supply

        self.stdout.write(self.style.MIGRATE_LABEL("  Supplies"))
        for name, sku_code, category, unit, qty, threshold in SUPPLIES:
            supply, created = Supply.objects.get_or_create(
                name=name,
                defaults={
                    "sku_code": sku_code,
                    "category": category,
                    "unit": unit,
                    "inventory_quantity": qty,
                    "low_stock_threshold": threshold,
                },
            )
            if created:
                self.stdout.write(f"    + Supply: {name}")

    # ------------------------------------------------------------------
    # Product category + products + SKUs
    # ------------------------------------------------------------------

    def _seed_product_category(self):
        from products.models import ProductCategory

        self.stdout.write(self.style.MIGRATE_LABEL("  Product categories"))
        cat, created = ProductCategory.objects.get_or_create(
            key="popcorn",
            defaults={"name": "Popcorn", "is_active": True},
        )
        if created:
            self.stdout.write("    + Category: Popcorn")
        return cat

    def _seed_products(self, category) -> dict[str, object]:
        from products.models import Product, SKU

        self.stdout.write(self.style.MIGRATE_LABEL("  Products & SKUs"))
        skus_by_suffix: dict[str, SKU] = {}

        for name, flavor, description, fundraiser_eligible, standalone_eligible, skus_data in PRODUCTS_DATA:
            product, created = Product.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    "name": name,
                    "flavor": flavor,
                    "description": description,
                    "category": category,
                    "is_active": True,
                    "fundraiser_eligible": fundraiser_eligible,
                    "standalone_store_eligible": standalone_eligible,
                },
            )
            if created:
                self.stdout.write(f"    + Product: {name}")

            for sku_suffix, size, retail, cost, weight, qty in skus_data:
                sku_code = f"PNS-{sku_suffix}"
                sku, sku_created = SKU.objects.get_or_create(
                    sku_code=sku_code,
                    defaults={
                        "product": product,
                        "size": size,
                        "retail_price": retail,
                        "cost_price": cost,
                        "weight_ounces": weight,
                        "inventory_quantity": qty,
                        "low_stock_threshold": 10,
                        "is_active": True,
                    },
                )
                skus_by_suffix[sku_suffix] = sku
                if sku_created:
                    self.stdout.write(f"      + SKU: {sku_code} ({size})")

        return skus_by_suffix

    # ------------------------------------------------------------------
    # Fundraiser campaign + teams
    # ------------------------------------------------------------------

    def _seed_fundraiser(self, org, users: dict[str, User], skus_by_suffix: dict):
        from fundraisers.models import FundraiserCampaign, FundraiserCampaignStatus
        from teams.models import Team, TeamMembership, TeamMemberRole

        self.stdout.write(self.style.MIGRATE_LABEL("  Fundraiser campaign"))
        campaign, created = FundraiserCampaign.objects.get_or_create(
            slug="maplewood-fall-2026",
            defaults={
                "organization": org,
                "campaign_name": "Maplewood Fall Popcorn Drive 2026",
                "description": "Help Maplewood Elementary raise funds for new playground equipment!",
                "fundraising_purpose": "New playground equipment for K-5 students",
                "start_date": datetime.date(2026, 9, 1),
                "end_date": datetime.date(2026, 10, 31),
                "goal_amount": Decimal("10000.00"),
                "profit_percentage": Decimal("35.00"),
                "status": FundraiserCampaignStatus.ACTIVE,
                "is_active": True,
                "created_by": users["staffuser"],
                "approved_by": users["admin"],
            },
        )
        if created:
            self.stdout.write(f"    + Campaign: {campaign.campaign_name}")

        self.stdout.write(self.style.MIGRATE_LABEL("  Teams"))
        teams = []
        team_data = [
            ("Team Kernel Crushers", "team-kernel-crushers-maplewood-2026", users["seller1"], Decimal("2500.00")),
            ("Team Butter Brigade",  "team-butter-brigade-maplewood-2026",  users["seller2"], Decimal("2000.00")),
        ]
        for team_name, team_slug, captain, goal in team_data:
            team, team_created = Team.objects.get_or_create(
                slug=team_slug,
                defaults={
                    "campaign": campaign,
                    "organization": org,
                    "name": team_name,
                    "captain": captain,
                    "team_goal": goal,
                    "is_active": True,
                },
            )
            if team_created:
                self.stdout.write(f"    + Team: {team_name}")
                # Add captain as a member with captain role
                TeamMembership.objects.get_or_create(
                    team=team,
                    member=captain,
                    defaults={"role": TeamMemberRole.CAPTAIN},
                )
                # Add customers as members
                for customer_key in ("customer1", "customer2"):
                    TeamMembership.objects.get_or_create(
                        team=team,
                        member=users[customer_key],
                        defaults={"role": TeamMemberRole.MEMBER},
                    )
            teams.append(team)

        # Link teams to campaign
        for team in teams:
            campaign.teams.add(team)

        return campaign, teams

    # ------------------------------------------------------------------
    # Seller links + stores
    # ------------------------------------------------------------------

    def _seed_seller_stores(self, users: dict[str, User], campaign, teams: list):
        from sellers.models import SellerLink, SellerStore

        self.stdout.write(self.style.MIGRATE_LABEL("  Seller stores"))
        seller_store_data = [
            (
                "seller1", "Alex's Popcorn Stand",
                "alex-chen-maplewood-2026",
                "Alex Chen's Official Maplewood Popcorn Store",
                "Help me reach my goal — every bag supports our playground!",
                Decimal("1500.00"),
                teams[0],
            ),
            (
                "seller2", "Jamie's Popcorn Shop",
                "jamie-rivera-maplewood-2026",
                "Jamie Rivera's Popcorn Shop",
                "Support the Butter Brigade — buy a bag today!",
                Decimal("1200.00"),
                teams[1] if len(teams) > 1 else None,
            ),
        ]
        for username, link_title, store_slug, display_name, message, goal, team in seller_store_data:
            user = users[username]

            link, _ = SellerLink.objects.get_or_create(
                user=user,
                slug=slugify(link_title),
                defaults={"title": link_title, "is_active": True},
            )

            store, store_created = SellerStore.objects.get_or_create(
                slug=store_slug,
                defaults={
                    "seller": user,
                    "campaign": campaign,
                    "team": team,
                    "display_name": display_name,
                    "personal_message": message,
                    "seller_goal": goal,
                    "is_active": True,
                },
            )
            if store_created:
                self.stdout.write(f"    + Store: {display_name}")
            campaign.sellers.add(link)

    # ------------------------------------------------------------------
    # Sample orders
    # ------------------------------------------------------------------

    def _seed_orders(self, users: dict[str, User], skus_by_suffix: dict):
        from decimal import Decimal

        from orders.models import Order, OrderItem, OrderStatus, PaymentStatus

        self.stdout.write(self.style.MIGRATE_LABEL("  Sample orders"))

        _SHIPPING_ADDRESSES = {
            "customer1": {
                "shipping_recipient_name": "Pat Jones",
                "shipping_address_line_1": "742 Evergreen Terrace",
                "shipping_city": "Springfield",
                "shipping_state": "IL",
                "shipping_postal_code": "62701",
                "shipping_country": "US",
            },
            "customer2": {
                "shipping_recipient_name": "Sam Kim",
                "shipping_address_line_1": "100 Main Street",
                "shipping_city": "Shelbyville",
                "shipping_state": "IL",
                "shipping_postal_code": "62565",
                "shipping_country": "US",
            },
        }

        order_counter = Order.objects.count()

        for customer_key, sku_suffix, qty, status_val, payment_val, days_ago in SAMPLE_ORDERS:
            customer = users[customer_key]
            sku = skus_by_suffix.get(sku_suffix)
            if sku is None:
                continue

            unit_price = int(sku.retail_price * 100)
            subtotal = unit_price * qty
            tax = int(subtotal * Decimal("0.0825"))
            shipping = 599
            total = subtotal + tax + shipping

            created_at = timezone.now() - datetime.timedelta(days=days_ago)

            order = Order.objects.create(
                customer=customer,
                **_SHIPPING_ADDRESSES[customer_key],
                billing_same_as_shipping=True,
                subtotal_cents=subtotal,
                tax_cents=tax,
                shipping_cents=shipping,
                total_cents=total,
                status=status_val,
                payment_status=payment_val,
            )

            # Backdate the created_at after creation (auto_now_add can't be set directly)
            Order.objects.filter(pk=order.pk).update(created_at=created_at)

            OrderItem.objects.create(
                order=order,
                product=sku.product,
                sku=sku,
                product_name_snapshot=sku.product.name,
                sku_snapshot={
                    "sku_code": sku.sku_code,
                    "size": sku.size,
                    "retail_price": str(sku.retail_price),
                },
                quantity=qty,
                unit_price_cents=unit_price,
                line_total_cents=unit_price * qty,
                weight_ounces=sku.weight_ounces,
                fundraiser_eligible=sku.product.fundraiser_eligible,
            )
            order_counter += 1
            self.stdout.write(f"    + Order: {customer_key} × {qty} {sku_suffix} [{status_val}]")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_login_summary(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Demo login credentials:"))
        rows = [
            ("admin",      "admin@popcornnsuch.local",    "adminpass123!",  "superuser"),
            ("staffuser",  "staff@popcornnsuch.local",    "staffpass123!",  "staff"),
            ("orgmanager", "orgmgr@popcornnsuch.local",   "orgpass123!",    "org_manager"),
            ("seller1",    "alex.chen@popcornnsuch.local","sellerpass123!", "seller + captain"),
            ("seller2",    "jamie.r@popcornnsuch.local",  "sellerpass123!", "seller"),
            ("customer1",  "pat.jones@popcornnsuch.local","custpass123!",   "customer"),
            ("customer2",  "sam.kim@popcornnsuch.local",  "custpass123!",   "customer"),
        ]
        for username, email, password, role in rows:
            self.stdout.write(
                f"  {self.style.SQL_KEYWORD(username):30s}  "
                f"{email:36s}  "
                f"{self.style.SQL_FIELD(password):20s}  "
                f"({role})"
            )
        self.stdout.write("")
