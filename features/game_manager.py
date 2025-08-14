#!/usr/bin/env python3
"""
Minimal Pyrogram v2 table tracker for winner detection.

Mirrors the method used in test.py:
- Detect admin's table message containing "Full" and store its message_id.
- On edit of the same message with a ✅ after a username, detect winner and announce.

Register with:
    from features.game_manager import register_pyro_table_tracker
    register_pyro_table_tracker(app, GROUP_ID, ADMIN_IDS)
"""

import re
from datetime import datetime
from pyrogram import filters

# In-memory storage of active games keyed by message_id
_games = {}


def extract_game_data_from_message(message_text: str):
    lines = (message_text or "").strip().split("\n")
    usernames = []
    amount = None

    for line in lines:
        if "full" in line.lower():
            match = re.search(r"(\d+)\s*[Ff]ull", line)
            if match:
                amount = int(match.group(1))
        else:
            match = re.search(r"@?(\w+)", line)
            if match:
                usernames.append(match.group(1))

    if not usernames or not amount:
        return None

    return {
        "players": usernames,
        "amount": amount,
        "created_at": datetime.now(),
    }


def extract_winner_from_edited_message(message_text: str):
    patterns = [
        r"@(\w+)\s*✅",
        r"(\w+)\s*✅",
        r"✅\s*@(\w+)",
        r"✅\s*(\w+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message_text or "")
        if match:
            return match.group(1)
    return None


def register_pyro_table_tracker(app, group_id: int, admin_ids, *, database=None, balance_sheet_manager=None):
    """Register handlers to track admin table and detect winner.

    Optional integrations:
    - database: DatabaseManager for crediting winner and recording transactions
    - balance_sheet_manager: BalanceSheetManager to refresh pinned balance sheet after winner
    """

    @app.on_message(filters.chat(group_id) & filters.user(admin_ids) & filters.text)
    def on_admin_table_message(client, message):
        if not message or not message.text:
            return
        game_data = extract_game_data_from_message(message.text)
        if game_data:
            _games[message.id] = game_data

    @app.on_edited_message(filters.chat(group_id) & filters.user(admin_ids) & filters.text)
    def on_admin_edit_message(client, message):
        if not message or not message.text:
            return
        winner = extract_winner_from_edited_message(message.text)
        if winner and message.id in _games:
            game_data = _games.pop(message.id)

            # Announce in group
            client.send_message(
                group_id,
                f"🎉 Winner Found: @{winner}\n💰 Prize: {game_data['amount']}"
            )

            # Optional: credit winner and record transaction
            if database is not None:
                try:
                    winner_user = database.get_user_by_username(winner)
                    if winner_user:
                        new_balance = winner_user.get('balance', 0) + int(game_data['amount'])
                        database.update_user_balance(winner_user['user_id'], new_balance)

                        tx = {
                            'user_id': winner_user['user_id'],
                            'type': 'win',
                            'amount': int(game_data['amount']),
                            'description': 'Game win',
                            'timestamp': datetime.now(),
                        }
                        database.create_transaction(tx)

                        # DM winner (best-effort)
                        try:
                            client.send_message(
                                winner_user['user_id'],
                                f"🎉 Congratulations @{winner}! You won ₹{game_data['amount']}"
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

            # Optional: refresh pinned balance sheet
            if balance_sheet_manager is not None:
                try:
                    balance_sheet_manager.update_pinned_balance_sheet(group_id)
                except Exception:
                    pass
