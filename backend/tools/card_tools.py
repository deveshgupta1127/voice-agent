import datetime
import random
from database.queries import get_cards_by_customer, update_card_status


def make_get_card_list(db):
    async def get_card_list(customer_id: str) -> dict:
        cards = await get_cards_by_customer(db, customer_id)
        return {"cards": cards}

    return get_card_list


def make_block_card(db):
    async def block_card(card_id: str, reason: str) -> dict:
        from database.queries import get_cards_by_customer
        import aiosqlite

        cursor = await db.execute("SELECT * FROM cards WHERE card_id = ?", (card_id,))
        card = await cursor.fetchone()
        if card is None:
            return {"success": False, "reason": "Card not found"}

        card = dict(card)
        if card["status"] == "blocked":
            return {"success": False, "reason": "Card is already blocked"}

        today = datetime.date.today().strftime("%Y%m%d")
        ref = f"BLK-{today}-{random.randint(100, 999)}"

        updated = await update_card_status(db, card_id, "blocked", reason, ref)
        if not updated:
            return {"success": False, "reason": "Failed to update card status"}

        return {
            "success": True,
            "card_id": card_id,
            "new_status": "blocked",
            "reference_number": ref,
            "blocked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "message": f"Card ending {card['last_four']} has been blocked successfully.",
        }

    return block_card
