import discord
import telegram
from facebook2telegram import send_post_to_tg

client = discord.Client()


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    print(f'{message.author.name}')

    if message.author.name in ("Spidey Bot", "Zapier"):
        send_post_to_tg(message.content)

        await message.channel.send(
            'Message successfully redirected to ATB Telegram Bot')

    if message.author.name == "Al_Wasilii":
        print('Boss just wrote')
        await message.channel.send('Hi boss, how are you?')
        send_post_to_tg(message.content)
        return

    if message.content.startswith('$hello'):
        await message.channel.send('Hello')

if __name__ == '__main__':
    client.run('OTQ0MzQzMzEyNDY1Mjg1MTQx.YhAOPg.oBLH9jAhz6Z3pEFZAUIM6QaZbWk')
