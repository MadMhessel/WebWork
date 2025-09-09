# Moderation Setup

1. **Grant Bot Rights**
   - Add the bot to your moderation channel or supergroup.
   - Give admin rights: Post Messages, Edit Messages, Delete Messages, Manage Topics.

2. **Get chat identifiers**
   - Use `@getidsbot` or API `getChat` to determine `MOD_CHAT_ID` for the moderation chat.
   - Determine `TARGET_CHAT_ID` for the publication channel.

3. **Configure environment**
   - Copy `.env.example` to `.env` and fill values:
     - `TELEGRAM_BOT_TOKEN`
     - `MOD_CHAT_ID`
     - `TARGET_CHAT_ID`
     - `ALLOWED_MODERATORS` – comma separated user ids
     - Optional: `PARSE_MODE` and `DISABLE_WEB_PAGE_PREVIEW`.

4. **Add moderators**
   - List of user ids in `ALLOWED_MODERATORS`.
   - Users outside the list will see an alert "Нет прав" when pressing buttons.

5. **Enable supergroup threads**
   - For best experience create a private supergroup and enable topics.
   - Use the group for moderation to get ForceReply support.

