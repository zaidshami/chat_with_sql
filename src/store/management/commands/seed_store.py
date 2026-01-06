from django.core.management.base import BaseCommand
from store.models import Customer, Product, Order, OrderItem
from django.db import transaction
import random

class Command(BaseCommand):
    help = "Seed demo store data"

    @transaction.atomic
    def handle(self, *args, **options):
        if Customer.objects.exists():
            self.stdout.write(self.style.WARNING("Store already has data; skipping."))
            return

        customers = [
            Customer.objects.create(name="Aisha Al-Harazi", email="aisha@example.com"),
            Customer.objects.create(name="Salem Al-Maqtari", email="salem@example.com"),
            Customer.objects.create(name="Mona Al-Sabri", email="mona@example.com"),
        ]

        products = [
            Product.objects.create(name="Solar Power Bank 20,000mAh", price="39.00"),
            Product.objects.create(name="MikroTik hAP ac2 Router", price="79.00"),
            Product.objects.create(name="Hotspot Voucher Pack (100 cards)", price="120.00"),
            Product.objects.create(name="UPS 1kVA", price="110.00"),
        ]

        for _ in range(15):
            c = random.choice(customers)
            o = Order.objects.create(customer=c)
            for _ in range(random.randint(1, 3)):
                p = random.choice(products)
                OrderItem.objects.create(order=o, product=p, qty=random.randint(1, 5))

        self.stdout.write(self.style.SUCCESS("Seeded store data."))
