"""
Shopping cart and order utilities.

Cart state is in-memory per user (lives for the process lifetime).
Confirmed orders are persisted in the database.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CartItem:
    dish_id: str
    name: str
    price: float
    quantity: int = 1

    @property
    def subtotal(self) -> float:
        return self.price * self.quantity


class CartManager:
    """
    In-memory shopping cart, one per WhatsApp user.
    Also provides dish lookup against the restaurant menu JSON.
    """

    def __init__(self, menu_path: str = "./data/restaurant_menu.json"):
        self._carts: dict[str, dict[str, CartItem]] = {}
        self._menu: Optional[dict] = None
        self._menu_path = menu_path

    # ── Menu helpers ──────────────────────────────────────────────
    def _load_menu(self) -> dict:
        if self._menu is None:
            path = Path(self._menu_path)
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self._menu = json.load(f)
            else:
                self._menu = {
                    "dishes": [],
                    "restaurant": {"currency": "ريال", "min_order": 25},
                }
        return self._menu

    def find_dish(self, query: str) -> Optional[dict]:
        """
        Find a dish by name. Tries exact match, then partial, then word-overlap.
        Returns the dish dict or None.
        """
        menu = self._load_menu()
        q = query.lower().strip()
        dishes = menu.get("dishes", [])

        # 1. Exact name match
        for dish in dishes:
            if q == dish["name"].lower() or q == dish.get("name_en", "").lower():
                return dish

        # 2. Substring match
        for dish in dishes:
            if q in dish["name"].lower() or q in dish.get("name_en", "").lower():
                return dish

        # 3. Word-overlap match (best scored)
        q_words = set(q.split())
        best, best_score = None, 0
        for dish in dishes:
            dish_words = set(dish["name"].lower().split())
            score = len(q_words & dish_words)
            if score > best_score:
                best_score, best = score, dish

        return best if best_score > 0 else None

    def get_currency(self) -> str:
        return self._load_menu().get("restaurant", {}).get("currency", "ريال")

    def get_min_order(self) -> float:
        return float(self._load_menu().get("restaurant", {}).get("min_order", 25))

    # ── Cart operations ───────────────────────────────────────────
    def add_item(
        self, user_id: str, dish_id: str, name: str, price: float, qty: int = 1
    ) -> CartItem:
        cart = self._carts.setdefault(user_id, {})
        if dish_id in cart:
            cart[dish_id].quantity += qty
        else:
            cart[dish_id] = CartItem(dish_id=dish_id, name=name, price=price, quantity=qty)
        return cart[dish_id]

    def remove_item(self, user_id: str, dish_id: str) -> bool:
        cart = self._carts.get(user_id, {})
        if dish_id in cart:
            del cart[dish_id]
            return True
        return False

    def get_items(self, user_id: str) -> list[CartItem]:
        return list(self._carts.get(user_id, {}).values())

    def get_total(self, user_id: str) -> float:
        return sum(item.subtotal for item in self.get_items(user_id))

    def is_empty(self, user_id: str) -> bool:
        return not bool(self._carts.get(user_id))

    def clear(self, user_id: str) -> None:
        self._carts.pop(user_id, None)

    # ── Formatted messages ────────────────────────────────────────
    def format_cart(self, user_id: str) -> str:
        currency = self.get_currency()
        items = self.get_items(user_id)

        if not items:
            return (
                "🛒 *سلتك فارغة!*\n\n"
                "أضف أطباقاً بكتابة:\n"
                "• /طلب كبسة\n"
                "• /طلب شيش طاووق\n"
                "• /طلب كنافة"
            )

        lines = ["🛒 *سلتك الحالية:*", ""]
        for item in items:
            lines.append(
                f"• {item.name} × {item.quantity} — *{item.subtotal:.0f} {currency}*"
            )

        total = self.get_total(user_id)
        min_order = self.get_min_order()
        lines += ["", f"💰 *الإجمالي: {total:.0f} {currency}*"]

        if total < min_order:
            remaining = min_order - total
            lines.append(
                f"⚠️ الحد الأدنى للطلب {min_order:.0f} {currency} "
                f"— أضف {remaining:.0f} {currency} أكثر"
            )

        lines += [
            "",
            "✅ /تأكيد — تأكيد الطلب",
            "❌ /إلغاء — إلغاء وتفريغ السلة",
        ]
        return "\n".join(lines)

    def format_order_for_staff(
        self, user_id: str, order_id: int, user_name: str = ""
    ) -> str:
        currency = self.get_currency()
        items = self.get_items(user_id)
        total = self.get_total(user_id)

        name_str = f" — {user_name}" if user_name else ""
        lines = [
            f"🔔 *طلب جديد #{order_id}*",
            f"👤 الزبون: {user_id}{name_str}",
            "",
            "*تفاصيل الطلب:*",
        ]
        for item in items:
            lines.append(
                f"• {item.name} × {item.quantity} — {item.subtotal:.0f} {currency}"
            )
        lines += [
            "",
            f"💰 *الإجمالي: {total:.0f} {currency}*",
            "",
            "⏰ يرجى تحضير الطلب فوراً!",
        ]
        return "\n".join(lines)


# Module-level singleton shared across the app
cart_manager = CartManager()
