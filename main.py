import discord
import telegram
from facebook2telegram import main

client = discord.Client()
tg_bot = telegram.Bot('2063032857:AAHMVw8Glz0IU2Z1zaug-iYjpn9CKr-X8_M')
tg_bot.send_message(407628660, text='Bot initialized')


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    print(f'{message.author.name}')

    if message.author.name in ("Spidey Bot", "Zapier"):
        # send_webhook({"post_id": message.content})
        main(message.content)

        await message.channel.send(
            'Message successfully redirected to ATB Telegram Bot')

    if message.author.name == "Anima Bridge":
        print('Geting the post id.')
        permalink = message.content
        video_id = permalink.split('/')[-2]
        group_id = permalink.split('/')[2]
        post_id = '_'.join([group_id, video_id])
        print(post_id)
        # send_webhook({"post_id": post_id})

    if message.author.name == "Al_Wasilii":
        print('Boss just wrote')
        await message.channel.send('Hi boss, how are you?')
        main(message.content)
        return

    if message.content.startswith('$hello'):
        await message.channel.send('Hello')

if __name__ == '__main__':
    client.run('OTQ0MzQzMzEyNDY1Mjg1MTQx.YhAOPg.oBLH9jAhz6Z3pEFZAUIM6QaZbWk')
