import discord
from discord import app_commands
import logging
import aiohttp
from config import DISCORD_BOT_TOKEN
from product_cache import product_cache

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DiscordBot:
    def __init__(self):
        # Set up Discord bot with necessary intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        
        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self.token = DISCORD_BOT_TOKEN
        self.setup_slash_commands()
        self.setup_events()
        
    def setup_events(self):
        """Set up Discord client events"""
        @self.client.event
        async def on_ready():
            logger.info(f'Discord bot logged in as {self.client.user}')
            try:
                # Initialize product cache
                await product_cache.refresh()
                logger.info('Product cache initialized')

                synced = await self.tree.sync()
                logger.info(f'Synced {len(synced)} slash commands')

            except Exception as e:
                logger.error(f'Failed to sync slash commands: {e}')
    
    def setup_slash_commands(self):
        """Set up slash commands"""
        @self.tree.command(name='wtb', description='Want to buy - Search for a product by SKU and size')
        @app_commands.describe(
            sku='Product SKU code (e.g., FZ8117-100)',
            variant='Size/variant (e.g., 43)'
        )
        async def wtb_command(interaction: discord.Interaction, sku: str, variant: str):
            await interaction.response.defer(ephemeral=True)

            try:
                # Search for product
                product_info = product_cache.find_product(sku, variant)

                if not product_info:
                    await interaction.followup.send(
                        f"❌ Product not found for SKU: {sku} with variant: {variant}",
                        ephemeral=True
                    )
                    logger.info(f'WTB command: Product not found - SKU: {sku}, Variant: {variant}')
                    return

                # Send webhook to Discord
                webhook_url = "https://discord.com/api/webhooks/1032909099970613278/Foq-4fdyfJ8ZllL1ffzgrX2xTZ8bIDK0Ez5etEveU36mU0GxN_OvPZSSf62f8Egl5WSQ"

                embed = {
                    "title": product_info['product_name'],
                    "description": f"**SKU:** {product_info['sku']}\n**Size:** {product_info['variant']}\n**Price:** €{product_info['price']}",
                    "url": product_info['product_url'],
                    "color": 0x5865F2,  # Discord blurple color
                    "footer": {
                        "text": f"Requested by {interaction.user.display_name}"
                    },
                    "timestamp": discord.utils.utcnow().isoformat()
                }

                if product_info['image_url']:
                    embed['image'] = {"url": product_info['image_url']}

                webhook_payload = {
                    "embeds": [embed]
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(webhook_url, json=webhook_payload) as resp:
                        if resp.status in [200, 204]:
                            await interaction.followup.send(
                                f"✅ WTB request sent for {product_info['product_name']} - Size {product_info['variant']}",
                                ephemeral=True
                            )
                            logger.info(f'WTB command: Sent webhook for {sku} - {variant} by {interaction.user}')
                        else:
                            error_text = await resp.text()
                            logger.error(f'Webhook failed: {resp.status} - {error_text}')
                            await interaction.followup.send(
                                "❌ Failed to send WTB request. Please try again.",
                                ephemeral=True
                            )

            except Exception as e:
                logger.error(f'Error in WTB command: {e}', exc_info=True)
                await interaction.followup.send(
                    f"❌ An error occurred: {str(e)}",
                    ephemeral=True
                )
        
    async def start(self):
        """Start the Discord bot"""
        try:
            logger.info("Starting Discord bot...")
            await self.client.start(self.token)
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
    
    async def stop(self):
        """Stop the Discord bot"""
        try:
            await self.client.close()
            logger.info("Discord bot stopped")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

# Global instance
discord_bot = DiscordBot()