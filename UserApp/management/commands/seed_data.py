from django.core.management.base import BaseCommand
from UserApp.models import Category, Product

class Command(BaseCommand):
    help = "Seed database with initial categories and products"

    def handle(self, *args, **kwargs):
        categories = ["Fiction", "Science", "History", "Technology"]
        for cat in categories:
            Category.objects.get_or_create(Category_name=cat)

        books = [
            {"pname": "The Great Gatsby", "p_short_name": "Gatsby", "author": "F. Scott Fitzgerald", "price": 10, "description": "Classic novel", "size": 1, "quantity": 10, "cat": "Fiction"},
            {"pname": "A Brief History of Time", "p_short_name": "Time", "author": "Stephen Hawking", "price": 15, "description": "Science classic", "size": 1, "quantity": 10, "cat": "Science"},
            {"pname": "Sapiens", "p_short_name": "Sapiens", "author": "Yuval Noah Harari", "price": 20, "description": "History bestseller", "size": 1, "quantity": 10, "cat": "History"},
            {"pname": "Clean Code", "p_short_name": "CleanCode", "author": "Robert C. Martin", "price": 25, "description": "Programming must-read", "size": 1, "quantity": 10, "cat": "Technology"},
        ]

        for b in books:
            cat = Category.objects.get(Category_name=b["cat"])
            Product.objects.get_or_create(
                pname=b["pname"],
                p_short_name=b["p_short_name"],
                author=b["author"],
                price=b["price"],
                description=b["description"],
                size=b["size"],
                quantity=b["quantity"],
                cat=cat,
            )
        self.stdout.write(self.style.SUCCESS("Database seeded!"))
