# 🎮 Ludo Bot Usage Examples

## Quick Start Guide for Admins

### 1. Starting a Game
Use the `/game` command with player mentions and bet amount:

```bash
/game @Mannux09 @CR_000 300 f
```

**Bot Response:**
```
🎮 Game Started!

👥 Players: @Mannux09, @CR_000
💰 Total Pot: ₹600
⏰ Game expires in 1 hour

📝 Edit any message with ✅ next to winner's @username to declare results!
```

### 2. Multiple Games Running
You can start multiple games simultaneously:

```bash
/game @player1 @player2 500 f
/game @player3 @player4 200 f
/game @player5 @player6 @player7 1000 f
```

### 3. Check Active Games
Monitor all running games:

```bash
/activegames
```

**Bot Response:**
```
🎮 Active Games:

🎲 Game ID: game_12345
👥 Players: @Mannux09, @CR_000
💰 Total Pot: ₹600
⏰ Time Left: 45 minutes

🎲 Game ID: game_12346
👥 Players: @player1, @player2
💰 Total Pot: ₹1000
⏰ Time Left: 58 minutes
```

### 4. Declaring Winners
Edit **ANY message** in the group to declare winners:

**Option A: Edit your own message**
```
Great match! @Mannux09 ✅ won this round!
```

**Option B: Edit any existing message**
```
@CR_000 played well but @Mannux09 ✅ takes the victory!
```

**Option C: Simple winner announcement**
```
@Mannux09 ✅
```

### 5. Winner Processing
**Bot automatically:**
- Finds @Mannux09 in active games
- Calculates commission (e.g., 5% = ₹30)
- Awards ₹570 to @Mannux09 (₹600 - ₹30)
- Sends private notifications
- Marks game as completed

## 💡 Pro Tips

### Multiple Winners
You can declare multiple winners in one message:
```
Both played amazing! @player1 ✅ @player2 ✅ share the pot
```

### Game Management
```bash
# Cancel a specific game (reply to any message about that game)
/cancel

# Set custom commission rates
/setcommission @Mannux09 3
/setcommission @CR_000 7

# Add balance manually
/addbalance @player1 1000
```

### Payment Confirmations
For payment tracking, use the standard format:
```
5000 received @Mannux09
3000 reviced @CR_000
```

## 🚨 Important Notes

### ✅ Things to Remember
- **Only admins** can use `/game` command
- **Any message edit** can declare winners
- **Games auto-expire** after 1 hour with refunds
- **Multiple games** can run simultaneously
- **Bot responses auto-delete** after 5 seconds

### ❌ Common Mistakes
- **Don't forget** the "f" after bet amount: `300 f`
- **Use @username** format for players: `@player1`
- **Add ✅ emoji** next to winner's username
- **Reply to original message** when using `/cancel`

## 📱 User Experience

### For Players
1. **Private notifications** when games start
2. **Balance automatically deducted** from their account
3. **Winner notifications** with prize amount and commission details
4. **Loser encouragement** messages
5. **Auto-refunds** if games expire

### Example Player Notifications

**Game Start:**
```
🎮 Game Started!

You've joined a game with ₹300 bet.
New balance: ₹1700

Best of luck! 🎲
```

**Winner Notification:**
```
🎉 Congratulations! You won!

💰 Prize: ₹570 (after 5% commission)
📊 New balance: ₹2270

🔗 Game: [link to group message]
```

**Loser Notification:**
```
😔 Better luck next time!

You lost ₹300 in this match.
Hope you win the next one! 🎲
```

## 🔧 Advanced Features

### Game Expiration
- Games automatically expire after 1 hour
- All players get full refunds
- Automatic notifications sent

### Commission System
- Each player has individual commission rates
- Winners pay commission on their winnings
- Losers pay the full bet amount
- Flexible rate management per user

### Transaction History
- All transactions logged in database
- Deposits, bets, wins, refunds tracked
- Admin actions recorded for audit

### Security
- Admin-only game management
- Balance validation before bets
- Secure user authentication
- Clean group chat with auto-delete

This system provides a complete, automated solution for managing Ludo groups while maintaining security and user experience!
