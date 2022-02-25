# coding=utf-8
import enum
import json  # Used for tacking last dates
import logging  # Used for logging
import os
import sys  # Used for exiting the program
from datetime import datetime  # Used for date comparison
from enum import Enum
from typing import Optional

import telegram  # telegram-bot-python
from telegram.ext import Updater
from telegram.error import TelegramError, InvalidToken, BadRequest, TimedOut  # Error handling

from flask import Flask, request
import facebook  # facebook-sdk
import youtube_dl  # youtube-dl

server = Flask(__name__)

# Logging
FMT = "[{asctime} {levelname:^9}] {name}: {message}"
FORMATS = {
    logging.DEBUG: FMT,
    logging.INFO: f'\33[36m{FMT}\33[0m',
    logging.WARNING: f'\33[33m{FMT}\33[0m',
    logging.ERROR: f'\33[31m{FMT}\33[0m',
    logging.CRITICAL: f'\33[1m\33[31m{FMT}\33[0m',
}


class CustomFormatter(logging.Formatter):
    def format(self, record):
        log_fmt = FORMATS[record.levelno]
        formatter = logging.Formatter(log_fmt, style='{')
        return formatter.format(record)


handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[handler])
logger = logging.getLogger(__name__)

# youtube-dl
ydl = youtube_dl.YoutubeDL({'outtmpl': '%(id)s%(ext)s'})


# graph: facebook.GraphAPI
# bot: telegram.Bot


class PostType(Enum):
    PHOTO = enum.auto()
    VIDEO = enum.auto()
    SHARED = enum.auto()
    STATUS = enum.auto()


class Post:
    post_type: Optional[PostType]

    def __init__(self, post: dict):
        self.post_id = post['id'] if 'id' in post else None
        self.post_type = PostType[post['type'].upper()] if 'type' in post else None
        self.message = post['message'] if 'message' in post else None
        self.permalink: str = post['permalink_url'] if 'permalink_url' in post else None
        self.post_id = post['id'] if 'id' in post else None
        self.caption = post['caption'] if 'caption' in post else None
        if post['type'] == 'status':
            if 'attachments' in post:
                self.post_type = PostType.SHARED
                self.media_src = post['attachments']['data'][0]['media']['image']['src']
            else:
                self.media_src = None

        elif post['type'] == 'photo':
            self.media_src = post['attachments']['data'][0]['media']['image']['src']

        elif post['type'] == 'video':
            self.media_src = post['attachments']['data'][0]['media']['source']


def getDirectURLVideoYDL(url) -> str:
    """
    Get direct URL for the video
    """
    return f"youtube.com/watch?v={url.split('?')[0].split('/')[-1]}"


def postPhotoToChat(bot: telegram.Bot,
                    post: Post,
                    post_message: str, chat_id: str) -> telegram.Message:
    """
    Posts the post's picture with the appropriate caption.
    """
    direct_link = post.media_src

    try:
        message = bot.send_photo(
            chat_id=chat_id,
            photo=direct_link,
            caption=post_message)
        return message

    except (BadRequest, TimedOut):
        """If the picture can't be sent using its URL,
        it is downloaded locally and uploaded to Telegram."""
        print('Could not send photo file, sending link...')
        message = bot.send_message(  # Send direct link as a message
            chat_id=chat_id,
            text=direct_link + '\n' + post_message)
        return message


def postVideoToChat(bot: telegram.Bot, post: Post, post_message: str, chat_id: str):
    """
    This function tries to pass 3 different URLs to the Telegram API
    instead of downloading the video file locally to save bandwidth.

    *First option":  Direct video source
    *Second option": Direct video source from youtube-dl
    *Third option":  Direct video source with smaller resolution
    "Fourth option": Send the video link
    """
    # If youtube link, post the link
    if post.caption == 'youtube.com':
        print('Sending YouTube link...')
        message = bot.send_message(
            chat_id=chat_id,
            text=f"{post.message}\n{getDirectURLVideoYDL(post.media_src)}")
        return message

    try:
        message = bot.send_message(
            chat_id=chat_id,
            text=post_message)
        return message

    except TelegramError:  # If the API can't send the video
        logger.error('Could not send the video. Posting just the message and the link to the post.')
        message = bot.send_message(
            chat_id=chat_id,
            text=post.message
        )
        return message


# def postLinkToChat(bot: telegram.Bot,
#                    post: Post,
#                    post_message: str, chat_id: str):
#     """
#     Checks if the post has a message with its link in it. If it does,
#     it sends only the message. If not, it sends the link followed by the
#     post's message.
#     """
#     if post['link'] in post_message:
#         post_link = ''
#     else:
#         post_link = post['link']
#
#     bot.send_message(
#         chat_id=chat_id,
#         text=post_link + '\n' + post_message)


def postNewPost(graph: facebook.GraphAPI,
                bot: telegram.Bot,
                post: Post,
                chat_id: str) -> bool:
    """
    Checks the type of the Facebook post and if it's allowed by the
    settings file, then calls the appropriate function for each type.
    """
    # If it's a shared post, call this function for the parent post
    if post.post_type == PostType.SHARED:
        logger.info('This is a shared post.')
        message = bot.send_message(
            chat_id=chat_id,
            text='Shared post.'
        )
        return True

    """If there's a message in the post, and it's allowed by the
    settings file, store it in 'post_message', which will be passed to
    another function based on the post type."""
    if post.message is not None:
        post_message = post.message
    else:
        post_message = ''

    # Telegram doesn't allow media captions with more than 200 characters
    # Send separate message with the post's message
    if (len(post_message) > 200) and \
            (post.post_type == PostType.PHOTO or post.post_type == PostType.VIDEO):
        separate_message = post_message
        post_message = ''
        send_separate = True
    else:
        separate_message = ''
        send_separate = False

    if post.post_type == PostType.PHOTO:
        logger.info('Posting photo...')
        media_message = postPhotoToChat(bot, post, post_message, chat_id)
        if send_separate:
            media_message.reply_text(separate_message)
    elif post.post_type == PostType.VIDEO:
        logger.info('Posting video...')
        media_message = postVideoToChat(bot, post, post_message, chat_id)
        if send_separate:
            media_message.reply_text(separate_message)
    elif post.post_type == PostType.STATUS:
        logger.info('Posting status...')
        media_message = bot.send_message(
            chat_id=chat_id,
            text=post.message)
    else:
        logger.warning('This post is a {}, skipping...'.format(post.post_type))
        return False

    markup = telegram.InlineKeyboardMarkup(
        [[telegram.InlineKeyboardButton(
            text='Vezi postarea',
            url=post.permalink
        )]]
    )
    media_message.edit_reply_markup(markup)
    return True


def get_facebook_post(graph: facebook.GraphAPI, post_id: str):
    try:
        # Request to the GraphAPI with all the pages (list) and required fields
        post = graph.get_object(
            id=post_id,
            fields='id,type,attachments,message,permalink_url,caption')

        logger.info('The post was successfully retrieved')

    # Error in the Facebook API
    except facebook.GraphAPIError as e:
        logger.error('Error: Could not get Facebook posts.')
        """
        TODO: 'get_object' for every page individually, due to a bug
        in the Graph API that makes some pages return an OAuthException 1,
        which in turn doesn't allow the 'get_objects' method return a dict
        that has only the working pages, which is the expected behavior
        when one or more pages in 'facebeook_pages' are offline. One possible
        workaround is to create an Extended Page Access Token instead of an
        App Token, with the downside of having to renew it every two months.
        """
        return None, f"get_facebook_post threw an error:\n{e}"

    return post, "Successfully fetched Facebook posts."


def error(bot, update, err):
    logger.warning('Update "{}" caused error "{}"'.format(update, err))


def main(new_post_id: str):
    # Loading the settings from the environment
    admin_id = os.environ['ADMIN']
    channel_id = os.environ['CHANNEL']
    telegram_token = os.environ['TG_TOKEN']
    facebook_token = os.environ['FB_TOKEN']

    graph = facebook.GraphAPI(access_token=facebook_token, version='3.1')
    bot = telegram.Bot(token=telegram_token)

    # Log all errors
    updater = Updater(token=telegram_token)
    dispatcher = updater.dispatcher
    dispatcher.add_error_handler(error)

    # new_post, logg_msg = get_facebook_post(graph, new_post_id)
    logg_msg = 'Testing'
    new_post = Post(new_post_id)

    # If there is an admin chat ID in the settings file
    if admin_id is not None:
        try:
            # Sends a message to the bot Admin confirming the action
            bot.send_message(
                chat_id=admin_id,
                text=logg_msg)
        except TelegramError:
            logger.warning('Admin ID not found.')
            logger.info(logg_msg)
    else:
        logger.info(logg_msg)

    if postNewPost(graph, bot, new_post, channel_id):
        logger.info('Posted the post')
    else:
        logger.critical('Some error occurred while posting the posts.')

    # For now the bot will not be interactive, it will just look for new posts when the server is called.
    # updater.start_polling()
    # updater.idle()


@server.route('/webhook', methods=['POST', 'GET'])
def webhook():
    if request.method == "POST":
        logger.info('A POST request received:')
        # if "post_id" in request.json:
        #     main(request.json['post_id'])
        main(request.json)
        return 'success', 200
    else:
        # To validate the Facebook request
        logger.info(request.args["hub.challenge"])
        msg = request.args["hub.challenge"] if request.args["hub.challenge"] is not None else "waiting"
        return msg, 200


if __name__ == '__main__':
    server.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
