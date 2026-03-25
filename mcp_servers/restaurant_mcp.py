"""
Restaurant Menu MCP Server — مطعم أبو طبق

Provides tools for querying the restaurant menu, dish details,
prices, and personalized recommendations via WhatsApp.

Tools:
  - get_full_menu          → Full categorized menu
  - get_category_menu      → Dishes filtered by category
  - get_dish_details       → Full details for a specific dish
  - search_menu            → Search dishes by keyword
  - get_recommendations    → Personalized dish recommendations
  - get_daily_specials     → Today's special offers
  - get_restaurant_info    → Restaurant general info
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# ── MCP SDK imports ───────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print(
        "ERROR: MCP SDK not installed. Run: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Load Menu Data ────────────────────────────────────────────────
def load_menu(menu_path: str) -> dict:
    path = Path(menu_path)
    if not path.exists():
        raise FileNotFoundError(f"Menu file not found: {menu_path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Helper Formatters ─────────────────────────────────────────────
def format_dish_card(dish: dict, currency: str = "ريال") -> str:
    """Format a single dish as a WhatsApp-friendly card."""
    emoji = dish.get("emoji", "🍽️")
    spicy_map = {0: "", 1: "🌶️ خفيف حار", 2: "🌶️🌶️ متوسط", 3: "🌶️🌶️🌶️ حار جداً"}
    spicy = spicy_map.get(dish.get("spicy_level", 0), "")

    tags = []
    if dish.get("is_vegetarian"):
        tags.append("🥬 نباتي")
    if dish.get("is_recommended"):
        tags.append("⭐ موصى به")
    if dish.get("serves"):
        tags.append(f"👥 يكفي {dish['serves']}")

    lines = [
        f"{emoji} *{dish['name']}*",
        f"💰 السعر: *{dish['price']} {currency}*",
        f"📝 {dish['description_short']}",
    ]
    if spicy:
        lines.append(f"🌶️ الحرارة: {spicy}")
    if tags:
        lines.append("  ".join(tags))
    if dish.get("prep_time"):
        lines.append(f"⏱️ وقت التحضير: {dish['prep_time']} دقيقة")

    return "\n".join(lines)


def format_dish_full(dish: dict, currency: str = "ريال") -> str:
    """Format full dish details for WhatsApp."""
    emoji = dish.get("emoji", "🍽️")
    spicy_map = {0: "لا حرارة", 1: "🌶️ خفيف", 2: "🌶️🌶️ متوسط", 3: "🌶️🌶️🌶️ حار جداً"}
    spicy = spicy_map.get(dish.get("spicy_level", 0), "")

    lines = [
        f"{emoji} *{dish['name']}*",
        f"_{dish.get('name_en', '')}_",
        "",
        f"💰 *السعر:* {dish['price']} {currency}",
        "",
        f"📖 *الوصف:*\n{dish['description']}",
        "",
        f"🥄 *المكونات:* {', '.join(dish.get('ingredients', []))}",
        f"🔥 *السعرات:* {dish.get('calories', '—')} سعرة",
        f"🌡️ *مستوى الحرارة:* {spicy}",
        f"⏱️ *وقت التحضير:* {dish.get('prep_time', '—')} دقيقة",
    ]

    allergens = dish.get("allergens", [])
    if allergens:
        lines.append(f"⚠️ *تحذير حساسية:* {', '.join(allergens)}")

    if dish.get("serves"):
        lines.append(f"👥 *يكفي:* {dish['serves']} أشخاص")

    if dish.get("is_vegetarian"):
        lines.append("🥬 *نباتي* ✅")
    if dish.get("is_recommended"):
        lines.append("⭐ *موصى به من الشيف*")
    if dish.get("fun_fact"):
        lines.append(f"\n😄 *حقيقة ظريفة:*\n_{dish['fun_fact']}_")

    return "\n".join(lines)


# ── MCP Server ────────────────────────────────────────────────────
def create_restaurant_server(menu_path: str) -> Server:
    menu = load_menu(menu_path)
    restaurant = menu["restaurant"]
    dishes = menu["dishes"]
    categories = menu["categories"]
    currency = restaurant.get("currency", "ريال")
    recommendations = menu.get("recommendations", {})
    daily_specials = menu.get("daily_specials", [])

    server = Server("restaurant-menu")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="get_full_menu",
                description=(
                    "Get the full restaurant menu organized by categories. "
                    "Use when user asks for the full menu, all dishes, or what's available."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            types.Tool(
                name="get_category_menu",
                description=(
                    "Get dishes for a specific category. "
                    "Categories: starters (مقبلات), mains (أطباق رئيسية), "
                    "grills (مشويات), drinks (مشروبات), desserts (حلويات)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": (
                                "Category ID or name in Arabic/English. "
                                "Options: starters, mains, grills, drinks, desserts"
                            ),
                        }
                    },
                    "required": ["category"],
                },
            ),
            types.Tool(
                name="get_dish_details",
                description=(
                    "Get full details for a specific dish including description, "
                    "ingredients, allergens, calories, and fun facts. "
                    "Use when user asks about a specific dish."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "dish_name": {
                            "type": "string",
                            "description": "Name of the dish in Arabic or English",
                        }
                    },
                    "required": ["dish_name"],
                },
            ),
            types.Tool(
                name="search_menu",
                description=(
                    "Search for dishes by keyword in name, description, or ingredients. "
                    "Use when user asks for dishes with specific ingredients or keywords."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "Search keyword (e.g., دجاج, لحم, نباتي, حار)",
                        }
                    },
                    "required": ["keyword"],
                },
            ),
            types.Tool(
                name="get_recommendations",
                description=(
                    "Get personalized dish recommendations based on preference. "
                    "Use when user asks for suggestions, recommendations, or what's best."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "preference": {
                            "type": "string",
                            "description": (
                                "Preference type: vegetarian (نباتي), spicy (حار), "
                                "family (عائلة), solo (فردي), kids (أطفال), "
                                "value (اقتصادي), chef_picks (اختيار الشيف)"
                            ),
                        }
                    },
                    "required": [],
                },
            ),
            types.Tool(
                name="get_daily_specials",
                description=(
                    "Get today's special offers and discounts. "
                    "Use when user asks about offers, discounts, or daily specials."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            types.Tool(
                name="get_restaurant_info",
                description=(
                    "Get restaurant general information: name, hours, delivery time, "
                    "minimum order, phone. Use when user asks about the restaurant."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        result = _handle_tool(name, arguments)
        return [types.TextContent(type="text", text=result)]

    def _handle_tool(name: str, arguments: dict) -> str:  # noqa: C901
        # ── get_full_menu ─────────────────────────────────────────
        if name == "get_full_menu":
            lines = [
                f"🍽️ *قائمة {restaurant['name']}*",
                f"_{restaurant['tagline']}_",
                "",
            ]
            for cat in categories:
                cat_dishes = [d for d in dishes if d["category"] == cat["id"]]
                if not cat_dishes:
                    continue
                lines.append(f"\n{cat['name']}")
                lines.append(f"_{cat['description']}_")
                lines.append("─" * 20)
                for dish in cat_dishes:
                    lines.append(
                        f"{dish.get('emoji','🍽️')} *{dish['name']}* — "
                        f"{dish['price']} {currency}"
                    )
                    if dish.get("is_recommended"):
                        lines[-1] += " ⭐"
            lines.append(
                f"\n\n💬 اطلب تفاصيل أي طبق أو قل 'وصف [اسم الطبق]' لمعرفة المزيد!"
            )
            return "\n".join(lines)

        # ── get_category_menu ─────────────────────────────────────
        elif name == "get_category_menu":
            category = arguments.get("category", "").lower().strip()

            # Map Arabic category names to IDs
            arabic_map = {
                "مقبلات": "starters",
                "مقبلة": "starters",
                "سلطات": "starters",
                "الأطباق الرئيسية": "mains",
                "رئيسية": "mains",
                "أطباق": "mains",
                "مشويات": "grills",
                "مشوية": "grills",
                "مشروبات": "drinks",
                "عصائر": "drinks",
                "حلويات": "desserts",
                "حلوى": "desserts",
                "ديسيرت": "desserts",
            }

            cat_id = arabic_map.get(category, category)

            cat_info = next(
                (c for c in categories if c["id"] == cat_id), None
            )
            if not cat_info:
                available = " | ".join(
                    f"{c['name']} ({c['id']})" for c in categories
                )
                return (
                    f"❓ لم أجد القسم '{category}'.\n\n"
                    f"الأقسام المتاحة:\n{available}"
                )

            cat_dishes = [d for d in dishes if d["category"] == cat_id]
            lines = [
                f"{cat_info['name']}",
                f"_{cat_info['description']}_",
                "",
            ]
            for dish in cat_dishes:
                lines.append(format_dish_card(dish, currency))
                lines.append("")

            return "\n".join(lines)

        # ── get_dish_details ──────────────────────────────────────
        elif name == "get_dish_details":
            query = arguments.get("dish_name", "").lower().strip()
            found = next(
                (
                    d
                    for d in dishes
                    if query in d["name"].lower()
                    or query in d.get("name_en", "").lower()
                    or query in d.get("id", "")
                ),
                None,
            )
            if not found:
                similar = [
                    d["name"]
                    for d in dishes
                    if any(
                        w in d["name"].lower()
                        for w in query.split()
                    )
                ][:3]
                msg = f"❓ لم أجد طبق بهذا الاسم: '{arguments.get('dish_name')}'."
                if similar:
                    msg += f"\n\nهل تقصد: {' | '.join(similar)}؟"
                return msg
            return format_dish_full(found, currency)

        # ── search_menu ───────────────────────────────────────────
        elif name == "search_menu":
            keyword = arguments.get("keyword", "").lower().strip()
            if not keyword:
                return "يرجى تحديد كلمة للبحث."

            matches = []
            for dish in dishes:
                searchable = " ".join([
                    dish["name"].lower(),
                    dish.get("name_en", "").lower(),
                    dish.get("description", "").lower(),
                    " ".join(dish.get("ingredients", [])).lower(),
                    dish.get("category", ""),
                    "نباتي" if dish.get("is_vegetarian") else "",
                    "حار" if dish.get("spicy_level", 0) > 1 else "",
                ])
                if keyword in searchable:
                    matches.append(dish)

            if not matches:
                return (
                    f"😔 لم أجد أي طبق يحتوي على '{keyword}'.\n\n"
                    "جرّب كلمات مثل: دجاج، لحم، نباتي، حار، حلو..."
                )

            lines = [
                f"🔍 نتائج البحث عن *'{keyword}'*",
                f"وجدت {len(matches)} طبق:",
                "",
            ]
            for dish in matches:
                lines.append(format_dish_card(dish, currency))
                lines.append("")

            return "\n".join(lines)

        # ── get_recommendations ───────────────────────────────────
        elif name == "get_recommendations":
            preference = arguments.get("preference", "chef_picks").lower().strip()

            pref_map = {
                "نباتي": "for_vegetarians",
                "نباتية": "for_vegetarians",
                "vegetarian": "for_vegetarians",
                "حار": "for_spicy_lovers",
                "حارة": "for_spicy_lovers",
                "spicy": "for_spicy_lovers",
                "عائلة": "for_families",
                "عائلي": "for_families",
                "family": "for_families",
                "فردي": "for_solo_diners",
                "وحدي": "for_solo_diners",
                "solo": "for_solo_diners",
                "أطفال": "for_kids",
                "kids": "for_kids",
                "اقتصادي": "best_value",
                "رخيص": "best_value",
                "value": "best_value",
                "الشيف": "chef_picks",
                "chef": "chef_picks",
                "chef_picks": "chef_picks",
            }

            pref_key = pref_map.get(preference, "chef_picks")
            rec_ids = recommendations.get(pref_key, recommendations.get("chef_picks", []))

            emoji_map = {
                "for_vegetarians": "🥬",
                "for_spicy_lovers": "🌶️",
                "for_families": "👨‍👩‍👧‍👦",
                "for_solo_diners": "🧑",
                "for_kids": "👶",
                "best_value": "💰",
                "chef_picks": "👨‍🍳",
            }

            label_map = {
                "for_vegetarians": "الأطباق النباتية",
                "for_spicy_lovers": "للعشاق الحار!",
                "for_families": "مناسب للعائلات",
                "for_solo_diners": "للأكل المنفرد",
                "for_kids": "للأطفال",
                "best_value": "أفضل قيمة",
                "chef_picks": "اختيارات الشيف",
            }

            rec_dishes = [d for d in dishes if d["id"] in rec_ids]
            if not rec_dishes:
                rec_dishes = [d for d in dishes if d.get("is_recommended")][:4]

            icon = emoji_map.get(pref_key, "⭐")
            label = label_map.get(pref_key, "توصياتنا")

            lines = [
                f"{icon} *{label}*",
                f"_هذه اختياراتنا الخاصة لك!_",
                "",
            ]
            for dish in rec_dishes:
                lines.append(format_dish_card(dish, currency))
                lines.append("")

            return "\n".join(lines)

        # ── get_daily_specials ────────────────────────────────────
        elif name == "get_daily_specials":
            today_ar_map = {
                "Monday": "الإثنين",
                "Tuesday": "الثلاثاء",
                "Wednesday": "الأربعاء",
                "Thursday": "الخميس",
                "Friday": "الجمعة",
                "Saturday": "السبت",
                "Sunday": "الأحد",
            }
            today_en = datetime.now().strftime("%A")
            today_ar = today_ar_map.get(today_en, today_en)

            today_special = next(
                (s for s in daily_specials if s["day"] == today_ar), None
            )

            lines = [f"🎉 *عروض اليوم — {today_ar}*", ""]

            if today_special:
                dish = next(
                    (d for d in dishes if d["id"] == today_special["dish_id"]), None
                )
                if dish:
                    original = dish["price"]
                    disc = today_special["discount"]
                    discounted = round(original * (1 - disc / 100))
                    lines += [
                        f"🔥 *العرض الخاص اليوم:*",
                        f"{dish.get('emoji','🍽️')} *{dish['name']}*",
                        f"السعر الأصلي: ~~{original}~~ {currency}",
                        f"سعر اليوم: *{discounted} {currency}* 🎊 (خصم {disc}%)",
                        f"_{today_special['note']}_",
                        "",
                        format_dish_card(dish, currency),
                    ]
            else:
                lines.append(
                    "😄 لا يوجد عرض خاص اليوم، لكن الأسعار دائماً تسعد القلب!"
                )

            lines += [
                "",
                "📅 *عروض الأسبوع:*",
            ]
            for special in daily_specials:
                sp_dish = next(
                    (d for d in dishes if d["id"] == special["dish_id"]), None
                )
                if sp_dish:
                    marker = " ← *اليوم!*" if special["day"] == today_ar else ""
                    lines.append(
                        f"• *{special['day']}:* {sp_dish['name']} — "
                        f"خصم {special['discount']}%{marker}"
                    )

            return "\n".join(lines)

        # ── get_restaurant_info ───────────────────────────────────
        elif name == "get_restaurant_info":
            return (
                f"🏠 *{restaurant['name']}*\n"
                f"_{restaurant['tagline']}_\n\n"
                f"📞 *التليفون:* {restaurant['phone']}\n"
                f"⏰ *أوقات العمل:* {restaurant['working_hours']}\n"
                f"🚚 *وقت التوصيل:* {restaurant['delivery_time']}\n"
                f"💰 *الحد الأدنى للطلب:* {restaurant['min_order']} {currency}\n\n"
                f"💬 _نسعد بخدمتك! اسألنا عن أي طبق أو طلب عرض اليوم._"
            )

        else:
            return f"❓ أداة غير معروفة: {name}"

    return server


# ── Entry Point ───────────────────────────────────────────────────
async def main(menu_path: str):
    server = create_restaurant_server(menu_path)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="Restaurant Menu MCP Server")
    parser.add_argument(
        "--menu-path",
        default="./data/restaurant_menu.json",
        help="Path to restaurant menu JSON file",
    )
    args = parser.parse_args()

    asyncio.run(main(args.menu_path))
