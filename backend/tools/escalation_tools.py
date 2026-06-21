from datetime import datetime
import random


def make_escalate_to_human():
    async def escalate_to_human(reason: str, summary: str) -> dict:
        seq = random.randint(100, 999)
        ref = f"ESC-{datetime.now().strftime('%Y%m%d')}-{seq}"
        return {
            "escalated": True,
            "reference": ref,
            "reason": reason,
            "summary": summary,
        }

    return escalate_to_human
