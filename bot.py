import discord
from discord.ext import commands
import os
import logging
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from logging.handlers import RotatingFileHandler
from utils.accounts_manager import AccountsManager

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
accounts_manager = AccountsManager(str(BASE_DIR / "accounts"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            BASE_DIR / "bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True


class TankiCommandTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if accounts_manager.is_blacklisted(interaction.user.id):
            language = accounts_manager.get_user_language(interaction.user.id)
            message = (
                "Access denied." if language.startswith("en") else "Доступ запрещён."
            )
            await interaction.response.send_message(message, ephemeral=True)
            return False
        return True


class TankiBot(commands.Bot):
    async def setup_hook(self):
        try:
            await self.load_extension("commands.stats")
            logger.info("✅ Ког stats загружен")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки stats: {e}")
            import traceback

            traceback.print_exc()
            raise

        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Синхронизировано {len(synced)} команд:")
            for cmd in synced:
                logger.info(f"   - /{cmd.name}")
        except Exception as e:
            logger.error(f"❌ Ошибка синхронизации: {e}")


bot = TankiBot(command_prefix="!", intents=intents, tree_cls=TankiCommandTree)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if accounts_manager.is_blacklisted(message.author.id):
        return

    if message.content.startswith("!"):
        command_name = message.content.split()[0][1:].lower()

        if command_name != "proxycheck":
            ctx = await bot.get_context(message)

            if ctx.valid:
                orig_send = ctx.send

                async def auto_delete_send(*args, **kwargs):
                    if "delete_after" not in kwargs:
                        kwargs["delete_after"] = 300.0

                    bot_message = await orig_send(*args, **kwargs)

                    async def delete_user_msg():
                        await asyncio.sleep(300)
                        try:
                            await message.delete()
                        except discord.HTTPException:
                            pass

                    asyncio.create_task(delete_user_msg())
                    return bot_message

                ctx.send = auto_delete_send

                await bot.invoke(ctx)
                return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен!")
    logger.info(f"ID бота: {bot.user.id}")


@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Принудительно синхронизирует слэш-команды"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Синхронизировано {len(synced)} команд")
        logger.info(f"Принудительная синхронизация: {len(synced)} команд")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка синхронизации: {e}")


if __name__ == "__main__":
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не задан в .env")
        raise SystemExit(1)

    logger.info("Запуск бота...")
    try:
        bot.run(token)
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
